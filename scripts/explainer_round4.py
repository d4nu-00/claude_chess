"""Round 4 (even more explanation data): uv run --extra ml python scripts/explainer_round4.py

Waits for scripts/explainer_collect.py to finish teacher_v3.jsonl, then E4 = E3's format on
teacher + teacher_v2 + teacher_v3 (each explanation shown ONCE — with ~5,500 positions one pass is
enough and halves training time; E3's best checkpoint came before its second pass), one epoch,
best checkpoint by val loss, same evaluation as A/D/E/E2/E3. Logs to data/logs/round4.log.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from explainer_round2 import ROOT, lora_jobs, log, pick_best  # noqa: E402

PY = [sys.executable]
NAME, ADAPTER = "E4_more_data", "E4"
LOG = ROOT / "data/logs/collect_v3.log"
FILES = ("datasets/explainer_v1/teacher.jsonl", "datasets/explainer_v1/teacher_v2.jsonl",
         "datasets/explainer_v1/teacher_v3.jsonl")


def main() -> None:
    while not (LOG.exists() and "finished:" in LOG.read_text()):
        time.sleep(300)
    sft = ROOT / f"data/sft_joint_{ADAPTER}"
    adapter = ROOT / f"data/models/joint_{ADAPTER}"
    if not (sft / "train.jsonl").exists():
        code = ("from pathlib import Path; from claude_chess.explainer import joint as J; "
                f"J.build_sft(Path('{sft}'), Path('{ROOT / 'data/models/enc_v1'}'), order='move_first', "
                f"with_relations=True, with_tactics=True, n_move_only=2000, teacher_repeat=1, teacher_paths={FILES!r})")
        log(f"{NAME}: building data")
        subprocess.run(PY + ["-c", code], cwd=ROOT, check=True)
    n_train = len((sft / "train.jsonl").read_text().splitlines())
    while lora_jobs():
        time.sleep(30)
    log(f"{NAME}: training {n_train // 2} iterations on {n_train} examples")
    subprocess.run(PY + ["-m", "claude_chess.explainer", "train-lm", "--data", str(sft), "--adapter", str(adapter),
                         "--iters", str(n_train // 2), "--batch-size", "2", "--grad-accumulation", "2", "--lr", "1e-4"],
                   cwd=ROOT, check=False)
    pick_best(adapter)
    (adapter / "joint_config.json").write_text((sft / "joint_config.json").read_text())
    log(f"{NAME}: evaluating")
    subprocess.run(PY + ["scripts/explainer_joint_eval.py", str(adapter), NAME, "250"], cwd=ROOT, check=False)
    res = json.loads((ROOT / "experiments/explainer/joint" / f"{NAME}.json").read_text())
    ideas = res.get("ideas", {})
    log(f"{NAME}: eval {res['eval']['explain']:.3f} puzzle {res['puzzle']['explain']:.3f} "
        f"ideas sound {ideas.get('sound')} true {ideas.get('true')}")
    log("done")


if __name__ == "__main__":
    main()
