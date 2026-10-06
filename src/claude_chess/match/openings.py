"""Small set of balanced opening starts (SAN), 4-8 plies, used to vary games."""

import random

import chess

OPENINGS: dict[str, list[str]] = {
    "Ruy Lopez": ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"],
    "Italian": ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"],
    "Sicilian Najdorf": ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6"],
    "French": ["e4", "e6", "d4", "d5", "Nc3", "Nf6"],
    "Caro-Kann": ["e4", "c6", "d4", "d5", "Nc3", "dxe4", "Nxe4", "Bf5"],
    "QGD": ["d4", "d5", "c4", "e6", "Nc3", "Nf6"],
    "King's Indian": ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6"],
    "English": ["c4", "e5", "Nc3", "Nf6", "Nf3", "Nc6"],
}


def random_opening(pair: int, plies: int = 8, seed: int = 0) -> tuple[str, list[str]]:
    """A random main-line ECO opening of up to `plies` plies for game pair `pair` (both colours
    share it). Random walk over the book's main-line continuations (context/book.py), so no
    obscure sidelines; deterministic in (seed, pair)."""
    from claude_chess.context.book import book_move
    from claude_chess.context.openings import opening_label

    rng = random.Random(seed * 100003 + pair)
    board, sans = chess.Board(), []
    for _ in range(plies):
        mv = book_move(board, rng)
        if mv is None:
            break
        sans.append(board.san(mv))
        board.push(mv)
    return opening_label(board) or "random book line", sans
