"""Post-game Stockfish analysis: centipawn loss per move, per-player aggregates, report.

Centipawn loss (CPL) for a move = eval_before - eval_after, both from the MOVER's view,
clamped to [0, 1000]. Mates are scored ±10000 (minus distance) before clamping, so
missing/allowing mate counts as a 1000cp loss. Book plies are excluded.
"""

from __future__ import annotations

import io
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn

from claude_chess.match.baselines import open_stockfish

CPL_CAP = 1000
MATE = 10000
INACCURACY, MISTAKE, BLUNDER = 50, 100, 300


def _eval_stm(eng: chess.engine.SimpleEngine, board: chess.Board, limit: chess.engine.Limit) -> int:
    """Eval of `board` from the side-to-move's view, in centipawns (mate = ±10000)."""
    if board.is_checkmate():
        return -MATE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    info = eng.analyse(board, limit)
    return info["score"].relative.score(mate_score=MATE)


def analyze_game(game: chess.pgn.Game, eng: chess.engine.SimpleEngine | None = None,
                 depth: int = 12, time: float | None = None) -> list[dict[str, Any]]:
    """Return one row per non-book move: {ply, color, player, san, cpl, best_eval, after_eval}."""
    own = eng is None
    if own:
        eng = open_stockfish()
    limit = chess.engine.Limit(time=time) if time else chess.engine.Limit(depth=depth)
    book = int(game.headers.get("BookPlies", "0") or 0)
    names = {chess.WHITE: game.headers.get("White", "white"), chess.BLACK: game.headers.get("Black", "black")}
    rows: list[dict[str, Any]] = []
    try:
        board = game.board()
        prev: int | None = None  # eval of current position, side-to-move view
        for ply, move in enumerate(game.mainline_moves(), start=1):
            if ply <= book:
                board.push(move)
                prev = None
                continue
            before = prev if prev is not None else _eval_stm(eng, board, limit)
            mover = board.turn
            san = board.san(move)
            board.push(move)
            after_opp = _eval_stm(eng, board, limit)
            after = -after_opp  # mover's view
            cpl = max(0, min(CPL_CAP, before - after))
            rows.append({"ply": ply, "color": "white" if mover == chess.WHITE else "black",
                         "player": names[mover], "san": san, "cpl": cpl,
                         "eval_before": before, "eval_after": after})
            prev = after_opp
    finally:
        if own:
            eng.quit()
    return rows


def rough_elo(acpl: float) -> int:
    """VERY rough ACPL->Elo mapping (common heuristic fit, ±300 at best)."""
    return int(round(3100 * math.exp(-0.01 * acpl)))


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
                pass  # tolerate a truncated last line after a crash
    return out


def _read_games(p: Path) -> list[chess.pgn.Game]:
    games = []
    if not p.exists():
        return games
    f = io.StringIO(p.read_text())
    while (g := chess.pgn.read_game(f)) is not None:
        games.append(g)
    return games


