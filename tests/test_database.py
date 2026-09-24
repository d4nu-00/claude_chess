import json
import shutil
import sqlite3
import threading

import chess
import chess.pgn
import pytest

from claude_chess.match import database as db
from claude_chess.match.baselines import RandomPlayer, StockfishPlayer
from claude_chess.match.runner import play_match

needs_sf = pytest.mark.skipif(
    shutil.which("stockfish") is None and not __import__("os").path.exists("/opt/homebrew/bin/stockfish"),
    reason="stockfish not installed")


# ── parse_player_name ───────────────────────────────────────────────────────


def test_parse_player_name():
    assert db.parse_player_name("engine-ctx(d1,sonnet)") == {
        "kind": "engine-ctx", "model": "sonnet", "config": {"depth": 1}}
    assert db.parse_player_name("engine-noctx(d2,haiku)") == {
        "kind": "engine-noctx", "model": "haiku", "config": {"depth": 2}}
    assert db.parse_player_name("naive(sonnet)") == {
        "kind": "naive", "model": "sonnet", "config": {}}
    assert db.parse_player_name("stockfish(elo1320)") == {
        "kind": "stockfish", "model": None, "config": {"elo": 1320}}
    assert db.parse_player_name("stockfish(skill5)") == {
        "kind": "stockfish", "model": None, "config": {"skill": 5}}
    assert db.parse_player_name("stockfish(full)") == {
        "kind": "stockfish", "model": None, "config": {"strength": "full"}}
    assert db.parse_player_name("random") == {"kind": "random", "model": None, "config": {}}
    # #A / #B disambiguation suffixes (added when both players share a name) don't change kind
    assert db.parse_player_name("random#A")["kind"] == "random"


def test_classify():
    assert db.classify(None) is None
    assert db.classify(10) == "ok"
    assert db.classify(60) == "inaccuracy"
    assert db.classify(150) == "mistake"
    assert db.classify(400) == "blunder"


# ── full pipeline: play a real (synthetic) match, ingest, inspect ─────────


@needs_sf
def test_ingest_run_from_runner(tmp_path):
    runs_root = tmp_path / "runs"
    db_path = tmp_path / "games.sqlite"
    rd = play_match(lambda: RandomPlayer(1), lambda: StockfishPlayer(skill=0, time=0.01),
                    games=2, max_plies=24, runs_root=runs_root, label="dbtest", parallel=2,
                    analysis_depth=5, quiet=True, db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        n_games = conn.execute("select count(*) from games").fetchone()[0]
        n_moves = conn.execute("select count(*) from moves").fetchone()[0]
        assert n_games == 2
        assert n_moves > 0

        run_row = conn.execute("select * from runs").fetchone()
        assert run_row["label"] == "dbtest"
        assert run_row["valid"] == 1
        assert run_row["run_id"] == db.run_id_for(rd)

        # players table got both names, parsed
        names = {r["name"] for r in conn.execute("select name from players")}
        assert "random" in names
        assert "stockfish(skill0)" in names
        sf_row = conn.execute("select * from players where name = 'stockfish(skill0)'").fetchone()
        assert sf_row["kind"] == "stockfish"
        assert json.loads(sf_row["config_json"]) == {"skill": 0}

        # analysis columns were merged in by analyze_run's ingest_run call
        analysed = conn.execute(
            "select count(*) from moves where book = 0 and cp_loss is not null").fetchone()[0]
        assert analysed > 0
        classified = conn.execute(
            "select distinct classification from moves where classification is not null").fetchall()
        assert {r[0] for r in classified} <= {"ok", "inaccuracy", "mistake", "blunder"}

        # book moves are flagged and carry no decision/analysis data
        book_row = conn.execute("select * from moves where book = 1 limit 1").fetchone()
        assert book_row["cp_loss"] is None
        assert book_row["llm_calls"] == 0

        # phase/opening columns (from the context builder) are populated
        has_phase = conn.execute("select count(*) from moves where phase is not null").fetchone()[0]
        assert has_phase == n_moves
    finally:
        conn.close()


@needs_sf
def test_idempotent_reingest(tmp_path):
    runs_root = tmp_path / "runs"
    db_path = tmp_path / "games.sqlite"
    rd = play_match(lambda: RandomPlayer(2), lambda: StockfishPlayer(skill=0, time=0.01),
                    games=1, max_plies=16, runs_root=runs_root, label="idem", parallel=1,
                    analysis_depth=5, quiet=True, db_path=db_path)

    conn = sqlite3.connect(db_path)
    n_games_before = conn.execute("select count(*) from games").fetchone()[0]
    n_moves_before = conn.execute("select count(*) from moves").fetchone()[0]
    conn.close()

    for _ in range(3):
        r = db.ingest_run(rd, db_path=db_path)
        assert r["games"] == n_games_before

    conn = sqlite3.connect(db_path)
    assert conn.execute("select count(*) from games").fetchone()[0] == n_games_before
    assert conn.execute("select count(*) from moves").fetchone()[0] == n_moves_before
    assert conn.execute("select count(*) from runs").fetchone()[0] == 1
    conn.close()


# ── aborted games ────────────────────────────────────────────────────────


def _fake_game(white="a", black="b", result="*", termination="aborted (LLM unavailable: x)",
              book_plies=0, opening=None):
    board = chess.Board()
    game = chess.pgn.Game.from_board(board)
    h = game.headers
    h["White"], h["Black"], h["Result"] = white, black, result
    h["Termination"], h["BookPlies"], h["PlyCount"] = termination, str(book_plies), str(board.ply())
    if opening:
        h["Opening"] = opening
    return game


def test_aborted_game_ingest(tmp_path):
    run_dir = tmp_path / "20260101_000000_abortedtest"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"label": "abortedtest"}))
    game = _fake_game(white="engine-ctx(d1,sonnet)", black="random",
                      result="*", termination="aborted (LLM unavailable: rate limited)")
    (run_dir / "games.pgn").write_text(str(game) + "\n\n")

    db_path = tmp_path / "games.sqlite"
    r = db.ingest_run(run_dir, db_path=db_path)
    assert r["games"] == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("select * from games").fetchone()
    assert row["result"] == "*"
    assert row["aborted"] == 1
    conn.close()

    # stats exclude aborted games by default
    stats = db.player_stats(db_path=db_path)
    assert stats == []
    stats_incl = db.player_stats(db_path=db_path, include_aborted=True)
    names = {p["player"] for p in stats_incl}
    assert "engine-ctx(d1,sonnet)" in names and "random" in names


