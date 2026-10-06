"""Teacher: Claude turns engine lines + verified facts into a condensed human explanation.

Claude is NOT asked which move is best — Stockfish already decided. It is asked *why*, in
the fewest human words, and to tag the idea with concept ids from `vocab.VOCAB` (or name a
new one). `verify()` then checks every concrete claim against the board before the text can
become training data (see the LLM error list in wiki/pages/reasoning-dataset.md).
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import chess

from claude_chess.explainer import concepts as C
from claude_chess.explainer import facts as F
from claude_chess.explainer import vocab
from claude_chess.llm import LLMUnavailable, extract_json

OUT_DIR = Path("datasets/explainer_v1")
FIELDS = ("assessment", "idea", "why_best", "why_not_alt", "concepts", "novel_concept", "plan", "difficulty")
DIFFICULTY = ("obvious", "natural", "hard", "computer")

SYSTEM = """You are a strong chess coach who explains engine analysis to club players (1200-2000).
Players can't use long variations. They need the IDEA: the one or two human concepts that make the
best move right and the alternative worse, said in plain words they can reuse in other games.

Rules:
- The engine lines and the verified facts are ground truth. Do not invent tactics, captures or
  threats that are not in the lines or facts. If you mention a move, it must appear in the lines
  given (or be legal in the position). Use SAN.
- Lead with the idea. Vague is fine ("open the f-file against the king"); wrong is not.
- Prefer the most general true reason. Don't recite the line — name what it achieves.
- If the best move is a pure engine move with no human idea, say so and set difficulty to "computer".
- Reply with ONE JSON object and nothing else."""

PROMPT = """{facts}

Concept vocabulary (choose 1-3 ids for "concepts", most important first):
{vocab}

Return JSON with exactly these keys:
{{"assessment": "<=20 words: who stands better and the main reason",
 "idea": "<=15 words: the human idea behind the best move",
 "why_best": "<=40 words: concrete justification (may cite the first moves of the best line)",
 "why_not_alt": "<=30 words: what the alternative misses or allows",
 "concepts": ["id", ...],
 "novel_concept": "short name if the key idea is not in the vocabulary, else empty string",
 "plan": "<=15 words: what the side to move should aim for next",
 "difficulty": "obvious | natural | hard | computer (how findable for a club player)"}}"""


def build_prompt(pf: F.PositionFacts) -> str:
    return PROMPT.format(facts=F.render(pf), vocab=vocab.render_vocab())


PROMPT_BATCH = """Explain each of the {n} positions below independently. Same rules for every position.

{blocks}

Concept vocabulary (choose 1-3 ids for "concepts", most important first):
{vocab}

