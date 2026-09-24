"""Permanent, queryable store of every game this harness has ever played.

SQLite at `db/games.sqlite` (tracked in git — it IS the research dataset), mirrored to a
plain `db/all_games.pgn`. WAL mode + a busy_timeout make it safe for the match runner's
worker threads (and separate `claude-chess db ingest` processes) to write concurrently.

Two write paths feed the same tables, both idempotent (upsert on natural keys):

  1. Live hook (`insert_game`, called by match/runner.py right after each game finishes):
     inserts the run row (once) and one games+moves row per finished game, straight from
     the in-memory `GameRecord` — no Stockfish analysis yet, so the analysis columns on
     `moves` are NULL.
  2. `ingest_run(run_dir)` (called at the end of match/analysis.py, and by `claude-chess db
     ingest`): re-reads the run directory from disk (meta.json, games.pgn, decisions.jsonl,
     move_analysis.jsonl) and upserts everything again, this time filling in the analysis
     columns. Safe to call any number of times on any run directory, including ones already
     covered by the live hook, or ones the live hook never saw at all (e.g. `runs/_invalid`).

See wiki/pages/games-database.md for the schema reference and example research queries.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Iterable

import chess
import chess.pgn

DEFAULT_DB_PATH = Path("db/games.sqlite")
DEFAULT_PGN_PATH = Path("db/all_games.pgn")

INACCURACY, MISTAKE, BLUNDER = 50, 100, 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    label       TEXT,
    started_at  TEXT,
    run_dir     TEXT,
    meta_json   TEXT,
    git_commit  TEXT,
    valid       INTEGER NOT NULL DEFAULT 1,
    ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS players (
    name        TEXT PRIMARY KEY,
    kind        TEXT,
    model       TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS games (
    game_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    idx             INTEGER NOT NULL,
    white           TEXT,
    black           TEXT,
    result          TEXT,
    termination     TEXT,
    aborted         INTEGER NOT NULL DEFAULT 0,
    opening_name    TEXT,
    opening_eco     TEXT,
    book_plies      INTEGER,
    plies           INTEGER,
    adjudication_cp INTEGER,
    pgn             TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_run ON games(run_id);
CREATE INDEX IF NOT EXISTS idx_games_white ON games(white);
CREATE INDEX IF NOT EXISTS idx_games_black ON games(black);

CREATE TABLE IF NOT EXISTS moves (
    game_id            TEXT NOT NULL REFERENCES games(game_id),
    ply                INTEGER NOT NULL,
    fen_before         TEXT,
    san                TEXT,
    uci                TEXT,
    player             TEXT,
    side               TEXT,
    book               INTEGER NOT NULL DEFAULT 0,
    phase              TEXT,
    opening             TEXT,
    llm_calls          INTEGER,
    cost_usd           REAL,
    seconds            REAL,
    illegal_attempts   TEXT,
    forced_random      INTEGER NOT NULL DEFAULT 0,
    candidates         TEXT,
    note               TEXT,
    own_eval           REAL,
    sf_eval_before     INTEGER,
    sf_eval_after      INTEGER,
    cp_loss            INTEGER,
    classification     TEXT,
    sf_best_move       TEXT,
    PRIMARY KEY (game_id, ply)
);
CREATE INDEX IF NOT EXISTS idx_moves_player ON moves(player);
CREATE INDEX IF NOT EXISTS idx_moves_classification ON moves(classification);
"""

_PLAYER_RE = re.compile(r"^(?P<base>.+?)(?:\((?P<inner>[^)]*)\))?(?:#[AB])?$")
_DEPTH_RE = re.compile(r"^d(\d+)$")
_ELO_RE = re.compile(r"^elo(\d+)$")
_SKILL_RE = re.compile(r"^skill(\d+)$")
_RUNDIR_RE = re.compile(r"^(\d{8}_\d{6})_")
_ADJ_CP_RE = re.compile(r"SF eval ([+-]\d+)cp")


# ── connection / schema ───────────────────────────────────────────────────


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the games DB with WAL + a generous busy_timeout so
    concurrent threads/processes can append safely."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ── player-name parsing ──────────────────────────────────────────────────


