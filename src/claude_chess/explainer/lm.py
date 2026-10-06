"""Student explainer: a small open LM (MLX, LoRA) that condenses the facts block into an idea.

Input  = the same rendered facts the teacher saw (facts.render, no ASCII board).
Target = the teacher's verified label, idea FIRST (condensation is the product; detail after).
Only labels that passed `teacher.verify` are trained on.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

SYSTEM = ("You are a chess coach. From the engine analysis and verified facts, explain the best move "
          "to a club player: the idea first, in a few plain words, then why, why not the alternative, "
          "the concepts, and the plan. Only mention moves that appear in the analysis.")

ORDER = (("idea", "Idea"), ("assessment", "Assessment"), ("why_best", "Why {best}"),
         ("why_not_alt", "Why not {alt}"), ("concepts", "Concepts"), ("novel_concept", "New concept"),
         ("plan", "Plan"), ("difficulty", "Difficulty"))


def format_target(label: dict, best: str, alt: str) -> str:
    out = []
    for key, head in ORDER:
        v = label.get(key)
        if key == "concepts":
            v = ", ".join(v or [])
        if key == "novel_concept" and not v:
            continue
        out.append(f"{head.format(best=best, alt=alt)}: {str(v).strip()}")
    return "\n".join(out)


def parse_output(text: str, best: str, alt: str) -> dict:
    """Inverse of format_target (tolerant: strips <think> blocks, missing fields stay empty)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    heads = {head.format(best=best, alt=alt).lower(): key for key, head in ORDER}
    out: dict = {"novel_concept": ""}
    for line in text.splitlines():
        if ":" not in line:
            continue
        h, v = line.split(":", 1)
        key = heads.get(h.strip().lower())
        if key is None:
            low = h.strip().lower()  # tolerate a different move in "Why X" / "Why not X"
            key = "why_not_alt" if low.startswith("why not") else "why_best" if low.startswith("why") else None
        if key:
            out[key] = v.strip()
    if "concepts" in out:
        out["concepts"] = [c.strip() for c in out["concepts"].split(",") if c.strip()]
    return out


def student_facts(rec: dict, scale: dict | None = None) -> str:
    """The student's input, re-rendered from FEN + lines with the CURRENT facts renderer (piece
    list, captures named, threats) — not the teacher's stored block, which relied on a board
    diagram the student can't read."""
    from claude_chess.explainer import facts as F

    pf = F.compute(rec["fen"], rec["best_line"].split(), rec["alt_line"].split(), rec["value"], rec["value_alt"],
                   scale)
    return F.render(pf, board_diagram=False)


def _scale() -> dict:
    from claude_chess.explainer import data as D

    p = D.DATA_DIR / "stats.json"
    return json.loads(p.read_text())["delta_scale"] if p.exists() else {}


def example(rec: dict, scale: dict | None = None) -> dict:
    best, alt = rec["best_san"][0], rec["alt_san"][0]
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": student_facts(rec, scale)},
                         {"role": "assistant", "content": format_target(rec["label"], best, alt)}]}


def build_sft(teacher_path: Path, out_dir: Path, seed: int = 0, n_valid: int = 40) -> dict[str, int]:
    """train/valid/test.jsonl in mlx_lm chat format from verified teacher labels (split by the
    structure-hash split carried on each record). Only `n_valid` val positions are kept for
    LoRA validation; the rest of val joins train (labels are scarce — teacher calls hit the
    plan's session limit). Test is never touched."""
    from claude_chess.explainer import facts as F
    from claude_chess.explainer import teacher as T

    recs = [json.loads(ln) for ln in teacher_path.read_text().splitlines() if ln.strip()]
    for r in recs:  # re-verify with the current verifier (labels are kept, flags are recomputed)
        if r["label"]:
            pf = F.compute(r["fen"], r["best_line"].split(), r["alt_line"].split(), r["value"], r["value_alt"])
            r["verify"] = T.verify(r["label"], pf)
    ok = [r for r in recs if r["verify"]["ok"]]
    buckets: dict[str, list] = {"train": [], "valid": [], "test": []}
    n_val = 0
    scale = _scale()
    for r in ok:
        name = {0: "train", 1: "valid", 2: "test"}[r["split"]]
        if name == "valid":
            n_val += 1
            if n_val > n_valid:
                name = "train"
        buckets[name].append(example(r, scale))
    random.Random(seed).shuffle(buckets["train"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in buckets.items():
        with (out_dir / f"{name}.jsonl").open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    return {k: len(v) for k, v in buckets.items()} | {"total": len(recs), "verified": len(ok)}


def train(model: str, data_dir: Path, adapter_dir: Path, iters: int = 600, batch_size: int = 4,
          lr: float = 1e-4, num_layers: int = 16, max_seq_length: int = 1024, log_file: Path | None = None,
          grad_accumulation: int = 1) -> int:
    cmd = [sys.executable, "-m", "mlx_lm", "lora", "--model", model, "--train", "--data", str(data_dir),
           "--adapter-path", str(adapter_dir), "--iters", str(iters), "--batch-size", str(batch_size),
           "--learning-rate", str(lr), "--num-layers", str(num_layers), "--mask-prompt",
           "--max-seq-length", str(max_seq_length), "--steps-per-eval", "100", "--val-batches", "20",
           "--save-every", "100", "--grad-checkpoint", "--grad-accumulation-steps", str(grad_accumulation)]
    with (log_file.open("w") if log_file else open("/dev/null", "w")) as fh:
        return subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode


class Student:
    """Loaded student model; `explain(facts_text, best, alt)` -> (raw text, parsed dict)."""

    def __init__(self, model: str, adapter: str | None = None, max_tokens: int = 400):
        from mlx_lm import load

        self.model, self.tok = load(model, adapter_path=adapter)
        self.max_tokens = max_tokens

    def prompt(self, facts_text: str) -> str:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": facts_text}]
        try:
            return self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False,
                                                enable_thinking=False)
        except TypeError:
            return self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)

    def explain(self, facts_text: str, best: str, alt: str) -> tuple[str, dict]:
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        text = generate(self.model, self.tok, prompt=self.prompt(facts_text), max_tokens=self.max_tokens,
                        sampler=make_sampler(temp=0.0), verbose=False)
        return text, parse_output(text, best, alt)
