"""Round-2 orchestrator: uv run --extra ml python scripts/explainer_round2.py

Runs the joint-model experiments one GPU job at a time (16 GB machine):
  A reason-first + relations (training started separately) -> best ckpt -> eval
  B move-first   + relations -> train (same iterations) -> best ckpt -> eval
  C reason-first, no relations -> train -> best ckpt -> eval
then links data/models/joint_best to the variant with the highest move accuracy (explain prompt,
cloud-eval + puzzles) for scripts/play.py. Logs to data/logs/round2.log.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = [sys.executable]
ITERS = 1573


def log(msg: str) -> None:
    print(f"[round2 {time.strftime('%H:%M')}] {msg}", flush=True)


def lora_jobs() -> list[str]:
    out = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if "mlx_lm lora" in ln and "ps -eo" not in ln]


def training_running(adapter: Path) -> bool:
    # match by directory name: the job may have been launched with a relative path
    return any(f"/{adapter.name} " in ln + " " or f" {adapter.name} " in ln + " " or ln.rstrip().endswith(adapter.name)
               or f"models/{adapter.name}" in ln for ln in lora_jobs())


def wait_gpu_free() -> None:
    while lora_jobs():
        time.sleep(30)


def val_curve(adapter: Path) -> dict[int, float]:
    raw = (adapter / "train.log").read_text(errors="replace")
    raw = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw).replace("\r", "\n")
    return {int(m.group(1)): float(m.group(2)) for m in re.finditer(r"^\s*(\d+)\s+val\s+([0-9.]+)", raw, re.M)}


def pick_best(adapter: Path) -> int:
    curve = val_curve(adapter)
    saved = {int(p.name[:7]) for p in adapter.glob("*_adapters.safetensors")}
    cands = {it: v for it, v in curve.items() if it in saved}
    best = min(cands, key=cands.get)
    shutil.copy(adapter / f"{best:07d}_adapters.safetensors", adapter / "adapters.safetensors")
    (adapter / "CHOSEN.txt").write_text(f"iteration {best}, val {cands[best]}; curve {curve}\n")
    log(f"{adapter.name}: best checkpoint {best} (val {cands[best]})")
    return best


def train(sft: str, adapter: Path) -> None:
    log(f"training {adapter.name} on {sft}")
    subprocess.run(PY + ["-m", "claude_chess.explainer", "train-lm", "--data", sft, "--adapter", str(adapter),
                         "--iters", str(ITERS), "--batch-size", "2", "--grad-accumulation", "2", "--lr", "1e-4"],
                   cwd=ROOT, check=False)


def evaluate(adapter: Path, name: str) -> dict:
    log(f"evaluating {name}")
    subprocess.run(PY + ["scripts/explainer_joint_eval.py", str(adapter), name, "250"], cwd=ROOT, check=False)
    p = ROOT / "experiments/explainer/joint" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def main() -> None:
    m = ROOT / "data/models"
    # D (verified tactical outcome per candidate) jumped the queue after A's result (J1 not
    # supported: the model copied its instinct); C (no relations) is parked.
    variants = [("A_reason_first", m / "joint_A", "data/sft_joint_A"),
                ("D_tactics", m / "joint_D", "data/sft_joint_D"),
                ("E_tactics_move_first", m / "joint_E", "data/sft_joint_E")]  # B swapped for E: J3 at D's input
    results = {}
    for name, adapter, sft in variants:
        wait_gpu_free()  # one GPU job at a time: never evaluate next to a training run
        if not any(adapter.glob("*_adapters.safetensors")) or not (adapter / "train.log").exists():
            train(sft, adapter)
        pick_best(adapter)
        shutil.copy(ROOT / sft / "joint_config.json", adapter / "joint_config.json")
        done = ROOT / "experiments/explainer/joint" / f"{name}.json"
        res = json.loads(done.read_text()) if done.exists() and "ideas" in done.read_text() else evaluate(adapter, name)
        results[name] = {k: res.get(k, {}).get("explain") for k in ("eval", "puzzle")}
        log(f"{name}: {results[name]}")
        scored = {k: (v["eval"] or 0) + (v["puzzle"] or 0) for k, v in results.items()}
        winner = max(scored, key=scored.get)
        link = m / "joint_best"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(dict((n, a) for n, a, _ in variants)[winner])
        log(f"joint_best -> {winner}")
    # J6: the same D model with deeper verified tactics at inference (no retraining; same text format)
    wait_gpu_free()
    log("evaluating D_depth4 (D with depth-4 tactical facts)")
    subprocess.run(PY + ["scripts/explainer_joint_eval.py", str(m / "joint_D"), "D_depth4", "250", "4"], cwd=ROOT,
                   check=False)
    (ROOT / "experiments/explainer/joint/summary.json").write_text(json.dumps(results, indent=1))
    log("done")


if __name__ == "__main__":
    main()