def parse_player_name(name: str) -> dict[str, Any]:
    """Split a player name like 'engine-ctx(d1,sonnet)' / 'stockfish(elo1320)' / 'random'
    into (kind, model, config). Best-effort: unrecognised tokens fall back to `model`."""
    m = _PLAYER_RE.match(name)
    base = m.group("base") if m else name
    inner = m.group("inner") if m else None
    config: dict[str, Any] = {}
    model: str | None = None
    if inner:
        for part in (p.strip() for p in inner.split(",")):
            if not part:
                continue
            if dm := _DEPTH_RE.match(part):
                config["depth"] = int(dm.group(1))
            elif em := _ELO_RE.match(part):
                config["elo"] = int(em.group(1))
            elif sm := _SKILL_RE.match(part):
                config["skill"] = int(sm.group(1))
            elif part == "full":
                config["strength"] = "full"
            else:
                model = part
    return {"kind": base, "model": model, "config": config}


def upsert_player(conn: sqlite3.Connection, name: str) -> None:
    p = parse_player_name(name)
    conn.execute(
        "INSERT INTO players (name, kind, model, config_json) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, model=excluded.model, "
        "config_json=excluded.config_json",
        (name, p["kind"], p["model"], json.dumps(p["config"])),
    )


# ── run helpers ───────────────────────────────────────────────────────────


def run_id_for(run_dir: str | Path) -> str:
    """Stable natural key for a run directory: `<name>` normally, `_invalid/<name>` for
    quarantined runs, so a run keeps its identity whether ingested from `runs/` or found
    via `--all`."""
    rd = Path(run_dir)
    if rd.parent.name == "_invalid":
        return f"_invalid/{rd.name}"
    return rd.name


def _started_at(run_dir: Path) -> str | None:
    m = _RUNDIR_RE.match(run_dir.name)
    if not m:
        return None
    try:
        dt = _dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        return dt.isoformat()
    except ValueError:
        return None


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5, cwd=Path(__file__).resolve().parent)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def upsert_run(conn: sqlite3.Connection, run_id: str, *, label: str | None, started_at: str | None,
               run_dir: str, meta_json: str | None, valid: bool) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, label, started_at, run_dir, meta_json, git_commit, valid, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(run_id) DO UPDATE SET label=excluded.label, started_at=excluded.started_at, "
        "run_dir=excluded.run_dir, meta_json=excluded.meta_json, git_commit=excluded.git_commit, "
        "valid=excluded.valid, ingested_at=excluded.ingested_at",
        (run_id, label, started_at, str(run_dir), meta_json, _git_commit(), int(valid),
         _dt.datetime.now().isoformat()),
    )


# ── move classification ──────────────────────────────────────────────────


def classify(cp_loss: int | None) -> str | None:
    if cp_loss is None:
        return None
    if cp_loss >= BLUNDER:
        return "blunder"
    if cp_loss >= MISTAKE:
        return "mistake"
    if cp_loss >= INACCURACY:
        return "inaccuracy"
    return "ok"


# ── game/move ingestion (shared by the live hook and full-run ingest) ────


def _adjudication_cp(termination: str) -> int | None:
    m = _ADJ_CP_RE.search(termination or "")
    return int(m.group(1)) if m else None


def _move_rows(game: chess.pgn.Game, decisions_by_ply: dict[int, dict[str, Any]],
               analysis_by_ply: dict[int, dict[str, Any]]) -> Iterable[dict[str, Any]]:
    h = game.headers
    book_plies = int(h.get("BookPlies", "0") or 0)
    white, black = h.get("White"), h.get("Black")
    board = game.board()
    from claude_chess.context import build_context  # local import: avoid a hard dep for callers who never need it

    for ply, move in enumerate(game.mainline_moves(), start=1):
        side = "white" if board.turn == chess.WHITE else "black"
        fen_before = board.fen()
        san = board.san(move)
        try:
            ctx = build_context(board, include_legal_moves=False)
            phase, opening = ctx.phase, ctx.opening
        except Exception:
            phase, opening = None, None
        board.push(move)

        is_book = ply <= book_plies
        d = decisions_by_ply.get(ply)
        a = analysis_by_ply.get(ply)
        row: dict[str, Any] = {
            "ply": ply, "fen_before": fen_before, "san": san, "uci": move.uci(),
            "player": (d.get("player") if d else (white if side == "white" else black)),
            "side": side, "book": int(is_book), "phase": phase, "opening": opening,
            "llm_calls": d.get("calls") if d else 0,
            "cost_usd": d.get("cost") if d else 0.0,
            "seconds": d.get("seconds") if d else 0.0,
            "illegal_attempts": json.dumps(d.get("illegal_attempts", []) if d else []),
            "forced_random": int(d.get("forced_random", False)) if d else 0,
            "candidates": json.dumps(d.get("candidates", []) if d else []),
            "note": d.get("note") if d else None,
            "own_eval": d.get("own_eval") if d else None,
            "sf_eval_before": a.get("eval_before") if a else None,
            "sf_eval_after": a.get("eval_after") if a else None,
            "cp_loss": a.get("cpl") if a else None,
            "classification": classify(a.get("cpl")) if a else None,
            "sf_best_move": a.get("best_move") if a else None,
        }
        yield row


