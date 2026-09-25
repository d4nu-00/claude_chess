"""Learning loop: after a game by the learner model, turn its Stockfish-verified mistakes
into lessons for the learned KB (`knowledge_learned/`), keeping only lessons that pass a
replay gate. See wiki/pages/learning-loop.md.

    find mistakes ──► Claude (learner model) writes a general lesson ──► gate ──► accept/reject
    (SF cp loss)       from position, its reasoning,                     replay target +
                       SF best line and refutation                       tag-matched controls,
                                                                         baseline KB vs +lesson

Stockfish only *selects and scores* — the lesson text and every replayed move are Claude's.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import chess
import chess.engine
import chess.pgn

from claude_chess.context import build_context, render_context
from claude_chess.context import learned
from claude_chess.context.concepts import TAG_WEIGHTS

SF_LIMIT = chess.engine.Limit(depth=18)
CAP = 1000

LESSON_SYSTEM = """You are a chess coach writing notes for yourself, a strong player who \
made a mistake in a real game. You will see the position, the move you chose and your reasoning \
at the time, and the engine's verdict. Write ONE short, GENERAL lesson that would have prevented \
this kind of mistake in other positions, not just this one.

Rules:
- Generalise from the pattern (piece setup, pawn structure, tactical motif, endgame type), \
never from exact squares of this game unless they define the pattern.
- Be concrete and actionable: what to check, when, and what it looks like.
- At most 3 summary bullets, each at most 30 words.
- tags: choose 1-4 from the ALLOWED TAGS list. The FIRST tag must be one of the POSITION TAGS \
(it decides when the lesson is shown), so pick the most specific one that captures the pattern.
- If the mistake is a one-off miscalculation with no transferable pattern, or an existing \
lesson already covers it, answer with action "skip".
Reply with JSON only:
{"action": "new" | "skip", "title": "...", "tags": ["..."], "summary": ["...", "..."], \
"diagnosis": "one sentence: what you missed", "why_general": "one sentence"}"""


# ── inputs ──────────────────────────────────────────────────────────────────


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _game_moves(run_dir: Path) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    pgn = run_dir / "games.pgn"
    if pgn.exists():
        f = io.StringIO(pgn.read_text())
        while (g := chess.pgn.read_game(f)) is not None:
            out[int(g.headers.get("Round", "0"))] = [m.uci() for m in g.mainline_moves()]
    return out


def _board(history_uci: list[str]) -> chess.Board:
    b = chess.Board()
    for u in history_uci:
        b.push_uci(u)
    return b


def find_mistakes(run_dir: Path, learner: str, min_cp: int = 100, max_n: int = 2,
                  lost_cp: int = 800) -> list[dict]:
    """Learner-model moves that lost >= min_cp, worst first; skips already-decided positions."""
    moves = _game_moves(run_dir)
    dec = {(int(d["game"]), d["ply"]): d for d in _jsonl(run_dir / "decisions.jsonl")}
    out = []
    for a in _jsonl(run_dir / "move_analysis.jsonl"):
        g, ply = int(a["game"]), a["ply"]
        d = dec.get((g, ply))
        if d is None or learner not in d["player"] or (a.get("cpl") or 0) < min_cp:
            continue
        eb = a.get("eval_before")
        if eb is not None and abs(eb) >= lost_cp:  # already won/lost: cp loss is noise
            continue
        if g not in moves:
            continue
        out.append({"game": g, "ply": ply, "fen": d["fen"], "history_uci": moves[g][: ply - 1],
                    "played": d["san"], "cpl": a["cpl"], "player": d["player"],
                    "src": f"{run_dir.name}:{g}:{ply}", "decision": d})
    out.sort(key=lambda m: -m["cpl"])
    # at most one lesson per 10-ply window: neighbouring errors are usually one mistake
    picked: list[dict] = []
    for m in out:
        if all(m["game"] != p["game"] or abs(m["ply"] - p["ply"]) >= 10 for p in picked):
            picked.append(m)
    return picked[:max_n]


def _trace_text(run_dir: Path, game: int, ply: int, limit: int = 1500) -> str:
    rows = [t for t in _jsonl(run_dir / "traces.jsonl") if int(t.get("game", -1)) == game and t.get("ply") == ply]
    parts = [f"[{t.get('role')}] {str(t.get('response', ''))[:600]}" for t in rows]
    return "\n".join(parts)[:limit]


def _pv_san(board: chess.Board, pv: list[chess.Move], n: int = 8) -> str:
    return board.variation_san(pv[:n]) if pv else ""


def engine_verdict(eng: chess.engine.SimpleEngine, board: chess.Board, played: str) -> dict:
    best = eng.analyse(board, SF_LIMIT)
    after = board.copy()
    after.push_san(played)
    refute = eng.analyse(after, SF_LIMIT)
    return {"best_line": _pv_san(board, best.get("pv", [])),
            "best_cp": best["score"].relative.score(mate_score=10000),
            "refutation_line": _pv_san(after, refute.get("pv", [])),
            "after_cp": -refute["score"].relative.score(mate_score=10000)}


# ── lesson writing ──────────────────────────────────────────────────────────


def lesson_prompt(m: dict, board: chess.Board, verdict: dict, trace: str, ctx_version: int,
                  kb: Path = learned.DEFAULT_DIR) -> tuple[str, list[str]]:
    ctx = build_context(board, include_legal_moves=False, version=ctx_version)
    existing = [f"- {les.title} [tags: {', '.join(les.tags)}]" for les in learned.load(kb)]
    cands = m["decision"].get("candidates") or []
    cand_txt = "; ".join(f"{c.get('san')} ({c.get('reason', '')})" for c in cands[:4])
    prompt = f"""{render_context(ctx, include_legal_moves=False)}

