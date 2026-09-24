"""Live experiment dashboard: rewrites experiments/<prefix>/LIVE.md and live.html.

Usage: uv run python scripts/live_status.py exp1 [--expected 80] [--loop 20]
No LLM calls — reads runs/*<prefix>*/ (games.jsonl, decisions.jsonl) and logs/<prefix>-*.log.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path

from claude_chess.match.stats import load_games

PLY_RE = re.compile(r"^\[g(\d+)\] ply +(\d+)")


def snapshot(prefix: str, expected: int, runs_root: Path, logs: Path, t0: float) -> tuple[str, str]:
    games = load_games(runs_root, prefix)
    configs = sorted({g["config"] for g in games} | _configs_from_logs(logs, prefix))
    levels = sorted({g["level"] for g in games} | _levels_from_logs(logs, prefix))
    cost = 0.0
    for rd in runs_root.iterdir():
        if rd.is_dir() and prefix in rd.name and (rd / "decisions.jsonl").exists():
            for line in (rd / "decisions.jsonl").read_text().splitlines():
                d = json.loads(line)
                if "maia" not in d.get("player", ""):
                    cost += d.get("cost") or 0.0
    running = []
    for lf in sorted(logs.glob(f"{prefix}-*.log")):
        last: dict[str, int] = {}
        done = set()
        for line in lf.read_text(errors="ignore").splitlines():
            m = PLY_RE.match(line)
            if m:
                last[m.group(1)] = int(m.group(2))
            if "RESULT" in line:
                done.add(line.split("]")[0].lstrip("[g"))
        for g, ply in sorted(last.items()):
            if g not in done:
                running.append(f"{lf.stem.removeprefix(prefix + '-')} g{g} @ ply {ply}")
    n = len(games)
    pct = 100 * n / expected if expected else 0
    elapsed = time.time() - t0
    eta = f"~{(elapsed / n) * (expected - n) / 60:.0f} min" if n else "–"
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))

    def cell(c: str, lv: int) -> str:
        gs = [g for g in games if g["config"] == c and g["level"] == lv]
        if not gs:
            return "·"
        w = sum(g["score"] == 1 for g in gs)
        d = sum(g["score"] == 0.5 for g in gs)
        lo = sum(g["score"] == 0 for g in gs)
        return f"{sum(g['score'] for g in gs):g}/{len(gs)} ({w}-{d}-{lo})"

    def total(c: str) -> str:
        gs = [g for g in games if g["config"] == c]
        return f"{sum(g['score'] for g in gs):g}/{len(gs)}" if gs else "·"

    stamp = time.strftime("%H:%M:%S")
    md = [f"# Live: experiment `{prefix}` (updated {stamp})", "",
          f"**{n}/{expected} games complete ({pct:.0f}%)** `{bar}`  ·  API cost so far **${cost:.2f}**"
          f"  ·  ETA {eta}", "",
          "| config | " + " | ".join(f"maia-{lv}" for lv in levels) + " | total |",
          "|---|" + "---|" * (len(levels) + 1)]
    for c in configs:
        md.append(f"| {c} | " + " | ".join(cell(c, lv) for lv in levels) + f" | {total(c)} |")
    md += ["", f"**In progress ({len(running)}):** " + (", ".join(running) if running else "none")]

    rows = "".join(
        f"<tr><th>{html.escape(c)}</th>" + "".join(f"<td>{html.escape(cell(c, lv))}</td>" for lv in levels)
        + f"<td class=t>{html.escape(total(c))}</td></tr>" for c in configs)
    head = "".join(f"<th>maia-{lv}</th>" for lv in levels)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="20">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Live experiment</title>
<style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--acc:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--acc:#60a5fa}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:980px}}
h1{{font-size:20px;margin:0 0 4px}} .mut{{color:var(--mut)}}
.bar{{height:10px;background:var(--line);border-radius:5px;overflow:hidden;margin:12px 0}}
.bar>div{{height:100%;width:{pct:.1f}%;background:var(--acc)}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;min-width:640px;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
.t{{font-weight:600}}
</style></head><body>
<h1>Experiment {html.escape(prefix)}: Claude vs Maia</h1>
<div class=mut>updated {stamp} · refreshes every 20 s</div>
<div class=bar><div></div></div>
<p><b>{n}/{expected} games ({pct:.0f}%)</b> · API cost so far <b>${cost:.2f}</b> · ETA {eta}</p>
<div class=wrap><table><tr><th>config</th>{head}<th>total</th></tr>{rows}</table></div>
<p class=mut>Cell = score/games (W-D-L) from Claude's side.</p>
<p><b>In progress ({len(running)}):</b> {html.escape(', '.join(running) or 'none')}</p>
</body></html>"""
    return "\n".join(md) + "\n", page


def _configs_from_logs(logs: Path, prefix: str) -> set[str]:
    out = set()
    for lf in logs.glob(f"{prefix}-*.log"):
        parts = lf.stem.split("-")  # prefix-model-arm-maiaNNNN
        if len(parts) >= 4:
            out.add(f"{parts[-3]}-{parts[-2]}")
    return out


def _levels_from_logs(logs: Path, prefix: str) -> set[int]:
    return {int(m.group(1)) for lf in logs.glob(f"{prefix}-*.log") if (m := re.search(r"maia(\d{4})", lf.stem))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--expected", type=int, default=80)
    ap.add_argument("--loop", type=float, default=0, help="rewrite every N seconds until --until-file vanishes")
    ap.add_argument("--runs-root", default="runs")
    ap.add_argument("--logs", default="logs")
    args = ap.parse_args()
    out = Path("experiments") / args.prefix
    out.mkdir(parents=True, exist_ok=True)
    # ETA counts from the experiment start: the earliest run's meta.json (written once at start;
    # log files' ctime changes on every write, so they can't be used).
    metas = [m.stat().st_mtime for m in Path(args.runs_root).glob(f"*{args.prefix}*/meta.json")]
    t0 = min(metas or [time.time()])
    while True:
        md, page = snapshot(args.prefix, args.expected, Path(args.runs_root), Path(args.logs), t0)
        (out / "LIVE.md").write_text(md)
        (out / "live.html").write_text(page)
        if not args.loop or md.startswith(f"# Live: experiment `{args.prefix}`") and \
                f"**{args.expected}/{args.expected} games" in md:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
