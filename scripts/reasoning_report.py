"""Render a raw-player run's saved reasoning as markdown: uv run python scripts/reasoning_report.py RUN_DIR

One section per move: ply, FEN, move played, thinking tokens, the model's written justification
(and thinking text when the backend exposed any), plus Stockfish eval/loss for the move when analysis exists. Output: RUN_DIR/reasoning.md
"""

import json
import sys
from pathlib import Path


def main(run_dir: str) -> None:
    rd = Path(run_dir)
    rows = [json.loads(line) for line in (rd / "decisions.jsonl").read_text().splitlines() if line]
    ana = {}
    if (rd / "move_analysis.jsonl").exists():
        for line in (rd / "move_analysis.jsonl").read_text().splitlines():
            a = json.loads(line)
            ana[(int(a["game"]), a["ply"])] = a
    out = [f"# Reasoning — {rd.name}\n"]
    for game in sorted({r["game"] for r in rows}):
        out.append(f"\n## Game {game}\n")
        for r in (r for r in rows if r["game"] == game):
            info = r.get("search") or {}
            if "reasoning" not in info:
                out.append(f"- ply {r['ply']} {r['player']}: {r['san']}\n")
                continue
            n = (r["ply"] + 1) // 2
            num = f"{n}." if r["color"] == "white" else f"{n}..."
            out.append(f"\n### ply {r['ply']}: {num} {r['san']} ({r['color']}, {info['thinking_tokens']} thinking tokens, "
                       f"${r['cost']:.3f}, {r['seconds']:.0f}s)\n\n`{r['fen']}`\n")
            if r.get("illegal_attempts"):
                out.append(f"\nRejected attempts: {r['illegal_attempts']}\n")
            if info.get("thinking"):
                out.append(f"\n**Thinking summary:**\n\n{info['thinking']}\n")
            a = ana.get((int(r["game"]), r["ply"]))
            if a:  # Stockfish evals are stored from the mover's view; show White's
                sg = 1 if r["color"] == "white" else -1
                out.append(f"\n**Stockfish (d12):** eval {sg * a['eval_before']:+d} -> {sg * a['eval_after']:+d} cp (White view), "
                           f"loss {a['cpl']} cp, engine's choice {a['best_move']}\n")
            out.append(f"\n**Why:**\n\n{info['reasoning']}\n")
    (rd / "reasoning.md").write_text("".join(out))
    print(rd / "reasoning.md")


if __name__ == "__main__":
    main(sys.argv[1])