def _upsert_game_and_moves(conn: sqlite3.Connection, run_id: str, idx: int, game: chess.pgn.Game,
                           decisions_by_ply: dict[int, dict[str, Any]],
                           analysis_by_ply: dict[int, dict[str, Any]]) -> int:
    h = game.headers
    white, black = h.get("White"), h.get("Black")
    result = h.get("Result", "*")
    termination = h.get("Termination", "")
    game_id = f"{run_id}:{idx}"
    opening_name = h.get("Opening")
    book_plies = int(h.get("BookPlies", "0") or 0)
    plies = int(h.get("PlyCount", "0") or 0)
    aborted = result not in ("1-0", "0-1", "1/2-1/2") or termination.startswith("aborted")

    opening_eco = None
    try:
        from claude_chess.context import build_context
        book_board = game.board()
        for mv in list(game.mainline_moves())[:book_plies]:
            book_board.push(mv)
        if opening_name:
            op = build_context(book_board, include_legal_moves=False).opening
            if op:
                opening_eco = op.split()[0]
    except Exception:
        pass

    for name in (white, black):
        if name:
            upsert_player(conn, name)

    conn.execute(
        "INSERT INTO games (game_id, run_id, idx, white, black, result, termination, aborted, "
        "opening_name, opening_eco, book_plies, plies, adjudication_cp, pgn) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(game_id) DO UPDATE SET run_id=excluded.run_id, idx=excluded.idx, "
        "white=excluded.white, black=excluded.black, result=excluded.result, "
        "termination=excluded.termination, aborted=excluded.aborted, "
        "opening_name=excluded.opening_name, opening_eco=excluded.opening_eco, "
        "book_plies=excluded.book_plies, plies=excluded.plies, "
        "adjudication_cp=excluded.adjudication_cp, pgn=excluded.pgn",
        (game_id, run_id, idx, white, black, result, termination, int(aborted),
         opening_name, opening_eco, book_plies, plies, _adjudication_cp(termination), str(game)),
    )

    n = 0
    for row in _move_rows(game, decisions_by_ply, analysis_by_ply):
        conn.execute(
            "INSERT INTO moves (game_id, ply, fen_before, san, uci, player, side, book, phase, "
            "opening, llm_calls, cost_usd, seconds, illegal_attempts, forced_random, candidates, "
            "note, own_eval, sf_eval_before, sf_eval_after, cp_loss, classification, sf_best_move) "
            "VALUES (:game_id,:ply,:fen_before,:san,:uci,:player,:side,:book,:phase,:opening,"
            ":llm_calls,:cost_usd,:seconds,:illegal_attempts,:forced_random,:candidates,:note,"
            ":own_eval,:sf_eval_before,:sf_eval_after,:cp_loss,:classification,:sf_best_move) "
            "ON CONFLICT(game_id, ply) DO UPDATE SET fen_before=excluded.fen_before, san=excluded.san, "
            "uci=excluded.uci, player=excluded.player, side=excluded.side, book=excluded.book, "
            "phase=excluded.phase, opening=excluded.opening, llm_calls=excluded.llm_calls, "
            "cost_usd=excluded.cost_usd, seconds=excluded.seconds, "
            "illegal_attempts=excluded.illegal_attempts, forced_random=excluded.forced_random, "
            "candidates=excluded.candidates, note=excluded.note, own_eval=excluded.own_eval, "
            "sf_eval_before=COALESCE(excluded.sf_eval_before, moves.sf_eval_before), "
            "sf_eval_after=COALESCE(excluded.sf_eval_after, moves.sf_eval_after), "
            "cp_loss=COALESCE(excluded.cp_loss, moves.cp_loss), "
            "classification=COALESCE(excluded.classification, moves.classification), "
            "sf_best_move=COALESCE(excluded.sf_best_move, moves.sf_best_move)",
            {**row, "game_id": game_id},
        )
        n += 1
    return n


