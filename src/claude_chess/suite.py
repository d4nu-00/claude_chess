"""Offline position test suite (engine-dev practice: WAC/STS-style suites before games).

Games are noisy and expensive; a fixed suite of positions measures DECISION quality directly
and pairs every arm on identical positions. See wiki/pages/context-research.md ("0.").

build: positions where Claude players moved in past runs (half "hard" = the move played lost
       ≥150cp, half random), with full move history (context v3 needs the last move),
       Stockfish best move + eval as labels. Stockfish only labels/scores — never decides.
run:   play one decision per position with a player; score cp loss with Stockfish afterwards.
Metrics: mean cp loss (capped 1000), best-move hit rate, blunder rate (≥200cp), proposer
recall (SF best among Claude's own candidates), cost and seconds per position.
compare: paired sign-flip permutation test on per-position cp loss between two result files.
"""

from __future__ import annotations

import io
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import chess
import chess.engine
import chess.pgn

from claude_chess.match.baselines import open_stockfish

LIMIT = chess.engine.Limit(depth=14)
CAP = 1000


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def build(runs_root: str | Path, out: str | Path, n: int = 100, seed: int = 0) -> int:
    rng = random.Random(seed)
    hard, easy = [], []
    for rd in sorted(Path(runs_root).iterdir()):
        if not rd.is_dir() or rd.name.startswith("_") or not (rd / "games.pgn").exists():
            continue
        games = {}
        f = io.StringIO((rd / "games.pgn").read_text())
        while (g := chess.pgn.read_game(f)) is not None:
            games[int(g.headers.get("Round", "0"))] = [m.uci() for m in g.mainline_moves()]
        cpl = {(int(a["game"]), a["ply"]): a.get("cpl") for a in _jsonl(rd / "move_analysis.jsonl")}
        for d in _jsonl(rd / "decisions.jsonl"):
            if any(k in d["player"] for k in ("maia", "stockfish", "random")) or d["game"] not in games:
                continue
            c = cpl.get((d["game"], d["ply"]))
            if c is None:
                continue
            item = {"fen": d["fen"], "history_uci": games[d["game"]][: d["ply"] - 1], "src": f"{rd.name}:{d['game']}:{d['ply']}"}
            (hard if c >= 150 else easy).append(item)
    seen: set[str] = set()
    picked = []
    for pool, k in ((hard, n // 2), (easy, n)):
        rng.shuffle(pool)
        for it in pool:
            epd = chess.Board(it["fen"]).epd()
            if epd in seen or chess.Board(it["fen"]).is_game_over():
                continue
            seen.add(epd)
            picked.append(it)
            if len(picked) >= k:
                break
    eng = open_stockfish()
    try:
        for it in picked:
            info = eng.analyse(chess.Board(it["fen"]), LIMIT)
            it["sf_best"] = chess.Board(it["fen"]).san(info["pv"][0])
            it["sf_eval"] = info["score"].relative.score(mate_score=10000)
    finally:
        eng.quit()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("".join(json.dumps(it) + "\n" for it in picked))
    return len(picked)


def _board(it: dict) -> chess.Board:
    b = chess.Board()
    for u in it["history_uci"]:
        b.push_uci(u)
    assert b.fen() == it["fen"], "history does not reproduce the FEN"
    return b


def run(suite: str | Path, factory: Callable[[], object], out: str | Path, workers: int = 8) -> dict:
    items = _jsonl(Path(suite))

    def one(it: dict) -> dict:
        player = factory()
        b = _board(it)
        t0 = time.monotonic()
        try:
            d = player.choose_move(b.copy())
        finally:
            if hasattr(player, "close"):
                player.close()
        own = []
        si = getattr(d, "search_info", None) or {}
        if si.get("candidates"):
            own = [s for s, c in si["candidates"].items() if c.get("source") == "claude"]
        elif d.candidates:
            own = [c.san for c in d.candidates]
        else:
            own = [d.san] if d.san else []
        return {"src": it["src"], "fen": it["fen"], "san": d.san, "sf_best": it["sf_best"],
                "claude_candidates": own, "cost": d.cost_usd, "seconds": time.monotonic() - t0,
                "calls": d.llm_calls, "note": d.note}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(one, items))
    eng = open_stockfish()
    try:
        for it, r in zip(items, rows):
            b = chess.Board(it["fen"])
            if r["san"] is None:
                r["cp_loss"] = CAP
                continue
            b.push_san(r["san"])
            if b.is_checkmate():
                r["cp_loss"] = 0
                continue
            after = -eng.analyse(b, LIMIT)["score"].relative.score(mate_score=10000)
            r["cp_loss"] = max(0, min(CAP, it["sf_eval"] - after))
    finally:
        eng.quit()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return summarize(rows)


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    return {"positions": n,
            "mean_cp_loss": sum(r["cp_loss"] for r in rows) / n,
            "best_move_hit": sum(r["san"] == r["sf_best"] for r in rows) / n,
            "blunder_rate": sum(r["cp_loss"] >= 200 for r in rows) / n,
            "proposer_recall": sum(r["sf_best"] in r["claude_candidates"] for r in rows) / n,
            "cost_usd": sum(r["cost"] for r in rows), "usd_per_pos": sum(r["cost"] for r in rows) / n,
            "s_per_pos": sum(r["seconds"] for r in rows) / n}


def compare(a_path: str | Path, b_path: str | Path, n: int = 20000, seed: int = 0) -> dict:
    """Paired sign-flip permutation test on per-position cp loss (a − b)."""
    a = {r["src"]: r for r in _jsonl(Path(a_path))}
    b = {r["src"]: r for r in _jsonl(Path(b_path))}
    keys = sorted(a.keys() & b.keys())
    diffs = [a[k]["cp_loss"] - b[k]["cp_loss"] for k in keys]
    obs = sum(diffs) / len(diffs)
    rng = random.Random(seed)
    extreme = sum(abs(sum(d if rng.random() < 0.5 else -d for d in diffs) / len(diffs)) >= abs(obs) - 1e-9
                  for _ in range(n))
    return {"paired_positions": len(keys), "mean_cp_loss_diff": obs, "p_value": (extreme + 1) / (n + 1),
            "a": summarize([a[k] for k in keys]), "b": summarize([b[k] for k in keys])}