## What happened
- You played **{m['played']}**. Your candidates were: {cand_txt or 'n/a'}
- Your reasoning at the time:
{trace or '(not recorded)'}

## Engine verdict (Stockfish, depth {SF_LIMIT.depth})
- Best: {verdict['best_line']}  (eval {verdict['best_cp']:+} cp for the side to move)
- After your {m['played']}: {verdict['refutation_line']}  (eval {verdict['after_cp']:+} cp) \
— you lost {m['cpl']} cp.

## POSITION TAGS (first lesson tag must be one of these)
{', '.join(ctx.tags)}

## ALLOWED TAGS
{', '.join(sorted(set(TAG_WEIGHTS) | set(ctx.tags)))}

## Existing lessons (don't duplicate)
{chr(10).join(existing) or '(none yet)'}
"""
    return prompt, ctx.tags


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "lesson"


def validate(data: dict, position_tags: list[str]) -> dict | None:
    if data.get("action") != "new":
        return None
    allowed = set(TAG_WEIGHTS) | set(position_tags)
    tags = [t for t in (data.get("tags") or []) if isinstance(t, str) and t in allowed][:4]
    summary = [str(s).strip() for s in (data.get("summary") or []) if str(s).strip()][:3]
    if not tags or tags[0] not in position_tags or not summary or not data.get("title"):
        return None
    out = {"title": str(data["title"]).strip()[:90], "tags": tags, "summary": summary,
           "diagnosis": str(data.get("diagnosis", "")), "why_general": str(data.get("why_general", ""))}
    for k in ("narrative", "turning_point_ply", "misconception"):  # slow-drift reviews
        if k in data:
            out[k] = data[k]
    return out


def lesson_markdown(lesson_id: str, les: dict, source: str, learner: str, evidence: list[str],
                    gate: dict | None, status: str = "active", kind: str = "mistake",
                    src_rec: dict | None = None) -> str:
    src_block = ""
    if src_rec:
        pgn = src_rec.get("pgn", "")
        info = {k: v for k, v in src_rec.items() if k != "pgn"}
        src_block = (f"\n## Source game\n```json\n{json.dumps(info, indent=1)}\n```\n"
                     + (f"```pgn\n{pgn}\n```\n" if pgn else ""))
    return f"""---
title: {les['title']}
tags: [{', '.join(les['tags'])}]
status: {status}
kind: {kind}
id: {lesson_id}
source: {source}
learner: {learner}
created: {time.strftime('%Y-%m-%d %H:%M')}
---
## Summary
{chr(10).join('- ' + x for x in les['summary'])}

## Evidence
{chr(10).join('- ' + e for e in evidence)}
- Gate: {json.dumps(gate) if gate else 'n/a'}
{src_block}"""


def source_record(run_dir: Path, game: int, kb: Path) -> dict:
    """Self-contained provenance so a lesson can be re-judged later (stronger model/engine) even
    if runs/ (git-ignored) is gone: the game itself, who played, how it was judged."""
    import subprocess
    rec: dict[str, Any] = {"db_game_id": f"{run_dir.name}:{game}", "run": run_dir.name,
                           "judge": f"stockfish depth {SF_LIMIT.depth} (lesson) / move_analysis in run",
                           "kb_version_at_learning": learned.version(kb)}
    try:
        with open_sf_version() as v:
            rec["engine"] = v
    except Exception:  # noqa: BLE001
        pass
    try:
        rec["harness_commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                               text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        rec["harness_commit"] = None
    pgn = run_dir / "games.pgn"
    if pgn.exists():
        f = io.StringIO(pgn.read_text())
        while (g := chess.pgn.read_game(f)) is not None:
            if int(g.headers.get("Round", "-1")) == game:
                h = g.headers
                rec.update({"white": h.get("White"), "black": h.get("Black"), "result": h.get("Result"),
                            "date": h.get("Date"), "termination": h.get("Termination"),
                            "pgn": str(g)})
                break
    meta = run_dir / "meta.json"
    if meta.exists():
        mj = json.loads(meta.read_text())
        rec["player_config"] = {k: mj.get(k) for k in ("model", "white_spec", "black_spec", "ctx_version",
                                                       "threat_agent", "search", "learned_kb_version")}
    return rec


class open_sf_version:
    """Context manager yielding the Stockfish id string (e.g. 'Stockfish 17')."""

    def __enter__(self) -> str:
        from claude_chess.match.baselines import open_stockfish
        self.eng = open_stockfish()
        return self.eng.id.get("name", "stockfish")

    def __exit__(self, *exc) -> None:
        self.eng.quit()


def mistake_evidence(m: dict, verdict: dict, les: dict) -> list[str]:
    return [f"Position: `{m['fen']}` — played **{m['played']}**, lost {m['cpl']} cp.",
            f"Engine best: {verdict['best_line']}", f"Refutation: {verdict['refutation_line']}",
            f"Diagnosis: {les.get('diagnosis', '')}", f"Why general: {les.get('why_general', '')}"]


# ── slow drift: outplayed by many small errors ─────────────────────────────

DRIFT_SYSTEM = """You are a strong chess player reviewing a stretch of your own game in which the \
position slipped away from you — either slowly, through many small inaccuracies, or from roughly \
equal to clearly lost before the decisive error. You will \
see the moves of that stretch with the engine's evaluation, your own evaluation at the time, what \
the engine preferred, and your stated reasons.

