"""Collect more teacher explanations, full speed across plan session windows:
uv run --extra ml python scripts/explainer_collect.py [N]

Opus 5.5, 5 positions per call (pilot: $0.020/label, 20/20 ideas correct — teacher_pilot.json).
New train-split positions, endgame-weighted (20/40/40 opening/middlegame/endgame), never
labelled before. Appends to datasets/explainer_v1/teacher_v2.jsonl (resumable). When the plan's
session limit is hit, reads "resets 3:20am" from the error, sleeps until a few minutes after,
and continues until N new labels exist.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

from claude_chess.explainer import data as D
from claude_chess.explainer import teacher as T
from claude_chess.llm import ClaudeCLIStream

OUT = Path("datasets/explainer_v1/teacher_v2.jsonl")
PILOT = Path("experiments/explainer/teacher_pilot")


def log(msg: str) -> None:
    print(f"[collect {time.strftime('%m-%d %H:%M')}] {msg}", flush=True)


def seconds_until_reset(msg: str, now: dt.datetime | None = None) -> float:
    """'... resets 3:20am (Europe/London)' -> seconds until then (+5 min); 30 min if unparseable."""
    now = now or dt.datetime.now()
    m = re.search(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", msg, re.I)
    if not m:
        return 1800.0
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    h = h % 12 + (12 if ap == "pm" else 0)
    t = now.replace(hour=h, minute=mins, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=1)
    return (t - now).total_seconds() + 300


def main(n: int = 2000, out: str | None = None, seed: int = 23) -> None:
    global OUT
    if out:
        OUT = Path(out)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists() and OUT.name == "teacher_v2.jsonl":  # seed with the pilot's Opus labels (40/40 correct)
        with OUT.open("w") as fh:
            for name in ("opus_x1", "opus_x5"):
                for ln in (PILOT / f"{name}.jsonl").read_text().splitlines():
                    fh.write(ln + "\n")
    data = D.load(("eval",))
    done: set[str] = set()  # never relabel a position from any earlier file
    for f in list(Path("datasets/explainer_v1").glob("teacher*.jsonl")) + list(PILOT.glob("*.jsonl")):
        if f != OUT:
            done |= {json.loads(ln)["fen"] for ln in f.read_text().splitlines()}
    have = len(OUT.read_text().splitlines()) if OUT.exists() else 0
    idx = T.select(data, {0: n}, seed=seed, weights=(0.2, 0.4, 0.4), exclude=done)
    recs = [{k: (data[k][i].item() if hasattr(data[k][i], "item") else str(data[k][i]))
             for k in ("fen", "best_line", "alt_line", "value", "value_alt", "split")} for i in idx]
    recs = recs[:n]  # run() skips positions already in OUT, so a resume continues to n in total
    del data
    scale = json.loads((D.DATA_DIR / "stats.json").read_text())["delta_scale"]
    llm = ClaudeCLIStream(model="claude-opus-5-5", effort="medium", timeout=900)
    while True:
        res = T.run(llm, recs, scale, OUT, workers=4, budget_usd=1e9, batch=5, log=log)
        total = len(OUT.read_text().splitlines())
        if not res["halted"]:
            log(f"finished: {total} labels in {OUT}")
            break
        wait = seconds_until_reset(res["message"])
        until = dt.datetime.now() + dt.timedelta(seconds=wait)
        log(f"session limit ({total} labels so far); waiting until {until:%H:%M} for the reset")
        # poll the wall clock: time.sleep's clock stops while the Mac sleeps, so one long sleep
        # can overshoot the reset by hours
        while dt.datetime.now() < until:
            time.sleep(60)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 2000, a[1] if len(a) > 1 else None, int(a[2]) if len(a) > 2 else 23)
