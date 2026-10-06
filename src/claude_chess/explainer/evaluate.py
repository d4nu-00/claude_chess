"""Evaluate explanations: verifier pass rate, concept agreement, condensation, blind judge, transfer.

Transfer test (the closest automatic proxy for "a human understands it"): a weaker reader
(Haiku) sees the board and the two candidate moves in random order and must pick the better
one — with no help, with the teacher's idea, or with the student's idea. Move names are
masked in the idea ("[move]"), so it must carry understanding, not the answer.
"""

from __future__ import annotations

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import chess

from claude_chess.explainer import facts as F
from claude_chess.explainer import teacher as T
from claude_chess.llm import extract_json

_SAN_ANY = re.compile(r"\b(?:\d+\.(?:\.\.)?)?(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?|"
                      r"[a-h][1-8](?:=[QRBN])?|O-O(?:-O)?)[+#]?(?![a-z])")


def mask_moves(text: str, sans: list[str]) -> str:
    """Hide the candidate moves (and any move in SAN) so an idea can't leak the answer."""
    out = text
    for s in sorted(set(sans), key=len, reverse=True):
        out = out.replace(s, "[move]").replace(s.rstrip("+#"), "[move]")
    return _SAN_ANY.sub(lambda m: "[move]" if any(c.isupper() for c in m.group(0)[:1]) or "x" in m.group(0)
                        else m.group(0), out)


def concept_f1(pred: list[str], gold: list[str]) -> float:
    p, g = set(pred or []), set(gold or [])
    if not p or not g:
        return 0.0
    tp = len(p & g)
    return 0.0 if tp == 0 else 2 * tp / (len(p) + len(g))


def words(s: str) -> int:
    return len(str(s or "").split())


# ── generation ───────────────────────────────────────────────────────────────


def generate(student, recs: list[dict], log=print) -> list[dict]:
    from claude_chess.explainer.lm import _scale, student_facts

    scale = _scale()
    out = []
    for n, r in enumerate(recs):
        raw, parsed = student.explain(student_facts(r, scale), r["best_san"][0], r["alt_san"][0])
        out.append({"fen": r["fen"], "raw": raw, "parsed": parsed})
        if (n + 1) % 10 == 0:
            log(f"[eval] generated {n + 1}/{len(recs)}")
    return out


def auto_metrics(recs: list[dict], gens: list[dict], scale: dict | None = None) -> dict:
    n = len(recs)
    fmt = ver = 0
    f1 = idea_w = 0.0
    flags: dict[str, int] = {}
    for r, g in zip(recs, gens):
        p = g["parsed"]
        has_all = all(k in p for k in ("idea", "assessment", "why_best", "why_not_alt", "concepts", "plan", "difficulty"))
        fmt += has_all
        pf = F.compute(r["fen"], r["best_line"].split(), r["alt_line"].split(), r["value"], r["value_alt"], scale)
        v = T.verify(p, pf)
        ver += v["ok"]
        for fl in v["flags"]:
            key = fl.split(":")[0]
            flags[key] = flags.get(key, 0) + 1
        f1 += concept_f1(p.get("concepts", []), r["label"].get("concepts", []))
        idea_w += words(p.get("idea", ""))
    return {"n": n, "format_ok": fmt / n, "verifier_ok": ver / n, "concept_f1_vs_teacher": f1 / n,
            "idea_words": idea_w / n, "teacher_idea_words": sum(words(r["label"].get("idea")) for r in recs) / n,
            "flags": flags}


# ── blind pairwise judge ─────────────────────────────────────────────────────

JUDGE_SYSTEM = """You are a chess master grading explanations written for club players. You get the position,
the engine analysis (ground truth) and two explanations, A and B. Judge: (1) correctness against the
engine analysis and the board, (2) whether the main idea is the right one, (3) how usable it is —
short, general, memorable. Reply with one JSON object only."""


def _render_expl(p: dict) -> str:
    return "\n".join(f"{k}: {p.get(k, '')}" for k in ("idea", "assessment", "why_best", "why_not_alt", "plan"))


def judge(llm, rec: dict, a: dict, b: dict) -> dict:
    prompt = (f"{rec['facts']}\n\nExplanation A:\n{_render_expl(a)}\n\nExplanation B:\n{_render_expl(b)}\n\n"
              'Return JSON: {"winner": "A" | "B" | "tie", "a_correct": true/false, "b_correct": true/false, '
              '"reason": "<=25 words"}')
    resp = llm.complete(JUDGE_SYSTEM, prompt, max_tokens=300)
    try:
        out = extract_json(resp.text)
    except ValueError:
        out = {"winner": "?"}
    out["cost_usd"] = resp.cost_usd
    return out


