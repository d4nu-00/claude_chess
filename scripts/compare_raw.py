"""Compare the raw-player board conditions: uv run python scripts/compare_raw.py [RUNS_ROOT]

Pools every run under RUNS_ROOT whose player is raw-<unicode|text|ascii|image>, keyed by condition.
Moves are deduplicated by (condition, game, ply) so a resumed run's replayed plies aren't double
counted. Cost/time/thinking come from decisions.jsonl, quality (CPL) from move_analysis.jsonl.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

COND = re.compile(r"^raw-(text|ascii|image)")


def load(path: Path):
    return [json.loads(x) for x in path.read_text().splitlines() if x] if path.exists() else []


def main(root: str = "runs") -> None:
    moves: dict[tuple, dict] = {}
    for rd in sorted(Path(root).glob("*raw-*")):
        dec, ana = load(rd / "decisions.jsonl"), {(str(a["game"]), a["ply"]): a for a in load(rd / "move_analysis.jsonl")}
        for r in dec:
            m = COND.match(r["player"])
            if not m:
                continue
            key = (m.group(1), int(r["game"]), r["ply"])
            info = r.get("search") or {}
            a = ana.get((str(r["game"]), r["ply"]))
            cur = moves.setdefault(key, {})
            cur.update(cost=r["cost"], sec=r["seconds"], tok=info.get("thinking_tokens", 0),
                       illegal=len(r["illegal_attempts"]))
            if a:
                cur["cpl"] = a["cpl"]
    by = defaultdict(list)
    for (c, g, p), v in moves.items():
        by[c].append(v)
    results = defaultdict(list)
    for rd in sorted(Path(root).glob("*raw-*")):
        for g in load(rd / "games.jsonl"):
            m = COND.match(g["white"]) or COND.match(g["black"])
            if m:
                results[m.group(1)].append(f"g{g['game']}:{g['result']}")
    print("| condition | Opus moves | cost $ | $/move | s/move | thinking tok/move | ACPL | inacc | mist | blund | illegal | games |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in ("text", "ascii", "image"):
        v = by.get(c, [])
        if not v:
            continue
        cp = [x["cpl"] for x in v if "cpl" in x]
        n = len(v)
        print(f"| {c} | {n} | {sum(x['cost'] for x in v):.2f} | {sum(x['cost'] for x in v) / n:.3f} | "
              f"{sum(x['sec'] for x in v) / n:.0f} | {sum(x['tok'] for x in v) / n:.0f} | "
              f"{(sum(cp) / len(cp)) if cp else float('nan'):.1f} (n={len(cp)}) | "
              f"{sum(50 <= x < 100 for x in cp)} | {sum(100 <= x < 300 for x in cp)} | {sum(x >= 300 for x in cp)} | "
              f"{sum(x['illegal'] for x in v)} | {' '.join(results.get(c, [])) or 'unfinished'} |")


if __name__ == "__main__":
    main(*sys.argv[1:])