Work out HOW the position got there:
- the turning point (the move where your plan or judgement first went wrong),
- the underlying positional or endgame misunderstanding (plan, pawn structure, piece placement, \
trades, king activity, prophylaxis, conversion technique) — not a tactic,
- where your own evaluation diverged from the engine's and why you misjudged it.

Then write ONE general lesson that would have kept you on track in similar positions.
Rules: generalise from the pattern, not this game's squares; at most 3 summary bullets of at \
most 30 words; tags: 1-4 from ALLOWED TAGS, the FIRST must be one of the POSITION TAGS. If the \
drift is noise with no transferable idea, answer action "skip".
Reply with JSON only:
{"action": "new" | "skip", "narrative": "3-5 sentences: how the position slipped", \
"turning_point_ply": int, "misconception": "one sentence", "title": "...", "tags": ["..."], \
"summary": ["..."], "why_general": "one sentence"}"""


def find_drifts(run_dir: Path, learner: str, min_cp: int = 100, min_total: int = 150,
                min_moves: int = 4, window: int = 12, lost_cp: int = 800, max_n: int = 1,
                collapse_cp: int = 300, equal_cp: int = 60) -> list[dict]:
    """Two kinds of "how did it get there" stretches of the learner's moves:

    - collapse: the game turned decisively (learner eval <= -collapse_cp from some move on, for
      good) — the stretch from the last roughly-equal position (>= -equal_cp) up to that point,
      INCLUDING bigger mistakes. Ranked first.
    - drift: runs of moves each below `min_cp` whose losses sum to >= `min_total` (split at
      big mistakes, which `find_mistakes` handles, and cut once the position is lost).
      Runs right before a big mistake rank ahead of the rest."""
    moves = _game_moves(run_dir)
    dec = {(int(d["game"]), d["ply"]): d for d in _jsonl(run_dir / "decisions.jsonl")}
    rows = [a for a in _jsonl(run_dir / "move_analysis.jsonl")
            if (int(a["game"]), a["ply"]) in dec and learner in dec[(int(a["game"]), a["ply"])]["player"]]
    rows.sort(key=lambda a: (int(a["game"]), a["ply"]))
    segs: list[dict] = []

    def close(g: int, seg: list[dict], ended_by: dict | None, kind: str = "drift") -> None:
        if len(seg) < min_moves:
            return
        if kind == "collapse":
            w = seg[-window:]  # the moves leading into the collapse
        else:  # the `window` consecutive moves with the largest summed loss
            best = max(range(max(1, len(seg) - window + 1)),
                       key=lambda i: sum(x["cpl"] or 0 for x in seg[i:i + window]))
            w = seg[best:best + window]
        total = sum(x["cpl"] or 0 for x in w)
        if total < min_total or g not in moves:
            return
        items = []
        for a in w:
            d = dec[(g, a["ply"])]
            chosen = next((c for c in d.get("candidates") or [] if c.get("san") == d["san"]), {})
            items.append({"game": g, "ply": a["ply"], "fen": d["fen"], "history_uci": moves[g][: a["ply"] - 1],
                          "played": d["san"], "cpl": a["cpl"] or 0, "eval_before": a.get("eval_before"),
                          "eval_after": a.get("eval_after"), "sf_best": a.get("best_move"),
                          "own_eval": d.get("own_eval"), "reason": chosen.get("reason", ""),
                          "src": f"{run_dir.name}:{g}:{a['ply']}", "player": d["player"]})
        segs.append({"kind": kind, "game": g, "moves": items, "total_cpl": total, "history_all": moves[g],
                     "ended_by": ({"ply": ended_by["ply"], "san": ended_by["san"], "cpl": ended_by["cpl"]}
                                  if ended_by else None),
                     "src": f"{run_dir.name}:{g}:{items[0]['ply']}-{items[-1]['ply']}"})

    cur: list[dict] = []
    cur_game = None
    for a in rows:
        g = int(a["game"])
        if g != cur_game:
            if cur_game is not None:
                close(cur_game, cur, None)
            cur, cur_game = [], g
        eb = a.get("eval_before")
        if eb is not None and abs(eb) >= lost_cp:
            close(g, cur, None)
            cur = []
            continue
        if (a["cpl"] or 0) >= min_cp:
            close(g, cur, a)
            cur = []
        else:
            cur.append(a)
    if cur_game is not None:
        close(cur_game, cur, None)
    # collapse stretches: per game, the first move after which the learner stays <= -collapse_cp
    by_game: dict[int, list[dict]] = {}
    for a in rows:
        by_game.setdefault(int(a["game"]), []).append(a)
    for g, gm in by_game.items():
        ev = [a.get("eval_before") for a in gm]
        k = next((i for i in range(len(gm)) if all(e is not None and e <= -collapse_cp for e in ev[i:])), None)
        if k is None or k == 0:
            continue
        start = max((i for i in range(k) if ev[i] is not None and ev[i] >= -equal_cp), default=None)
        if start is not None:
            close(g, gm[start:k], gm[k], kind="collapse")
    segs.sort(key=lambda sg: (sg["kind"] != "collapse", sg["ended_by"] is None, -sg["total_cpl"]))
    return segs[:max_n]


def drift_prompt(seg: dict, eng: chess.engine.SimpleEngine, ctx_version: int, kb: Path,
                 n_targets: int = 3) -> tuple[str, list[str], list[dict]]:
    ms = seg["moves"]
    first = _board(ms[0]["history_uci"])
    last = _board(ms[-1]["history_uci"])
    last.push_san(ms[-1]["played"])
    start_ctx = build_context(first, include_legal_moves=False, version=ctx_version)
    end_ctx = build_context(last, include_legal_moves=False, version=ctx_version)
    targets = sorted(ms, key=lambda x: -x["cpl"])[:n_targets]
    tags: set[str] = set()
    for t in targets:
        tags |= set(build_context(_board(t["history_uci"]), include_legal_moves=False, version=ctx_version).tags)
    # the full sequence (both sides) across the stretch
    hist = seg["history_all"]
    line = first.variation_san([chess.Move.from_uci(u) for u in hist[ms[0]["ply"] - 1: ms[-1]["ply"]]])
    table = ["| move | you played | engine eval before (you) | your own eval | cp lost | engine preferred | your reason |",
             "|---|---|---|---|---|---|---|"]
    for x in ms:
        b = _board(x["history_uci"])
        mv = f"{b.fullmove_number}{'.' if b.turn == chess.WHITE else '...'}"
        table.append(f"| {mv} (ply {x['ply']}) | {x['played']} | {x['eval_before']} | {x['own_eval']} | {x['cpl']} "
                     f"| {x['sf_best']} | {(x['reason'] or '')[:80]} |")
    lines = []
    for t in targets:
        v = engine_verdict(eng, _board(t["history_uci"]), t["played"])
        lines.append(f"- ply {t['ply']} {t['played']} (-{t['cpl']}): engine best {v['best_line']}; "
                     f"after yours: {v['refutation_line']}")
    ended = seg["ended_by"]
    existing = [f"- {les.title} [tags: {', '.join(les.tags)}]" for les in learned.load(kb)]
    what = ("The game went from roughly equal to clearly lost over this stretch (bigger mistakes included). "
            "Explain how it got there — the plan and judgement behind these moves, not just the worst one."
            if seg.get("kind") == "collapse" else
            "No single move here lost much, but together they turned the position: you were slowly outplayed.")
    prompt = f"""{what}

