"""All raw-player games (merged across original + resumed runs) as one PGN with reasoning comments.

uv run python scripts/export_pgn.py [OUT.pgn]   (default runs/all_games_with_reasoning.pgn)
Opus moves carry its written justification as a comment; every move carries a Stockfish depth-12
[%eval] (White's view, pawns). Games still running / aborted are marked Result "*".
"""

import glob
import json
import os
import re
import sys

import chess
import chess.engine
import chess.pgn

from claude_chess.match.baselines import open_stockfish


def main(out_path: str = "runs/all_games_with_reasoning.pgn") -> None:
    games: dict[tuple[str, int], dict[int, dict]] = {}
    results: dict[tuple[str, int], str] = {}
    for rd in sorted(d for d in glob.glob("runs/2*raw-*") if os.path.isdir(d)):
        rows = [json.loads(x) for x in open(rd + "/decisions.jsonl") if x.strip()]
        cond = next((re.match(r"raw-(\w+?)\(", r["player"]).group(1) for r in rows if r["player"].startswith("raw")), None)
        if cond is None:
            continue
        for r in rows:
            games.setdefault((cond, int(r["game"])), {})[r["ply"]] = r
        if os.path.exists(rd + "/games.jsonl"):
            for g in map(json.loads, open(rd + "/games.jsonl")):
                if g["result"] != "*":
                    results[(cond, int(g["game"]))] = g["result"]
    sf, lim, blocks = open_stockfish(), chess.engine.Limit(depth=12), []
    for (cond, g), plies in sorted(games.items()):
        board, game = chess.Board(), chess.pgn.Game()
        node, opus_white = game, None
        for ply in sorted(plies):
            r = plies[ply]
            if ply != board.ply() + 1:
                break
            if r["player"].startswith("raw"):
                opus_white = board.turn == chess.WHITE
            mv = chess.Move.from_uci(r["uci"])
            board.push(mv)
            node = node.add_variation(mv)
            cp = sf.analyse(board, lim)["score"].white().score(mate_score=10000)
            why = ((r.get("search") or {}).get("reasoning") or "").replace("{", "(").replace("}", ")")
            node.comment = f"[%eval {cp / 100:.2f}]" + (f" {why}" if why else "")
        name = f"Claude Opus 5.5 (raw-{cond}, max effort)"
        h = game.headers
        h["Event"] = f"Opus 5.5 raw-{cond} vs Maia-3 79M Elo 2400"
        h["Date"] = "2026.09.26"
        h["Round"] = str(g)
        h["White"], h["Black"] = (name, "Maia-3 79M @2400") if opus_white else ("Maia-3 79M @2400", name)
        h["Result"] = results.get((cond, g), "*")
        h["Termination"] = "finished" if (cond, g) in results else "unfinished (in progress or aborted)"
        blocks.append(str(game))
    sf.quit()
    with open(out_path, "w") as f:
        f.write("\n\n".join(blocks) + "\n")
    print(f"{out_path}: {len(blocks)} game(s)")


if __name__ == "__main__":
    main(*sys.argv[1:])
