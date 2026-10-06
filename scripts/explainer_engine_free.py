"""Engine-free mode check: uv run --extra ml python scripts/explainer_engine_free.py [N]

For N held-out test positions: the encoder picks the best/alternative moves and rolls out the
lines (no Stockfish); concept facts are still computed exactly by concepts.py; the student
explains. Reports agreement with Stockfish and the fact checker's pass rate on the student's text.
Writes experiments/explainer/engine_free.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import chess

from claude_chess.explainer import facts as F
from claude_chess.explainer import pipeline as P
from claude_chess.explainer import teacher as T


def main(n: int = 30) -> None:
    recs = [json.loads(ln) for ln in Path("datasets/explainer_v1/teacher.jsonl").read_text().splitlines()]
    test = [r for r in recs if r["split"] == 2 and r["verify"]["ok"]][:n]
    ex = P.Explainer(P.DEFAULT_LM, "data/models/lm_v1", "data/models/enc_v1")
    rows, same_best, ok = [], 0, 0
    for r in test:
        e = ex.explain(r["fen"], engine_free=True)
        pf = e.facts
        v = T.verify(e.parsed, pf)
        sf_best = r["best_san"][0]
        same_best += pf.best_san[0] == sf_best
        ok += v["ok"]
        rows.append({"fen": r["fen"], "encoder_best": pf.best_san[0], "encoder_alt": pf.alt_san[0],
                     "stockfish_best": sf_best, "encoder_eval": F.eval_words(pf.value, chess.Board(r["fen"]).turn),
                     "student": e.parsed, "verify": v})
    out = {"n": len(rows), "encoder_best_is_stockfish_best": same_best / max(1, len(rows)),
           "student_verifier_ok": ok / max(1, len(rows)), "rows": rows}
    Path("experiments/explainer").mkdir(parents=True, exist_ok=True)
    Path("experiments/explainer/engine_free.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
