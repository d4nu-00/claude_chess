"""Round 3 (more explanation data, J7): uv run --extra ml python scripts/explainer_round3.py

E2 = E's format (move-first, relations, depth-2 tactics) trained on the old 573 + the first window
of new Opus labels; E3 = the same with all ~2,000 new labels. Both evaluated on the same 500
positions + the same 100 idea-judge positions as A/D/E. Runs alongside scripts/explainer_collect.py
(which owns the Claude usage); the judge waits out session limits. Logs to data/logs/round3.log.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from explainer_round2 import ROOT, lora_jobs, log, pick_best  # noqa: E402

V2 = ROOT / "datasets/explainer_v1/teacher_v2.jsonl"
PY = [sys.executable]


def n_labels() -> int:
    return len(V2.read_text().splitlines()) if V2.exists() else 0


def collection_finished() -> bool:
    p = ROOT / "data/logs/collect.log"
    return p.exists() and "finished:" in p.read_text()


def build_train_eval(name: str, adapter_name: str) -> None:
    sft = ROOT / f"data/sft_joint_{adapter_name}"
    adapter = ROOT / f"data/models/joint_{adapter_name}"
    result = ROOT / "experiments/explainer/joint" / f"{name}.json"
    if result.exists() and "ideas" in result.read_text():  # already trained and evaluated
        log(f"{name}: already done, skipping")
        return
    code = ("from pathlib import Path; from claude_chess.explainer import joint as J; "
            f"J.build_sft(Path('{sft}'), Path('{ROOT / 'data/models/enc_v1'}'), order='move_first', "
            "with_relations=True, with_tactics=True, n_move_only=2000, "
            "teacher_paths=('datasets/explainer_v1/teacher.jsonl', 'datasets/explainer_v1/teacher_v2.jsonl'))")
    if not (sft / "train.jsonl").exists():
        log(f"{name}: building data from {n_labels()} new labels")
        subprocess.run(PY + ["-c", code], cwd=ROOT, check=True)
    n_train = len((sft / "train.jsonl").read_text().splitlines())
    iters = n_train // 2  # one epoch at batch 2
    while lora_jobs():
        time.sleep(30)
    log(f"{name}: training {iters} iterations on {n_train} examples")
    subprocess.run(PY + ["-m", "claude_chess.explainer", "train-lm", "--data", str(sft), "--adapter", str(adapter),
                         "--iters", str(iters), "--batch-size", "2", "--grad-accumulation", "2", "--lr", "1e-4"],
                   cwd=ROOT, check=False)
    pick_best(adapter)
    (adapter / "joint_config.json").write_text((sft / "joint_config.json").read_text())
    log(f"{name}: evaluating")
    subprocess.run(PY + ["scripts/explainer_joint_eval.py", str(adapter), name, "250"], cwd=ROOT, check=False)
    res = json.loads((ROOT / "experiments/explainer/joint" / f"{name}.json").read_text())
    ideas = res.get("ideas", {})
    log(f"{name}: eval {res['eval']['explain']:.3f} puzzle {res['puzzle']['explain']:.3f} "
        f"ideas sound {ideas.get('sound')} true {ideas.get('true')}")


def main() -> None:
    while n_labels() < 640 and not collection_finished():
        time.sleep(60)
    build_train_eval("E2_more_labels", "E2")
    while not collection_finished():
        time.sleep(300)
    build_train_eval("E3_all_labels", "E3")
    log("done")


if __name__ == "__main__":
    main()