def summarize(games: list[chess.pgn.Game], move_rows: list[dict[str, Any]],
              decisions: list[dict[str, Any]]) -> dict[str, Any]:
    players: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "games": 0, "W": 0, "D": 0, "L": 0, "score": 0.0, "moves": 0, "cpl_sum": 0,
        "inaccuracies": 0, "mistakes": 0, "blunders": 0, "illegal_attempts": 0,
        "moves_with_illegal": 0, "forfeits": 0, "llm_calls": 0, "cost_usd": 0.0,
        "seconds": 0.0, "decisions": 0})
    results = []
    for g in games:
        h = g.headers
        w, b, r = h.get("White"), h.get("Black"), h.get("Result")
        results.append({"round": h.get("Round"), "white": w, "black": b, "result": r,
                        "termination": h.get("Termination", ""), "opening": h.get("Opening", "")})
        for name, won, lost in ((w, "1-0", "0-1"), (b, "0-1", "1-0")):
            p = players[name]
            if r not in ("1-0", "0-1", "1/2-1/2"):  # aborted (LLM unavailable): no result
                p["aborted"] = p.get("aborted", 0) + 1
                continue
            p["games"] += 1
            if r == won:
                p["W"] += 1
                p["score"] += 1
            elif r == lost:
                p["L"] += 1
            else:
                p["D"] += 1
                p["score"] += 0.5
    for m in move_rows:
        p = players[m["player"]]
        p["moves"] += 1
        p["cpl_sum"] += m["cpl"]
        p["inaccuracies"] += INACCURACY <= m["cpl"] < MISTAKE
        p["mistakes"] += MISTAKE <= m["cpl"] < BLUNDER
        p["blunders"] += m["cpl"] >= BLUNDER
    for d in decisions:
        p = players[d["player"]]
        p["decisions"] += 1
        n_ill = len(d.get("illegal_attempts") or [])
        p["illegal_attempts"] += n_ill
        p["moves_with_illegal"] += n_ill > 0
        p["forfeits"] += d.get("uci") is None
        p["llm_calls"] += d.get("calls") or 0
        p["cost_usd"] += d.get("cost") or 0.0
        p["seconds"] += d.get("seconds") or 0.0
    out = {}
    for name, p in players.items():
        acpl = p["cpl_sum"] / p["moves"] if p["moves"] else None
        nd = p["decisions"] or 1
        out[name] = {**{k: v for k, v in p.items() if k not in ("cpl_sum",)},
                     "acpl": round(acpl, 1) if acpl is not None else None,
                     "rough_elo": rough_elo(acpl) if acpl is not None else None,
                     "illegal_rate": round(p["moves_with_illegal"] / nd, 3),
                     "illegal_per_move": round(p["illegal_attempts"] / nd, 3),
                     "calls_per_move": round(p["llm_calls"] / nd, 2),
                     "avg_seconds": round(p["seconds"] / nd, 2),
                     "cost_usd": round(p["cost_usd"], 4)}
    return {"players": out, "games": results}


def render_report(summary: dict[str, Any], title: str = "Match report") -> str:
    lines = [f"# {title}", "", "## Players", "",
             "| player | G | W | D | L | score | ACPL | inacc | mist | blund | illegal rate | forfeits | calls/move | cost $ | s/move | rough Elo* |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, p in summary["players"].items():
        lines.append(
            f"| {name} | {p['games']} | {p['W']} | {p['D']} | {p['L']} | {p['score']}/{p['games']} | "
            f"{p['acpl']} | {p['inaccuracies']} | {p['mistakes']} | {p['blunders']} | "
            f"{p['illegal_rate']:.1%} | {p['forfeits']} | {p['calls_per_move']} | {p['cost_usd']:.4f} | "
            f"{p['avg_seconds']} | {p['rough_elo']} |")
    lines += ["", "\\*rough Elo = 3100·exp(-0.01·ACPL); a crude heuristic, not a rating.",
              "Thresholds: inaccuracy ≥50cp, mistake ≥100cp, blunder ≥300cp (per-move loss capped at 1000). "
              "Illegal rate = fraction of moves with ≥1 illegal attempt.", "", "## Games", "",
              "| # | white | black | result | termination | opening |", "|---|---|---|---|---|---|"]
    for g in summary["games"]:
        lines.append(f"| {g['round']} | {g['white']} | {g['black']} | {g['result']} | {g['termination']} | {g['opening']} |")
    return "\n".join(lines) + "\n"


def analyze_run(run_dir: str | Path, depth: int = 12, time: float | None = None,
                quiet: bool = False) -> dict[str, Any]:
    rd = Path(run_dir)
    games = _read_games(rd / "games.pgn")
    decisions = _read_jsonl(rd / "decisions.jsonl")
    finished = {g.headers.get("Round") for g in games}
    decisions = [d for d in decisions if str(d.get("game")) in finished]  # skip unfinished games
    move_rows: list[dict[str, Any]] = []
    eng = open_stockfish()
    try:
        for g in games:
            rows = analyze_game(g, eng, depth=depth, time=time)
            for r in rows:
                r["game"] = g.headers.get("Round")
            move_rows += rows
    finally:
        eng.quit()
    summary = summarize(games, move_rows, decisions)
    summary["analysis"] = {"depth": depth, "time": time}
    (rd / "summary.json").write_text(json.dumps(summary, indent=2))
    (rd / "move_analysis.jsonl").write_text("".join(json.dumps(r) + "\n" for r in move_rows))
    report = render_report(summary, title=f"Match report: {rd.name}")
    (rd / "report.md").write_text(report)
    if not quiet:
        print(report)
    return summary