## Start of the stretch
{render_context(start_ctx, include_legal_moves=False)}

## Moves in the stretch (both sides)
{line}

## Your moves, engine vs you (evals in centipawns from YOUR side; total lost {seg['total_cpl']} cp)
{chr(10).join(table)}

## Engine lines at your costliest moves in the stretch
{chr(10).join(lines)}

## End of the stretch
{render_context(end_ctx, include_legal_moves=False)}
{f"Right after this stretch you played {ended['san']} and lost {ended['cpl']} cp in one move." if ended else ""}

## POSITION TAGS (first lesson tag must be one of these)
{', '.join(sorted(tags))}

## ALLOWED TAGS
{', '.join(sorted(set(TAG_WEIGHTS) | tags))}

## Existing lessons (don't duplicate)
{chr(10).join(existing) or '(none yet)'}
"""
    return prompt, sorted(tags), targets


def drift_evidence(seg: dict, les: dict) -> list[str]:
    ms = seg["moves"]
    ev = [f"{'Collapse' if seg.get('kind') == 'collapse' else 'Slow drift'}: plies {ms[0]['ply']}–{ms[-1]['ply']}, {len(ms)} moves, {seg['total_cpl']} cp lost in total "
          f"(max {max(x['cpl'] for x in ms)} in one move).",
          "Moves: " + ", ".join(f"{x['played']}(-{x['cpl']})" for x in ms)]
    if seg["ended_by"]:
        ev.append(f"Followed by {seg['ended_by']['san']} (-{seg['ended_by']['cpl']}) at ply {seg['ended_by']['ply']}.")
    ev += [f"How it got there: {les.get('narrative', '')}",
           f"Turning point: ply {les.get('turning_point_ply')}", f"Misconception: {les.get('misconception', '')}",
           f"Why general: {les.get('why_general', '')}"]
    return ev


# ── caches (persistent, knowledge_learned/cache/cache.sqlite) ──────────────
#
# 1. Stockfish scores per (FEN, move, depth): identical moves always get identical scores
#    (SF is not deterministic across calls) and nothing is analysed twice.
# 2. Replayed decisions per (player config, KB contents, position+history, sample #):
#    the baseline arm of the gate is the same for every lesson gated against the same KB,
#    and a --regate reuses both arms. The KB key is a hash of the lesson texts, so any
#    change to the KB (new/retired lesson) is a different key.


class Cache:
    def __init__(self, kb: Path):
        import sqlite3
        d = kb / "cache"
        d.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(d / "cache.sqlite", timeout=30, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        import threading
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: str):
        with self._lock:
            row = self._db.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(row[0])

    def put(self, key: str, value) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json.dumps(value)))
            self._db.commit()

    def close(self) -> None:
        self._db.close()


def kb_fingerprint(kb: Path | None) -> str:
    """Hash of the active lessons' texts (what the player would actually see)."""
    import hashlib
    if kb is None:
        return "none"
    h = hashlib.sha256()
    for les in learned.load(kb):
        h.update(les.id.encode())
        h.update((kb / "lessons" / f"{les.id}.md").read_bytes())
    return h.hexdigest()[:16]


