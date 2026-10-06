"""Rebuild PGNs from a run's per-move log: uv run python scripts/recover_pgn.py RUN_DIR [RUN_DIR ...]

The match runner appends every move (both players) to decisions.jsonl as it is played, but only
writes games.pgn when a game ends. If a match is killed (usage limit, crash) use this to get every
game, finished or not, as RUN_DIR/recovered_games.pgn. Raw players' written reasoning is kept as
move comments. Games already in games.pgn are still rebuilt, marked by their last decision.
"""

import json
import sys
from pathlib import Path

import chess
import chess.pgn


def recover(run_dir: Path) -> Path:
    rows = [json.loads(line) for line in (run_dir / "decisions.jsonl").read_text().splitlines() if line]
    meta = json.loads((run_dir / "meta.json").read_text()) if (run_dir / "meta.json").exists() else {}
    finished = set()
    if (run_dir / "games.jsonl").exists():
        finished = {json.loads(line)["game"] for line in (run_dir / "games.jsonl").read_text().splitlines() if line}
    out = []
    for g in sorted({r["game"] for r in rows}):
        moves = [r for r in rows if r["game"] == g]
        first = min(moves, key=lambda r: r["ply"])
        board = chess.Board(first["fen"])
        game = chess.pgn.Game.from_board(board)  # starts from the first logged position
        node = game
        names = {}
        for r in sorted(moves, key=lambda r: r["ply"]):
            names[r["color"]] = r["player"]
            if not r.get("uci"):
                break
            node = node.add_variation(chess.Move.from_uci(r["uci"]))
            why = ((r.get("search") or {}).get("reasoning") or "").replace("{", "(").replace("}", ")")
            if why:
                node.comment = why
        h = game.headers
        h["Event"] = f"recovered {run_dir.name}"
        h["Round"] = str(g)
        h["White"], h["Black"] = names.get("white", "?"), names.get("black", "?")
        h["Result"] = "*"
        h["Termination"] = "recovered from decisions.jsonl" + ("" if g in finished else " (game unfinished)")
        out.append(str(game))
    path = run_dir / "recovered_games.pgn"
    path.write_text("\n\n".join(out) + "\n")
    print(f"{path}: {len(out)} game(s)")
    return path


if __name__ == "__main__":
    for d in sys.argv[1:]:
        recover(Path(d))