# ── invalid runs (quarantined) ──────────────────────────────────────────


def test_invalid_run_flagged(tmp_path):
    invalid_dir = tmp_path / "_invalid" / "20260101_000000_bad"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "meta.json").write_text(json.dumps({"label": "bad"}))
    game = _fake_game(white="engine-ctx(d1,sonnet)", black="engine-noctx(d1,sonnet)",
                      result="1-0", termination="checkmate")
    (invalid_dir / "games.pgn").write_text(str(game) + "\n\n")

    db_path = tmp_path / "games.sqlite"
    db.ingest_run(invalid_dir, db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_row = conn.execute("select * from runs").fetchone()
    assert run_row["valid"] == 0
    assert run_row["run_id"] == "_invalid/20260101_000000_bad"
    conn.close()

    # excluded from stats by default, included with include_invalid
    assert db.player_stats(db_path=db_path) == []
    stats = db.player_stats(db_path=db_path, include_invalid=True)
    assert any(p["player"] == "engine-ctx(d1,sonnet)" for p in stats)


def test_ingest_all(tmp_path):
    runs_root = tmp_path / "runs"
    good = runs_root / "20260101_000000_good"
    good.mkdir(parents=True)
    (good / "meta.json").write_text(json.dumps({"label": "good"}))
    (good / "games.pgn").write_text(str(_fake_game(result="1-0", termination="checkmate")) + "\n\n")

    bad = runs_root / "_invalid" / "20260101_000000_bad"
    bad.mkdir(parents=True)
    (bad / "meta.json").write_text(json.dumps({"label": "bad"}))
    (bad / "games.pgn").write_text(str(_fake_game(result="1-0", termination="checkmate")) + "\n\n")

    db_path = tmp_path / "games.sqlite"
    totals = db.ingest_all(runs_root, db_path=db_path, include_invalid=True)
    assert totals["runs"] == 2
    assert totals["games"] == 2

    conn = sqlite3.connect(db_path)
    valids = {r[0]: r[1] for r in conn.execute("select run_id, valid from runs")}
    conn.close()
    assert valids == {"20260101_000000_good": 1, "_invalid/20260101_000000_bad": 0}


# ── export ───────────────────────────────────────────────────────────────


def test_export_pgn(tmp_path):
    run_dir = tmp_path / "20260101_000000_exp"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"label": "exp"}))
    (run_dir / "games.pgn").write_text(
        str(_fake_game(white="alice", black="bob", result="1-0", termination="checkmate")) + "\n\n")
    db_path = tmp_path / "games.sqlite"
    db.ingest_run(run_dir, db_path=db_path)

    out = tmp_path / "all.pgn"
    n = db.export_pgn(out, db_path=db_path)
    assert n == 1
    text = out.read_text()
    assert '[White "alice"]' in text

    n2 = db.export_pgn(out, db_path=db_path, player="nobody")
    assert n2 == 0


# ── concurrency ─────────────────────────────────────────────────────────


def test_concurrent_insert_game(tmp_path):
    """Many threads inserting different games into the same DB file concurrently
    (mirrors match/runner.py's --parallel worker threads) must not lose rows or corrupt
    the DB under WAL + busy_timeout."""
    db_path = tmp_path / "games.sqlite"
    run_dir = tmp_path / "20260101_000000_concurrent"
    run_dir.mkdir()
    n_threads = 12
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            game = _fake_game(white=f"p{i}", black="opponent", result="1-0", termination="checkmate")
            db.insert_game(run_dir, "concurrent", None, game, i, [], db_path=db_path)
        except Exception as e:  # pragma: no cover - surfaced via `errors`
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    assert conn.execute("select count(*) from games").fetchone()[0] == n_threads
    assert conn.execute("select count(*) from runs").fetchone()[0] == 1
    for i in range(n_threads):
        assert conn.execute("select 1 from games where game_id = ?",
                            (f"20260101_000000_concurrent:{i}",)).fetchone() is not None
    conn.close()


# ── stats ────────────────────────────────────────────────────────────────


def test_player_stats_basic(tmp_path):
    run_dir = tmp_path / "20260101_000000_stats"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"label": "stats"}))
    g1 = _fake_game(white="alice", black="bob", result="1-0", termination="checkmate")
    g2 = _fake_game(white="bob", black="alice", result="1/2-1/2", termination="fifty")
    g1.headers["Round"], g2.headers["Round"] = "0", "1"
    (run_dir / "games.pgn").write_text(str(g1) + "\n\n" + str(g2) + "\n\n")

    db_path = tmp_path / "games.sqlite"
    db.ingest_run(run_dir, db_path=db_path)
    stats = {p["player"]: p for p in db.player_stats(db_path=db_path)}
    assert stats["alice"]["W"] == 1 and stats["alice"]["D"] == 1
    assert stats["alice"]["score"] == 1.5
    assert stats["bob"]["L"] == 1 and stats["bob"]["D"] == 1
    assert stats["bob"]["score"] == 0.5