def _pos_key(it: dict) -> str:
    import hashlib
    return hashlib.sha256(" ".join(it["history_uci"]).encode()).hexdigest()[:16]


# ── gate ────────────────────────────────────────────────────────────────────


def _cp_loss(eng: chess.engine.SimpleEngine, board: chess.Board, san: str | None, sf_eval: int) -> int:
    if san is None:
        return CAP
    b = board.copy()
    b.push_san(san)
    if b.is_checkmate():
        return 0
    after = -eng.analyse(b, chess.engine.Limit(depth=14))["score"].relative.score(mate_score=10000)
    return max(0, min(CAP, sf_eval - after))


def control_pool(run_dir: Path, learner: str, exclude_game: str) -> list[dict]:
    """Positions to check the lesson doesn't hurt: past suites + the learner's other moves."""
    pool: list[dict] = []
    for sp in sorted(Path("suites").glob("*.jsonl")):
        pool += [it for it in _jsonl(sp) if "history_uci" in it]
    moves = _game_moves(run_dir)
    for d in _jsonl(run_dir / "decisions.jsonl"):
        g = int(d["game"])
        if learner in d["player"] and g in moves:
            pool.append({"fen": d["fen"], "history_uci": moves[g][: d["ply"] - 1],
                         "src": f"{run_dir.name}:{g}:{d['ply']}"})
    return [it for it in pool if not it["src"].startswith(exclude_game)]


def select_controls(pool: list[dict], cand_kb: Path, lesson_id: str, ctx_version: int, n: int) -> list[dict]:
    """Only positions where the candidate KB would actually show the new lesson: everywhere
    else the context is byte-identical, so replaying them measures nothing. (Also used to
    filter a lesson's own targets.)"""
    learned.set_active(cand_kb)
    try:
        hits = []
        for it in pool:
            try:
                b = _board(it["history_uci"])
            except (ValueError, AssertionError):
                continue
            if b.is_game_over():
                continue
            ctx = build_context(b, include_legal_moves=False, version=ctx_version)
            if ctx.lessons and lesson_id in {les.id for les in learned.retrieve(set(ctx.tags), k=1)}:
                hits.append(it)
            if len(hits) >= n:
                break
        return hits
    finally:
        learned.set_active(None)


def replay(items: list[dict], factory: Callable[[], Any], kb: Path | None, repeats: int, workers: int = 4,
           cache: "Cache | None" = None) -> list[list[str | None]]:
    """Play each item `repeats` times with the learned KB set to `kb`. Returns SANs.
    Cached per (player config, KB contents, position+history, sample #)."""
    learned.set_active(kb)
    try:
        probe = factory()
        pname = getattr(probe, "name", type(probe).__name__)
        if hasattr(probe, "close"):
            probe.close()
        fp = kb_fingerprint(kb)
        out: list[list[str | None]] = [[None] * repeats for _ in items]
        jobs = []
        for i, it in enumerate(items):
            for r in range(repeats):
                key = f"move|{pname}|{fp}|{_pos_key(it)}|{r}"
                hit = cache.get(key) if cache else None
                if hit is not None:
                    out[i][r] = hit["san"]
                else:
                    jobs.append((i, r, key))

        def one(job: tuple[int, int, str]) -> tuple[int, int, str, str | None]:
            i, r, key = job
            p = factory()
            try:
                return i, r, key, p.choose_move(_board(items[i]["history_uci"])).san
            finally:
                if hasattr(p, "close"):
                    p.close()

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, r, key, san in ex.map(one, jobs):
                out[i][r] = san
                if cache and san is not None:
                    cache.put(key, {"san": san})
        return out
    finally:
        learned.set_active(None)