Return ONE JSON object: {{"labels": [ ... ]}} with exactly {n} entries in the same order, each:
{{"position": <number>, "assessment": "<=20 words", "idea": "<=15 words: the human idea behind the best move",
 "why_best": "<=40 words", "why_not_alt": "<=30 words", "concepts": ["id", ...],
 "novel_concept": "short name or empty string", "plan": "<=15 words",
 "difficulty": "obvious | natural | hard | computer"}}"""


def build_batch_prompt(pfs: list[F.PositionFacts]) -> str:
    blocks = "\n\n".join(f"### Position {k + 1}\n{F.render(pf)}" for k, pf in enumerate(pfs))
    return PROMPT_BATCH.format(n=len(pfs), blocks=blocks, vocab=vocab.render_vocab())


# ── verification ─────────────────────────────────────────────────────────────

# piece moves/references and pawn captures; bare squares ("d5") are too ambiguous to check
_SAN_RE = re.compile(r"\b(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?|O-O(?:-O)?)[+#]?")
# "wins a pawn" is a claim; "wins a pawn back" / "wins back" is a recovery and isn't checked
_WIN_RE = re.compile(r"\b(?:wins?|winning|nets?|picks? up|grabs?)\s+(?:a|an|the|two|both)?\s*"
                     r"(pawn|pawns|piece|knight|bishop|rook|queen|exchange|material)\b(?!\s+back)", re.I)
_MATE_RE = re.compile(r"\b(?:mates|forced mate|checkmate|mate in \d)\b", re.I)


def _positions_along(board: chess.Board, lines: list[list[str]], plies: int = 8) -> list[chess.Board]:
    """The root, every position along the lines, and the root with the opponent to move (so the
    opponent's threats — "meets the threat ...Bxd1" — count as real moves)."""
    out = [board.copy(stack=False)]
    if not board.is_check():
        nb = board.copy(stack=False)
        nb.push(chess.Move.null())
        out.append(nb)
    for line in lines:
        b = board.copy(stack=False)
        for u in line[:plies]:
            mv = chess.Move.from_uci(u)
            if not b.is_legal(mv):
                break
            b.push(mv)
            out.append(b.copy(stack=False))
    return out


def _ref_ok(token: str, boards: list[chess.Board]) -> bool:
    tok = token.rstrip("+#")
    for b in boards:
        try:
            b.parse_san(tok)
            return True
        except ValueError:
            pass
        # a piece reference like "Nd5" = "the knight on d5"
        if tok[0] in "KQRBN" and len(tok) >= 3 and tok[-2] in "abcdefgh" and tok[-1] in "12345678":
            p = b.piece_at(chess.parse_square(tok[-2:]))
            if p and p.symbol().upper() == tok[0]:
                return True
    return False


def verify(label: dict, pf: F.PositionFacts) -> dict:
    """Flags for one teacher label. `ok` = no hard failure (bad JSON fields, unknown concept,
    move/piece reference not in the position or lines, false material or mate claim)."""
    flags: list[str] = []
    for k in FIELDS:
        if k not in label:
            flags.append(f"missing:{k}")
    cons = label.get("concepts") or []
    if not isinstance(cons, list) or not cons or any(c not in vocab.IDS for c in cons):
        flags.append("bad_concepts")
    if label.get("difficulty") not in DIFFICULTY:
        flags.append("bad_difficulty")
    board = chess.Board(pf.fen)
    boards = _positions_along(board, [pf.best_line, pf.alt_line])
    text_best = " ".join(str(label.get(k, "")) for k in ("idea", "why_best", "assessment", "plan"))
    text_all = text_best + " " + str(label.get("why_not_alt", ""))
    bad = sorted({t for t in _SAN_RE.findall(text_all) if not _ref_ok(t, boards)})
    if bad:
        flags.append("bad_ref:" + ",".join(bad[:5]))
    # material claims about the best move must match the best line (balance gained vs alt)
    gain = pf.d_best.get("g.material_balance", 0.0) - pf.d_alt.get("g.material_balance", 0.0)
    gain_abs = pf.d_best.get("g.material_balance", 0.0)
    if _WIN_RE.search(str(label.get("idea", "")) + " " + str(label.get("why_best", ""))) and gain <= 0 and gain_abs <= 0:
        flags.append("material_claim")
    mates = pf.d_best.get("g.checkmate", 0.0) > 0 or pf.value > 0.995
    if _MATE_RE.search(str(label.get("idea", "")) + " " + str(label.get("why_best", ""))) and not mates \
            and pf.d_alt.get("g.checkmate", 0.0) >= 0 and "threat" not in text_best.lower():
        flags.append("mate_claim")
    # soft: concept ids that have detectors but none of them is active/changing
    soft = []
    for cid in cons if isinstance(cons, list) else []:
        h = vocab.BY_ID.get(cid)
        if not h or not h.detectors:
            continue
        keys = [f"{s}.{d}" for d in h.detectors for s in ("us", "them", "g") if f"{s}.{d}" in C.KEYS]
        if not any(pf.root.get(k) or pf.d_best.get(k) or pf.d_alt.get(k) for k in keys):
            soft.append(cid)
    hard = [f for f in flags if not f.startswith("missing:novel")]
    return {"ok": not hard, "flags": flags, "unsupported_concepts": soft}


# ── running ──────────────────────────────────────────────────────────────────


def label_one(llm, rec: dict, scale: dict[str, float]) -> dict:
    pf = F.from_record(rec, scale)
    prompt = build_prompt(pf)
    t0 = time.monotonic()
    resp = llm.complete(SYSTEM, prompt, max_tokens=800)
    try:
        label = extract_json(resp.text)
    except ValueError:
        label = {}
    ver = verify(label, pf)
    return {
        "fen": rec["fen"], "split": int(rec["split"]), "best_line": rec["best_line"], "alt_line": rec["alt_line"],
        "value": float(rec["value"]), "value_alt": float(rec["value_alt"]), "best_san": pf.best_san,
        "alt_san": pf.alt_san, "salience": pf.sal, "facts": F.render(pf, board_diagram=False),
        "label": label, "verify": ver, "model": getattr(llm, "model", "?"), "cost_usd": resp.cost_usd,
        "seconds": round(time.monotonic() - t0, 1), "raw": resp.text if not label else "",
    }


def _result(rec: dict, pf: F.PositionFacts, label: dict, llm, cost: float, seconds: float, raw: str) -> dict:
    return {
        "fen": rec["fen"], "split": int(rec["split"]), "best_line": rec["best_line"], "alt_line": rec["alt_line"],
        "value": float(rec["value"]), "value_alt": float(rec["value_alt"]), "best_san": pf.best_san,
        "alt_san": pf.alt_san, "salience": pf.sal, "facts": F.render(pf, board_diagram=False),
        "label": label, "verify": verify(label, pf), "model": getattr(llm, "model", "?"), "cost_usd": cost,
        "seconds": seconds, "raw": raw if not label else "",
    }


def label_batch(llm, recs: list[dict], scale: dict[str, float]) -> list[dict]:
    """Several positions in ONE call: the system prompt, rules and vocabulary are paid once.
    Cost and time are split evenly across the positions."""
    if len(recs) == 1:
        return [label_one(llm, recs[0], scale)]
    pfs = [F.from_record(r, scale) for r in recs]
    t0 = time.monotonic()
    resp = llm.complete(SYSTEM, build_batch_prompt(pfs), max_tokens=800 * len(recs))
    try:
        labels = extract_json(resp.text).get("labels") or []
    except ValueError:
        labels = []
    by_pos = {int(lb.get("position", k + 1)): lb for k, lb in enumerate(labels) if isinstance(lb, dict)}
    secs = round((time.monotonic() - t0) / len(recs), 1)
    out = []
    for k, (rec, pf) in enumerate(zip(recs, pfs)):
        lb = dict(by_pos.get(k + 1) or {})
        lb.pop("position", None)
        out.append(_result(rec, pf, lb, llm, resp.cost_usd / len(recs), secs, resp.text if not lb else ""))
    return out


def select(data: dict, n_per_split: dict[int, int], seed: int = 0, min_gap: float = 0.04,
           max_gap: float = 0.6, weights: tuple[float, float, float] = (0.3, 0.45, 0.25),
           exclude: set[str] | None = None) -> list[int]:
    """Instructive positions: the alternative costs >= min_gap win prob (a real choice), not
    both moves already decided (mate/crushing), stratified by phase within each split."""
    import numpy as np

    rng = np.random.default_rng(seed)
    gap = data["value"] - data["value_alt"]
    phase = data["root"][:, C.KEYS.index("g.phase")]
    both_decided = ((data["value"] > 0.97) & (data["value_alt"] > 0.97)) | ((data["value"] < 0.03) & (data["value_alt"] < 0.03))
    ok = (data["src"] == 0) & (data["has_alt"] == 1) & (gap >= min_gap) & (gap <= max_gap) & ~both_decided
    out: list[int] = []
    for split, n in n_per_split.items():
        idx = np.flatnonzero(ok & (data["split"] == split))
        if exclude:
            idx = np.asarray([i for i in idx if str(data["fen"][i]) not in exclude], dtype=np.int64)
        buckets = [idx[phase[idx] > 0.75], idx[(phase[idx] > 0.3) & (phase[idx] <= 0.75)], idx[phase[idx] <= 0.3]]
        for bkt, w in zip(buckets, weights):  # opening-ish / middlegame / endgame
            k = min(len(bkt), int(round(n * w)))
            out += rng.choice(bkt, size=k, replace=False).tolist()
    return out


def run(llm, records: list[dict], scale: dict[str, float], out_path: Path, workers: int = 6,
        budget_usd: float = 50.0, log=print, batch: int = 1) -> dict:
    """Label records in parallel, appending to out_path; resumable (skips FENs already done);
    stops submitting new work once the running cost passes the budget."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    spent = 0.0
    if out_path.exists():
        for ln in out_path.read_text().splitlines():
            if ln.strip():
                r = json.loads(ln)
                done.add(r["fen"])
                spent += r.get("cost_usd", 0.0)
    todo = [r for r in records if r["fen"] not in done]
    log(f"[teacher] {len(done)} done (${spent:.2f}), {len(todo)} to go, budget ${budget_usd:.2f}")
    lock = threading.Lock()
    n_ok = n = 0
    halted = False  # set on a usage/rate limit: stop submitting, let in-flight calls finish
    halt_msg = ""
    with ThreadPoolExecutor(workers) as ex, out_path.open("a") as fh:
        futs = {}
        it = iter(todo)
        def submit_next() -> bool:
            if spent >= budget_usd or halted:
                return False
            chunk = [r for r in (next(it, None) for _ in range(batch)) if r is not None]
            if not chunk:
                return False
            futs[ex.submit(label_batch, llm, chunk, scale)] = chunk
            return True
        for _ in range(workers * 2):
            submit_next()
        while futs:
            for fut in as_completed(list(futs)):
                futs.pop(fut)
                try:
                    res = fut.result()
                except LLMUnavailable as e:  # session/rate limit: halt; rerun later to resume
                    halted = True
                    halt_msg = str(e)
                    log(f"[teacher] halting on backend limit: {e}")
                    break
                except Exception as e:  # other failure: log and move on (never write a fake label)
                    log(f"[teacher] error: {e}")
                    submit_next()
                    break
                with lock:
                    for r in res:
                        fh.write(json.dumps(r) + "\n")
                        spent += r["cost_usd"]
                        n += 1
                        n_ok += r["verify"]["ok"]
                    fh.flush()
                if n % 25 < len(res):
                    log(f"[teacher] {n} new, {n_ok} ok, ${spent:.2f} total")
                submit_next()
                break
    log(f"[teacher] {'HALTED (limit)' if halted else 'finished'}: {n} new, {n_ok} verified ok, ${spent:.2f} total")
    return {"halted": halted, "message": halt_msg, "new": n, "ok": n_ok, "spent": spent}