def pairwise(llm, recs: list[dict], first: list[dict], second: list[dict], seed: int = 0,
             workers: int = 6) -> dict:
    """first vs second (dicts of parsed fields), order randomized per item. Returns win rates
    of `first` and per-side correctness."""
    rng = random.Random(seed)
    jobs = []
    for r, x, y in zip(recs, first, second):
        swap = rng.random() < 0.5
        jobs.append((r, (y, x) if swap else (x, y), swap))
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda j: judge(llm, j[0], *j[1]), jobs))
    win = tie = lose = c1 = c2 = 0
    cost = 0.0
    for (r, _, swap), o in zip(jobs, res):
        w = o.get("winner")
        cost += o.get("cost_usd", 0.0)
        a_ok, b_ok = bool(o.get("a_correct")), bool(o.get("b_correct"))
        f_ok, s_ok = (b_ok, a_ok) if swap else (a_ok, b_ok)
        c1 += f_ok
        c2 += s_ok
        if w == "tie":
            tie += 1
        elif (w == "A" and not swap) or (w == "B" and swap):
            win += 1
        elif w in ("A", "B"):
            lose += 1
    n = len(jobs)
    return {"n": n, "first_wins": win / n, "ties": tie / n, "second_wins": lose / n,
            "first_correct": c1 / n, "second_correct": c2 / n, "cost_usd": round(cost, 3)}


# ── transfer test ────────────────────────────────────────────────────────────

READER_SYSTEM = """You are a club-level chess player (about 1500). Pick the better of two candidate moves.
Reply with one JSON object only."""


def reader_pick(llm, rec: dict, hint: str | None, seed: int) -> bool:
    b = chess.Board(rec["fen"])
    cands = [rec["best_san"][0], rec["alt_san"][0]]
    random.Random(seed).shuffle(cands)
    hint_txt = f"\nA coach's hint (moves hidden): {hint}\n" if hint else "\n"
    prompt = (f"FEN: {rec['fen']} ({'White' if b.turn else 'Black'} to move)\n{F.ascii_board(b)}\n{hint_txt}\n"
              f"Candidates: {cands[0]} or {cands[1]}.\nReturn JSON: {{\"move\": \"<one of the two, SAN>\"}}")
    try:
        mv = str(extract_json(llm.complete(READER_SYSTEM, prompt, max_tokens=200).text).get("move", ""))
    except ValueError:
        return False
    return mv.rstrip("+#") == rec["best_san"][0].rstrip("+#")


def transfer(llm, recs: list[dict], hints: dict[str, list[str | None]], workers: int = 8, seed: int = 0) -> dict:
    """Accuracy of the reader per condition (name -> list of hints aligned with recs)."""
    out = {}
    for name, hs in hints.items():
        with ThreadPoolExecutor(workers) as ex:
            hits = list(ex.map(lambda t: reader_pick(llm, t[0], t[1], seed + t[2]),
                               [(r, h, i) for i, (r, h) in enumerate(zip(recs, hs))]))
        out[name] = {"accuracy": sum(hits) / len(hits), "n": len(hits)}
    return out


def idea_hint(p: dict, rec: dict) -> str:
    sans = list(rec["best_san"][:1]) + list(rec["alt_san"][:1])
    return mask_moves(f"{p.get('idea', '')} Plan: {p.get('plan', '')}", sans)


def save(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))


# ── idea-only judge ──────────────────────────────────────────────────────────

IDEA_SYSTEM = """You are a chess master. Given the engine analysis (ground truth) and a one-line coaching idea
for the best move, decide whether the idea is correct: it names the real reason the best move is better than
the alternative, and says nothing false about the position. Vague is fine; wrong is not.
Reply with one JSON object only."""


def idea_correct(llm, rec: dict, idea: str) -> dict:
    prompt = (f"{rec['facts']}\n\nCoaching idea for {rec['best_san'][0]}: \"{idea}\"\n\n"
              'Return JSON: {"correct": true/false, "reason": "<=20 words"}')
    resp = llm.complete(IDEA_SYSTEM, prompt, max_tokens=200)
    try:
        out = extract_json(resp.text)
    except ValueError:
        out = {"correct": None}
    out["cost_usd"] = resp.cost_usd
    return out


def idea_accuracy(llm, recs: list[dict], ideas: list[str], workers: int = 6) -> dict:
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda t: idea_correct(llm, *t), zip(recs, ideas)))
    ok = [r for r in res if r.get("correct") is not None]
    return {"n": len(ok), "correct": sum(bool(r["correct"]) for r in ok) / max(1, len(ok)),
            "cost_usd": round(sum(r.get("cost_usd", 0) for r in res), 3),
            "reasons": [r.get("reason", "") for r in res]}