def gate(targets: list[dict], controls: list[dict], factory: Callable[[], Any], base_kb: Path, cand_kb: Path,
         eng: chess.engine.SimpleEngine, repeats: int = 3, min_gain: float = 50, max_harm: float = 25,
         cache: "Cache | None" = None) -> dict:
    """Replay targets (×repeats) and controls (×1) with baseline KB vs KB+lesson.
    gain = mean cp-loss improvement over targets; harm = mean worsening over controls."""
    items = targets + controls
    for it in items:
        if "sf_eval" not in it:
            key = f"sfeval|14|{it['fen']}"
            hit = cache.get(key) if cache else None
            if hit is None:
                hit = eng.analyse(_board(it["history_uci"]), chess.engine.Limit(depth=14))["score"] \
                    .relative.score(mate_score=10000)
                if cache:
                    cache.put(key, hit)
            it["sf_eval"] = hit

    # Score each (position, move) once: Stockfish is not deterministic across calls (hash state),
    # and the same move must get the same score in both arms or the noise reads as harm/gain.
    def loss(it: dict, san: str | None) -> int:
        key = f"cpl|14|{it['fen']}|{san}"
        hit = cache.get(key) if cache else None
        if hit is None:
            hit = _cp_loss(eng, _board(it["history_uci"]), san, it["sf_eval"])
            if cache:
                cache.put(key, hit)
        return hit

    def losses(kb: Path) -> list[float]:
        t = replay(targets, factory, kb, repeats, cache=cache)
        c = replay(controls, factory, kb, 1, cache=cache) if controls else []
        return [sum(loss(it, x) for x in ss) / len(ss) for it, ss in zip(items, t + c)]

    base, cand = losses(base_kb), losses(cand_kb)
    nt = len(targets)
    tb, tc = sum(base[:nt]) / nt, sum(cand[:nt]) / nt
    gain = tb - tc
    harm = (sum(c - b for b, c in zip(base[nt:], cand[nt:])) / len(controls)) if controls else 0.0
    accepted = gain >= min_gain and harm <= max_harm
    reason = ("accepted" if accepted else
              f"target gain {gain:.0f} < {min_gain}" if gain < min_gain else f"control harm {harm:.0f} > {max_harm}")
    return {"accepted": accepted, "reason": reason, "targets": nt,
            "per_target": [{"src": it["src"], "base_cpl": round(b), "cand_cpl": round(c)}
                           for it, b, c in zip(targets, base[:nt], cand[:nt])],
            "target_base_cpl": round(tb),
            "target_cand_cpl": round(tc), "target_repeats": repeats, "controls": len(controls),
            "control_mean_delta": round(harm, 1)}


# ── orchestration ───────────────────────────────────────────────────────────


