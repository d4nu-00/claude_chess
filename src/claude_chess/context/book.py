"""Opening book from the bundled ECO lines (knowledge/openings/*.tsv, lichess chess-openings).

Engines use a book so no thinking time goes on known theory. Here that also saves Claude
calls. Endgames are untouched: the book only covers positions on named ECO lines.

The ECO table names dubious lines too (Englund, Grob, ...), so continuations are ranked by
how much named theory passes through the position they reach — a theory-depth proxy for
main lines that needs no engine (Stockfish never influences a Claude player's move).
"""

from __future__ import annotations

import csv
import io
import random
from functools import lru_cache

import chess
import chess.pgn

from .openings import SOURCES


@lru_cache(maxsize=1)
def through_counts() -> dict[str, int]:
    """EPD -> number of named ECO lines passing through (or ending at) that position."""
    counts: dict[str, int] = {}
    for src in SOURCES:
        if not src.exists():
            continue
        with src.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                game = chess.pgn.read_game(io.StringIO(row["pgn"]))
                if game is None:
                    continue
                b = game.board()
                seen = {b.epd()}
                for mv in game.mainline_moves():
                    b.push(mv)
                    seen.add(b.epd())
                for k in seen:
                    counts[k] = counts.get(k, 0) + 1
    return counts


def continuations(board: chess.Board) -> list[tuple[chess.Move, int]]:
    """Book moves from `board` with their theory counts, best first. Empty = out of book."""
    counts = through_counts()
    if board.epd() not in counts:
        return []
    out = []
    for mv in board.legal_moves:
        board.push(mv)
        n = counts.get(board.epd(), 0)
        board.pop()
        if n:
            out.append((mv, n))
    out.sort(key=lambda t: -t[1])
    return out


def book_move(board: chess.Board, rng: random.Random, share: float = 0.5) -> chess.Move | None:
    """A main-line book move: among continuations with >= `share` of the top count, pick one
    weighted by count (a little variety, never an obscure sideline)."""
    cont = continuations(board)
    if not cont:
        return None
    top = cont[0][1]
    main = [(m, n) for m, n in cont if n >= share * top]
    return rng.choices([m for m, _ in main], weights=[n for _, n in main])[0]
