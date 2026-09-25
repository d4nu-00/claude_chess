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
    return {"title": str(data["title"]).strip()[:90], "tags": tags, "summary": summary,
            "diagnosis": str(data.get("diagnosis", "")), "why_general": str(data.get("why_general", ""))}


def lesson_markdown(lesson_id: str, les: dict, m: dict, verdict: dict, gate: dict | None,
                    status: str = "active") -> str:
    g = json.dumps(gate) if gate else "n/a"
    return f"""---
title: {les['title']}
tags: [{', '.join(les['tags'])}]
status: {status}
id: {lesson_id}
source: {m['src']}
learner: {m['player']}
created: {time.strftime('%Y-%m-%d %H:%M')}
---
## Summary
{chr(10).join('- ' + s for s in les['summary'])}

## Evidence
- Position: `{m['fen']}` — played **{m['played']}**, lost {m['cpl']} cp.
- Engine best: {verdict['best_line']}
- Refutation: {verdict['refutation_line']}
- Diagnosis: {les['diagnosis']}
- Why general: {les['why_general']}
- Gate: {g}
"""


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
    else the context is byte-identical, so replaying them measures nothing."""
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


def replay(items: list[dict], factory: Callable[[], Any], kb: Path | None, repeats: int, workers: int = 4
           ) -> list[list[str | None]]:
    """Play each item `repeats` times with the learned KB set to `kb`. Returns SANs."""
    learned.set_active(kb)
    try:
        def one(job: tuple[int, int]) -> tuple[int, str | None]:
            i, _ = job
            p = factory()
            try:
                return i, p.choose_move(_board(items[i]["history_uci"])).san
            finally:
                if hasattr(p, "close"):
                    p.close()
        jobs = [(i, r) for i in range(len(items)) for r in range(repeats)]
        out: list[list[str | None]] = [[] for _ in items]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, san in ex.map(one, jobs):
                out[i].append(san)
        return out
    finally:
        learned.set_active(None)


def gate(target: dict, controls: list[dict], factory: Callable[[], Any], base_kb: Path, cand_kb: Path,
         eng: chess.engine.SimpleEngine, repeats: int = 3, min_gain: int = 50, max_harm: int = 25) -> dict:
    items = [target] + controls
    for it in items:
        if "sf_eval" not in it:
            it["sf_eval"] = eng.analyse(_board(it["history_uci"]), chess.engine.Limit(depth=14))["score"] \
                .relative.score(mate_score=10000)
    reps = [repeats] + [1] * len(controls)

    # Score each (position, move) once: Stockfish is not deterministic across calls (hash state),
    # and the same move must get the same score in both arms or the noise reads as harm/gain.
    memo: dict[tuple[str, str | None], int] = {}

    def loss(it: dict, san: str | None) -> int:
        key = (it["fen"], san)
        if key not in memo:
            memo[key] = _cp_loss(eng, _board(it["history_uci"]), san, it["sf_eval"])
        return memo[key]

    def losses(sans: list[list[str | None]]) -> list[float]:
        return [sum(loss(it, s) for s in ss) / len(ss) for it, ss in zip(items, sans)]

    base = losses(_expand(replay(_flatten(items, reps), factory, base_kb, 1), reps))
    cand = losses(_expand(replay(_flatten(items, reps), factory, cand_kb, 1), reps))
    gain = base[0] - cand[0]
    harm = (sum(c - b for b, c in zip(base[1:], cand[1:])) / len(controls)) if controls else 0.0
    accepted = gain >= min_gain and harm <= max_harm
    reason = ("accepted" if accepted else
              f"target gain {gain:.0f} < {min_gain}" if gain < min_gain else f"control harm {harm:.0f} > {max_harm}")
    return {"accepted": accepted, "reason": reason, "target_base_cpl": round(base[0]),
            "target_cand_cpl": round(cand[0]), "target_repeats": repeats, "controls": len(controls),
            "control_mean_delta": round(harm, 1)}


def _flatten(items: list[dict], reps: list[int]) -> list[dict]:
    return [it for it, r in zip(items, reps) for _ in range(r)]


def _expand(sans: list[list[str | None]], reps: list[int]) -> list[list[str | None]]:
    flat = [s[0] for s in sans]
    out, i = [], 0
    for r in reps:
        out.append(flat[i:i + r])
        i += r
    return out


# ── orchestration ───────────────────────────────────────────────────────────


def _commit(kb: Path, action: str, lesson_id: str, extra: dict) -> int:
    man = learned.read_manifest(kb)
    man["version"] += 1
    man["history"].append({"version": man["version"], "action": action, "lesson": lesson_id,
                           "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra})
    learned.write_manifest(kb, man)
    return man["version"]


def ensure_kb(kb: Path) -> None:
    (kb / "lessons").mkdir(parents=True, exist_ok=True)
    (kb / "rejected").mkdir(parents=True, exist_ok=True)
    if not (kb / "manifest.json").exists():
        learned.write_manifest(kb, {"version": 0, "history": []})
    if not (kb / "config.json").exists():
        (kb / "config.json").write_text(json.dumps(
            {"learner_models": ["claude-opus-5-5", "opus"], "auto_learn": True,
             "min_cp": 100, "max_lessons_per_run": 2, "gate": True, "gate_repeats": 3,
             "gate_controls": 4, "gate_min_gain": 50, "gate_max_harm": 25}, indent=2) + "\n")


def load_config(kb: Path = learned.DEFAULT_DIR) -> dict:
    ensure_kb(kb)
    return json.loads((kb / "config.json").read_text())


def learn_from_run(run_dir: str | Path, learner: str, factory: Callable[[], Any], llm: Any,
                   ctx_version: int = 3, kb: Path = learned.DEFAULT_DIR, cfg: dict | None = None,
                   dry_run: bool = False, log: Callable[[str], None] = print) -> dict:
    from claude_chess.llm import extract_json
    from claude_chess.match.baselines import open_stockfish

    run_dir = Path(run_dir)
    ensure_kb(kb)
    cfg = {**load_config(kb), **(cfg or {})}
    mistakes = find_mistakes(run_dir, learner, cfg["min_cp"], cfg["max_lessons_per_run"])
    report: dict[str, Any] = {"run": run_dir.name, "learner": learner, "kb_version_before": learned.version(kb),
                              "mistakes": len(mistakes), "results": []}
    log(f"[learn] {len(mistakes)} mistake(s) ≥{cfg['min_cp']}cp by {learner} in {run_dir.name}")
    eng = open_stockfish()
    try:
        for m in mistakes:
            board = _board(m["history_uci"])
            verdict = engine_verdict(eng, board, m["played"])
            prompt, pos_tags = lesson_prompt(m, board, verdict, _trace_text(run_dir, m["game"], m["ply"]),
                                              ctx_version, kb)
            try:
                data = extract_json(llm.complete(LESSON_SYSTEM, prompt).text)
            except Exception as e:  # noqa: BLE001 — a bad reply skips this mistake only
                report["results"].append({"src": m["src"], "outcome": f"lesson call failed: {e}"})
                continue
            les = validate(data, pos_tags)
            if les is None:
                report["results"].append({"src": m["src"], "outcome": "skipped by model or invalid",
                                          "raw": data})
                log(f"[learn] {m['src']} ply {m['ply']} {m['played']} (-{m['cpl']}): no lesson")
                continue
            lesson_id = f"L{learned.version(kb) + 1:03d}-{_slug(les['title'])}"
            res: dict[str, Any] = {"src": m["src"], "played": m["played"], "cpl": m["cpl"],
                                   "lesson_id": lesson_id, "lesson": les}
            gate_res = None
            if cfg["gate"] and not dry_run:
                with tempfile.TemporaryDirectory() as tmp:
                    cand = Path(tmp) / "kb"
                    shutil.copytree(kb, cand)
                    (cand / "lessons" / f"{lesson_id}.md").write_text(lesson_markdown(lesson_id, les, m, verdict, None))
                    learned.write_manifest(cand, {**learned.read_manifest(cand), "version": -1})  # new mtime key
                    controls = select_controls(control_pool(run_dir, learner, f"{run_dir.name}:{m['game']}:"),
                                               cand, lesson_id, ctx_version, cfg["gate_controls"])
                    log(f"[learn] gating {lesson_id}: target×{cfg['gate_repeats']} + {len(controls)} controls")
                    gate_res = gate(m, controls, factory, kb, cand, eng, cfg["gate_repeats"],
                                    cfg["gate_min_gain"], cfg["gate_max_harm"])
            res["gate"] = gate_res
            accepted = (gate_res is None or gate_res["accepted"]) and not dry_run
            if accepted:
                (kb / "lessons" / f"{lesson_id}.md").write_text(lesson_markdown(lesson_id, les, m, verdict, gate_res))
                res["kb_version"] = _commit(kb, "add", lesson_id, {"source": m["src"], "gate": gate_res})
                res["outcome"] = "accepted"
            else:
                (kb / "rejected" / f"{lesson_id}.md").write_text(
                    lesson_markdown(lesson_id, les, m, verdict, gate_res, status="rejected"))
                res["outcome"] = "dry-run" if dry_run else f"rejected ({gate_res['reason']})"
            log(f"[learn] {lesson_id}: {res['outcome']}  — {les['title']}")
            report["results"].append(res)
    finally:
        eng.quit()
    report["kb_version_after"] = learned.version(kb)
    (run_dir / "learn_report.json").write_text(json.dumps(report, indent=2, default=str))
    with (kb / "CHANGELOG.md").open("a") as f:
        for r in report["results"]:
            if "lesson_id" in r:
                f.write(f"- {time.strftime('%Y-%m-%d')} {r['lesson_id']} {r['outcome']} "
                        f"(from {r['src']}, {r['played']} -{r['cpl']}cp): {r['lesson']['title']}\n")
    return report