def _commit(kb: Path, action: str, lesson_id: str, extra: dict) -> int:
    man = learned.read_manifest(kb)
    man["version"] += 1
    man["history"].append({"version": man["version"], "action": action, "lesson": lesson_id,
                           "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra})
    learned.write_manifest(kb, man)
    return man["version"]


DEFAULT_CONFIG: dict[str, Any] = {
    "learner_models": ["claude-opus-5-5", "opus"], "auto_learn": True,
    # single-move mistakes
    "min_cp": 100, "max_lessons_per_run": 2, "gate": True, "gate_repeats": 3,
    "gate_controls": 4, "gate_min_gain": 50, "gate_max_harm": 25,
    # slow drift (outplayed by many small errors)
    "drift": True, "drift_min_total": 150, "drift_min_moves": 4, "drift_window": 12,
    "collapse_cp": 300, "equal_cp": 60,
    "max_drifts_per_run": 1, "drift_targets": 3, "drift_repeats": 2, "drift_min_gain": 20,
}


def ensure_kb(kb: Path) -> None:
    (kb / "lessons").mkdir(parents=True, exist_ok=True)
    (kb / "rejected").mkdir(parents=True, exist_ok=True)
    if not (kb / "manifest.json").exists():
        learned.write_manifest(kb, {"version": 0, "history": []})
    if not (kb / "config.json").exists():
        (kb / "config.json").write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")


def load_config(kb: Path = learned.DEFAULT_DIR) -> dict:
    """File overrides on top of DEFAULT_CONFIG, so new keys work with an older config.json."""
    ensure_kb(kb)
    return {**DEFAULT_CONFIG, **json.loads((kb / "config.json").read_text())}


def _submit(kind: str, les: dict, source: str, learner: str, evidence: list[str], targets: list[dict],
            ctx: dict, repeats: int, min_gain: float) -> dict:
    """Gate a proposed lesson and record it as accepted or rejected."""
    kb, cfg, run_dir = ctx["kb"], ctx["cfg"], ctx["run_dir"]
    # ids number every proposal (accepted or not) so they never collide; the KB version counts accepts
    seq = len(_jsonl(kb / "proposals.jsonl")) + 1
    lesson_id = f"L{seq:03d}-{_slug(les['title'])}"
    res: dict[str, Any] = {"kind": kind, "src": source, "lesson_id": lesson_id, "lesson": les,
                           "targets": [t["src"] for t in targets]}
    src_rec = source_record(run_dir, targets[0]["game"], kb)
    with (kb / "proposals.jsonl").open("a") as f:  # everything needed to re-gate / re-judge later
        f.write(json.dumps({"lesson_id": lesson_id, "kind": kind, "lesson": les, "source": source,
                            "learner": learner, "evidence": evidence, "run_dir": str(run_dir),
                            "source_game": src_rec,
                            "targets": [{k: t[k] for k in ("fen", "history_uci", "src", "game")} for t in targets]})
                + "\n")
    gate_res = None
    if cfg["gate"] and not ctx["dry_run"]:
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "kb"
            shutil.copytree(kb, cand)
            (cand / "lessons" / f"{lesson_id}.md").write_text(
                lesson_markdown(lesson_id, les, source, learner, evidence, None, kind=kind))
            learned.write_manifest(cand, {**learned.read_manifest(cand), "version": -1})  # new mtime key
            # Measure only where the lesson is actually shown: elsewhere the context is identical.
            shown = select_controls(targets, cand, lesson_id, ctx["ctx_version"], len(targets))
            if not shown:
                gate_res = {"accepted": False, "reason": "lesson not shown at any of its own targets",
                            "targets": 0, "targets_proposed": len(targets)}
            else:
                games = {f"{run_dir.name}:{t['game']}:" for t in targets}
                pool = [it for it in control_pool(run_dir, ctx["learner"], "\0")
                        if not any(it["src"].startswith(g) for g in games)]
                controls = select_controls(pool, cand, lesson_id, ctx["ctx_version"], cfg["gate_controls"])
                ctx["log"](f"[learn] gating {lesson_id} ({kind}): {len(shown)}/{len(targets)} target(s) "
                           f"×{repeats} + {len(controls)} controls")
                gate_res = gate(shown, controls, ctx["factory"], kb, cand, ctx["eng"], repeats,
                                min_gain, cfg["gate_max_harm"], cache=ctx.get("cache"))
                gate_res["targets_proposed"] = len(targets)
    res["gate"] = gate_res
    if (gate_res is None or gate_res["accepted"]) and not ctx["dry_run"]:
        (kb / "lessons" / f"{lesson_id}.md").write_text(
            lesson_markdown(lesson_id, les, source, learner, evidence, gate_res, kind=kind, src_rec=src_rec))
        res["kb_version"] = _commit(kb, "add", lesson_id, {"kind": kind, "source": source, "gate": gate_res})
        res["outcome"] = "accepted"
    else:
        (kb / "rejected" / f"{lesson_id}.md").write_text(
            lesson_markdown(lesson_id, les, source, learner, evidence, gate_res, status="rejected", kind=kind,
                            src_rec=src_rec))
        res["outcome"] = "dry-run" if ctx["dry_run"] else f"rejected ({gate_res['reason']})"
    ctx["log"](f"[learn] {lesson_id}: {res['outcome']}  — {les['title']}")
    return res


def learn_from_run(run_dir: str | Path, learner: str, factory: Callable[[], Any], llm: Any,
                   ctx_version: int = 3, kb: Path = learned.DEFAULT_DIR, cfg: dict | None = None,
                   dry_run: bool = False, log: Callable[[str], None] = print) -> dict:
    from claude_chess.llm import extract_json
    from claude_chess.match.baselines import open_stockfish

    run_dir = Path(run_dir)
    ensure_kb(kb)
    cfg = {**load_config(kb), **(cfg or {})}
    mistakes = find_mistakes(run_dir, learner, cfg["min_cp"], cfg["max_lessons_per_run"])
    drifts = (find_drifts(run_dir, learner, cfg["min_cp"], cfg["drift_min_total"], cfg["drift_min_moves"],
                          cfg["drift_window"], max_n=cfg["max_drifts_per_run"], collapse_cp=cfg["collapse_cp"],
                          equal_cp=cfg["equal_cp"]) if cfg["drift"] else [])
    report: dict[str, Any] = {"run": run_dir.name, "learner": learner, "kb_version_before": learned.version(kb),
                              "mistakes": len(mistakes), "drifts": len(drifts), "results": []}
    log(f"[learn] {learner} in {run_dir.name}: {len(mistakes)} mistake(s) ≥{cfg['min_cp']}cp, "
        f"{len(drifts)} slow-drift stretch(es) ≥{cfg['drift_min_total']}cp")
    eng = open_stockfish()
    cache = Cache(kb)
    ctx = {"kb": kb, "cfg": cfg, "run_dir": run_dir, "learner": learner, "factory": factory,
           "ctx_version": ctx_version, "eng": eng, "dry_run": dry_run, "log": log, "cache": cache}

    def ask(system: str, prompt: str, src: str) -> dict | None:
        try:
            return extract_json(llm.complete(system, prompt).text)
        except Exception as e:  # noqa: BLE001 — a bad reply skips this item only
            report["results"].append({"src": src, "outcome": f"lesson call failed: {e}"})
            return None

    try:
        for m in mistakes:
            board = _board(m["history_uci"])
            verdict = engine_verdict(eng, board, m["played"])
            prompt, pos_tags = lesson_prompt(m, board, verdict, _trace_text(run_dir, m["game"], m["ply"]),
                                              ctx_version, kb)
            data = ask(LESSON_SYSTEM, prompt, m["src"])
            les = validate(data, pos_tags) if data is not None else None
            if les is None:
                if data is not None:
                    report["results"].append({"kind": "mistake", "src": m["src"], "outcome": "no lesson", "raw": data})
                log(f"[learn] {m['src']} {m['played']} (-{m['cpl']}): no lesson")
                continue
            res = _submit("mistake", les, m["src"], m["player"], mistake_evidence(m, verdict, les), [m],
                          ctx, cfg["gate_repeats"], cfg["gate_min_gain"])
            res.update({"played": m["played"], "cpl": m["cpl"]})
            report["results"].append(res)
        for sg in drifts:
            prompt, pos_tags, targets = drift_prompt(sg, eng, ctx_version, kb, cfg["drift_targets"])
            data = ask(DRIFT_SYSTEM, prompt, sg["src"])
            les = validate(data, pos_tags) if data is not None else None
            if les is None:
                if data is not None:
                    report["results"].append({"kind": sg.get("kind", "drift"), "src": sg["src"],
                                              "outcome": "no lesson", "raw": data})
                log(f"[learn] drift {sg['src']} (-{sg['total_cpl']} total): no lesson")
                continue
            res = _submit(sg.get("kind", "drift"), les, sg["src"], sg["moves"][0]["player"], drift_evidence(sg, les), targets,
                          ctx, cfg["drift_repeats"], cfg["drift_min_gain"])
            res.update({"total_cpl": sg["total_cpl"], "narrative": les.get("narrative")})
            report["results"].append(res)
    finally:
        eng.quit()
        report["cache"] = {"hits": cache.hits, "misses": cache.misses}
        cache.close()
    report["kb_version_after"] = learned.version(kb)
    (run_dir / "learn_report.json").write_text(json.dumps(report, indent=2, default=str))
    with (kb / "CHANGELOG.md").open("a") as f:
        for r in report["results"]:
            if "lesson_id" in r:
                what = (f"{r['played']} -{r['cpl']}cp" if r["kind"] == "mistake" else f"{r['kind']} -{r['total_cpl']}cp")
                f.write(f"- {time.strftime('%Y-%m-%d')} {r['lesson_id']} [{r['kind']}] {r['outcome']} "
                        f"(from {r['src']}, {what}): {r['lesson']['title']}\n")
    return report


def regate(lesson_id: str, factory: Callable[[], Any], ctx_version: int = 3, kb: Path = learned.DEFAULT_DIR,
           cfg: dict | None = None, log: Callable[[str], None] = print) -> dict:
    """Re-run the gate for a stored proposal (e.g. a rejected lesson, after a gate fix or with more
    repeats) without paying to regenerate it. An accepted re-gate gets a new id; the old file stays."""
    from claude_chess.match.baselines import open_stockfish
    props = {p["lesson_id"]: p for p in _jsonl(kb / "proposals.jsonl")}
    if lesson_id not in props:
        raise KeyError(f"no stored proposal {lesson_id} in {kb / 'proposals.jsonl'}")
    p = props[lesson_id]
    cfg = {**load_config(kb), **(cfg or {})}
    eng = open_stockfish()
    try:
        ctx = {"kb": kb, "cfg": cfg, "run_dir": Path(p["run_dir"]), "learner": p["learner"], "factory": factory, "ctx_version": ctx_version, "eng": eng,
               "dry_run": False, "log": log, "cache": Cache(kb)}
        mistake = p["kind"] == "mistake"
        res = _submit(p["kind"], p["lesson"], p["source"], p["learner"],
                      p["evidence"] + [f"Re-gate of {lesson_id}"], p["targets"], ctx,
                      cfg["gate_repeats"] if mistake else cfg["drift_repeats"],
                      cfg["gate_min_gain"] if mistake else cfg["drift_min_gain"])
    finally:
        eng.quit()
        ctx["cache"].close()
    with (kb / "CHANGELOG.md").open("a") as f:
        f.write(f"- {time.strftime('%Y-%m-%d')} {res['lesson_id']} [{p['kind']}] {res['outcome']} "
                f"(re-gate of {lesson_id}): {p['lesson']['title']}\n")
    return res
