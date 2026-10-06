"""Which teacher gives the most good labels per unit of plan usage?
uv run --extra ml python scripts/explainer_teacher_pilot.py [N]

Same N new train positions (endgame-weighted, none labelled before) for: Opus one-per-call,
Opus 5-per-call, Sonnet 5-per-call, Haiku 5-per-call. Reports cost/label, seconds/label, verifier
pass rate, idea length, and a blind Opus judge's "idea correct?" per label.
Writes experiments/explainer/teacher_pilot.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from claude_chess.explainer import data as D
from claude_chess.explainer import evaluate as EV
from claude_chess.explainer import teacher as T
from claude_chess.llm import ClaudeCLIStream

CONDITIONS = [("opus_x1", "claude-opus-5-5", 1), ("opus_x5", "claude-opus-5-5", 5),
              ("sonnet_x5", "claude-sonnet-5-5", 5), ("haiku_x5", "claude-haiku-4-5-20251001", 5)]


def main(n: int = 20) -> None:
    data = D.load(("eval",))
    done = {json.loads(ln)["fen"] for ln in Path("datasets/explainer_v1/teacher.jsonl").read_text().splitlines()}
    idx = T.select(data, {0: n}, seed=11, weights=(0.2, 0.4, 0.4), exclude=done)
    recs = [{k: (data[k][i].item() if hasattr(data[k][i], "item") else str(data[k][i]))
             for k in ("fen", "best_line", "alt_line", "value", "value_alt", "split")} for i in idx]
    scale = json.loads((D.DATA_DIR / "stats.json").read_text())["delta_scale"]
    out_dir = Path("experiments/explainer/teacher_pilot")
    out_dir.mkdir(parents=True, exist_ok=True)
    judge = ClaudeCLIStream(model="claude-opus-5-5", effort="medium", timeout=600)
    summary = {}
    for name, model, batch in CONDITIONS:
        path = out_dir / f"{name}.jsonl"
        llm = ClaudeCLIStream(model=model, effort="medium", timeout=900)
        T.run(llm, recs, scale, path, workers=4, budget_usd=10, batch=batch)
        rows = [json.loads(ln) for ln in path.read_text().splitlines()]
        ideas = [r["label"].get("idea", "") for r in rows]
        jud = EV.idea_accuracy(judge, rows, ideas, workers=4)
        summary[name] = {
            "n": len(rows), "cost_per_label": round(sum(r["cost_usd"] for r in rows) / max(1, len(rows)), 4),
            "seconds_per_label": round(sum(r["seconds"] for r in rows) / max(1, len(rows)), 1),
            "verifier_ok": sum(r["verify"]["ok"] for r in rows) / max(1, len(rows)),
            "idea_words": sum(len(i.split()) for i in ideas) / max(1, len(ideas)),
            "idea_correct": jud["correct"], "judge_cost": jud["cost_usd"],
        }
        print(name, json.dumps(summary[name]), flush=True)
    Path("experiments/explainer/teacher_pilot.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
