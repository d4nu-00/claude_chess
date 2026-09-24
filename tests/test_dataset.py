"""Dataset export from a synthetic run directory (no LLM, no Stockfish)."""

import gzip
import json

import chess

from claude_chess.dataset import export


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_export_builds_all_files(tmp_path):
    run = tmp_path / "20260101_000000_test"
    run.mkdir()
    board = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")
    (run / "meta.json").write_text(json.dumps({"model": "haiku", "search": "alphabeta"}))
    (run / "games.pgn").write_text('[Round "0"]\n[FEN "4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1"]\n'
                                   '[SetUp "1"]\n\n1. Rxd5 *\n')
    _write(run / "games.jsonl", [{"game": 0, "result": "1-0"}])
    search = {"mode": "alphabeta", "decided_by": "alpha-beta", "candidates": {
        "Rxd5": {"source": "engine", "tactical_cp": 900, "vetoed": False},
        "Rd3": {"source": "claude", "tactical_cp": -500, "engine_reply": "Qxd3", "vetoed": True},
        "Ke2": {"source": "claude", "tactical_cp": 0, "vetoed": False}}}
    _write(run / "decisions.jsonl", [{
        "game": 0, "ply": 1, "fen": board.fen(), "player": "hybrid-ctx(t2,haiku)", "color": "white",
        "san": "Rxd5", "uci": "d2d5", "candidates": [], "illegal_attempts": [], "calls": 2,
        "cost": 0.01, "note": "injected Rxd5", "search": search,
        "board_read": {"threats_real": ["Qxd2"]}}])
    _write(run / "traces.jsonl", [
        {"game": 0, "ply": 1, "call": 0, "role": "proposer", "fen": board.fen(), "prompt": "p",
         "response": json.dumps({"thinking": "Queen is loose.", "candidates": [
             {"move": "Rd3", "reason": "active rook", "prior": 0.5},
             {"move": "Ke2", "reason": "centralise", "prior": 0.3},
             {"move": "Rxd5", "reason": "wins the queen", "prior": 0.2}]})}])
    _write(run / "move_analysis.jsonl", [{"game": 0, "ply": 1, "cpl": 0, "eval_before": 400,
                                          "eval_after": 400, "best_move": "Rxd5"}])
    out = tmp_path / "ds"
    stats = export([run], out)
    assert stats["positions"] == 1 and stats["calls"] == 1 and stats["sft"] == 1
    row = json.loads((out / "positions.jsonl").read_text())
    assert row["agents"]["proposer"]["thinking"] == "Queen is loose."
    assert row["labels"]["game_result"] == 1.0 and row["split"] in ("train", "val", "test")
    sft = json.loads((out / "sft.jsonl").read_text())
    target = sft["messages"][-1]["content"]
    assert target.startswith("Threats [verified]: Qxd2")
    assert "Rd3: active rook [verified: rejected after Qxd3, loses 5.0 pawns]" in target
    assert target.endswith("Best move: Rxd5")
    pairs = [json.loads(l) for l in (out / "preferences.jsonl").read_text().splitlines()]
    assert [p["rejected"].splitlines()[-1] for p in pairs] == ["Best move: Rd3"]
    with gzip.open(out / "calls.jsonl.gz", "rt") as f:
        assert json.loads(f.readline())["role"] == "proposer"