# ── live hook (called from match/runner.py right after a game finishes) ──


def insert_game(run_dir: str | Path, label: str | None, meta_json: str | None,
                game: chess.pgn.Game, idx: int, decisions: list[dict[str, Any]],
                db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Insert one just-finished game (no Stockfish analysis yet). Called live by the
    runner; `ingest_run` will later fill in the analysis columns for the same rows."""
    run_dir = Path(run_dir)
    run_id = run_id_for(run_dir)
    decisions_by_ply = {d["ply"]: d for d in decisions}
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        upsert_run(conn, run_id, label=label, started_at=_started_at(run_dir), run_dir=str(run_dir),
                  meta_json=meta_json, valid=(run_dir.parent.name != "_invalid"))
        _upsert_game_and_moves(conn, run_id, idx, game, decisions_by_ply, {})
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ── full-run (re)ingest, from disk ────────────────────────────────────────


def _read_jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _read_games(p: Path) -> list[chess.pgn.Game]:
    games = []
    if not p.exists():
        return games
    f = io.StringIO(p.read_text())
    while (g := chess.pgn.read_game(f)) is not None:
        games.append(g)
    return games


def ingest_run(run_dir: str | Path, db_path: str | Path = DEFAULT_DB_PATH,
               valid: bool | None = None) -> dict[str, int]:
    """(Re)ingest a whole run directory from disk: meta.json, games.pgn, decisions.jsonl,
    move_analysis.jsonl (if present). Idempotent — safe to call again after analysis runs,
    or any number of times. Returns {"games": n, "moves": n}."""
    rd = Path(run_dir)
    run_id = run_id_for(rd)
    if valid is None:
        valid = rd.parent.name != "_invalid"

    meta_path = rd / "meta.json"
    meta_json = meta_path.read_text() if meta_path.exists() else None
    label = None
    if meta_json:
        try:
            label = json.loads(meta_json).get("label")
        except json.JSONDecodeError:
            pass

    games = _read_games(rd / "games.pgn")
    decisions = _read_jsonl(rd / "decisions.jsonl")
    analysis_rows = _read_jsonl(rd / "move_analysis.jsonl")

    decisions_by_game: dict[str, dict[int, dict[str, Any]]] = {}
    for d in decisions:
        decisions_by_game.setdefault(str(d.get("game")), {})[d["ply"]] = d
    analysis_by_game: dict[str, dict[int, dict[str, Any]]] = {}
    for a in analysis_rows:
        analysis_by_game.setdefault(str(a.get("game")), {})[a["ply"]] = a

    conn = connect(db_path)
    n_games = n_moves = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        upsert_run(conn, run_id, label=label, started_at=_started_at(rd), run_dir=str(rd),
                  meta_json=meta_json, valid=valid)
        for i, g in enumerate(games):
            try:
                idx = int(g.headers.get("Round", "0") or 0)
            except ValueError:
                idx = i
            n_moves += _upsert_game_and_moves(
                conn, run_id, idx, g,
                decisions_by_game.get(str(idx), {}), analysis_by_game.get(str(idx), {}))
            n_games += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {"games": n_games, "moves": n_moves}


def ingest_all(runs_root: str | Path = "runs", db_path: str | Path = DEFAULT_DB_PATH,
               include_invalid: bool = True) -> dict[str, Any]:
    """Ingest every run under `runs_root` (and, if requested, `runs_root/_invalid`)."""
    root = Path(runs_root)
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name != "_invalid" and (p / "meta.json").exists())
    if include_invalid and (root / "_invalid").is_dir():
        dirs += sorted(p for p in (root / "_invalid").iterdir()
                       if p.is_dir() and (p / "meta.json").exists())
    totals = {"runs": 0, "games": 0, "moves": 0, "run_dirs": []}
    for d in dirs:
        r = ingest_run(d, db_path=db_path)
        totals["runs"] += 1
        totals["games"] += r["games"]
        totals["moves"] += r["moves"]
        totals["run_dirs"].append(str(d))
    return totals


# ── export ────────────────────────────────────────────────────────────────


def export_pgn(out_path: str | Path, db_path: str | Path = DEFAULT_DB_PATH, *,
              player: str | None = None, include_invalid: bool = False) -> int:
    """Write every stored game's PGN to `out_path`. Returns the number of games written."""
    conn = connect(db_path)
    try:
        sql = "SELECT g.pgn FROM games g JOIN runs r ON r.run_id = g.run_id WHERE 1=1"
        params: list[Any] = []
        if not include_invalid:
            sql += " AND r.valid = 1"
        if player:
            sql += " AND (g.white = ? OR g.black = ?)"
            params += [player, player]
        sql += " ORDER BY g.run_id, g.idx"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for row in rows:
            f.write(row["pgn"] + "\n\n")
    return len(rows)


# ── stats ─────────────────────────────────────────────────────────────────


def player_stats(db_path: str | Path = DEFAULT_DB_PATH, *, include_invalid: bool = False,
                 include_aborted: bool = False) -> list[dict[str, Any]]:
    """Per-player W/D/L/score, ACPL, blunder rate, illegal rate, cost. By default only
    over valid, non-aborted games (the honest research subset)."""
    conn = connect(db_path)
    try:
        game_filter = "1=1"
        if not include_invalid:
            game_filter += " AND r.valid = 1"
        if not include_aborted:
            game_filter += " AND g.aborted = 0"
        games = conn.execute(
            f"SELECT g.* FROM games g JOIN runs r ON r.run_id = g.run_id WHERE {game_filter}").fetchall()
        moves = conn.execute(
            f"SELECT m.* FROM moves m JOIN games g ON g.game_id = m.game_id "
            f"JOIN runs r ON r.run_id = g.run_id WHERE {game_filter} AND m.book = 0").fetchall()
    finally:
        conn.close()

    stats: dict[str, dict[str, Any]] = {}

    def bucket(name: str) -> dict[str, Any]:
        return stats.setdefault(name, {
            "player": name, "games": 0, "W": 0, "D": 0, "L": 0, "score": 0.0,
            "moves": 0, "cpl_sum": 0, "blunders": 0, "illegal_moves": 0,
            "forced_random": 0, "llm_calls": 0, "cost_usd": 0.0, "seconds": 0.0,
        })

    for g in games:
        for name, won, lost in ((g["white"], "1-0", "0-1"), (g["black"], "0-1", "1-0")):
            if not name:
                continue
            b = bucket(name)
            b["games"] += 1
            if g["result"] == won:
                b["W"] += 1
                b["score"] += 1
            elif g["result"] == lost:
                b["L"] += 1
            elif g["result"] == "1/2-1/2":
                b["D"] += 1
                b["score"] += 0.5

    for m in moves:
        if not m["player"]:
            continue
        b = bucket(m["player"])
        b["moves"] += 1
        if m["cp_loss"] is not None:
            b["cpl_sum"] += m["cp_loss"]
        if m["classification"] == "blunder":
            b["blunders"] += 1
        illegal = json.loads(m["illegal_attempts"] or "[]")
        if illegal:
            b["illegal_moves"] += 1
        if m["forced_random"]:
            b["forced_random"] += 1
        b["llm_calls"] += m["llm_calls"] or 0
        b["cost_usd"] += m["cost_usd"] or 0.0
        b["seconds"] += m["seconds"] or 0.0

    out = []
    for b in stats.values():
        nm = b["moves"] or 1
        out.append({
            **{k: v for k, v in b.items() if k != "cpl_sum"},
            "acpl": round(b["cpl_sum"] / nm, 1) if b["moves"] else None,
            "blunder_rate": round(b["blunders"] / nm, 3) if b["moves"] else None,
            "illegal_rate": round(b["illegal_moves"] / nm, 3) if b["moves"] else None,
            "cost_usd": round(b["cost_usd"], 4),
        })
    out.sort(key=lambda p: -p["score"])
    return out
