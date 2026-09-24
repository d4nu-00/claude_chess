"""Opening identification against the bundled lichess ECO table (CC0).

Matching is by position (EPD), so transpositions are recognised. We report the
deepest book position reached anywhere in the game, and note when the game left book.

The raw data lives in knowledge/openings/{a..e}.tsv (eco, name, pgn). Parsing ~3.6k PGN
lines takes ~1s, so a derived `epd_index.tsv` is cached next to them and rebuilt
automatically if missing or older than the sources.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chess
import chess.pgn

from .paths import KNOWLEDGE_DIR

OPENINGS_DIR = KNOWLEDGE_DIR / "openings"
INDEX_FILE = OPENINGS_DIR / "epd_index.tsv"
SOURCES = [OPENINGS_DIR / f"{c}.tsv" for c in "abcde"]


@dataclass(frozen=True)
class OpeningEntry:
    eco: str
    name: str
    plies: int


def _pos_key(board: chess.Board) -> str:
    # Board + side + castling + legal ep square: exactly what EPD encodes.
    return board.epd()


def _build_index() -> dict[str, OpeningEntry]:
    index: dict[str, OpeningEntry] = {}
    for src in SOURCES:
        if not src.exists():
            continue
        with src.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                game = chess.pgn.read_game(io.StringIO(row["pgn"]))
                if game is None:
                    continue
                board = game.board()
                for mv in game.mainline_moves():
                    board.push(mv)
                key = _pos_key(board)
                entry = OpeningEntry(row["eco"], row["name"], board.ply())
                old = index.get(key)
                # Keep the canonical (shortest) move order for a transposed position.
                if old is None or entry.plies < old.plies:
                    index[key] = entry
    return index


def _write_index(index: dict[str, OpeningEntry]) -> None:
    try:
        with INDEX_FILE.open("w", encoding="utf-8") as fh:
            for key, e in index.items():
                fh.write(f"{key}\t{e.eco}\t{e.name}\t{e.plies}\n")
    except OSError:
        pass  # read-only checkout: just rebuild in memory next time


@lru_cache(maxsize=1)
def load_index() -> dict[str, OpeningEntry]:
    src_mtime = max((s.stat().st_mtime for s in SOURCES if s.exists()), default=0)
    if INDEX_FILE.exists() and INDEX_FILE.stat().st_mtime >= src_mtime:
        index: dict[str, OpeningEntry] = {}
        with INDEX_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                key, eco, name, plies = line.rstrip("\n").split("\t")
                index[key] = OpeningEntry(eco, name, int(plies))
        return index
    index = _build_index()
    _write_index(index)
    return index


@lru_cache(maxsize=1)
def _max_book_plies() -> int:
    return max((e.plies for e in load_index().values()), default=0)


def identify_opening(board: chess.Board) -> tuple[OpeningEntry | None, int | None]:
    """Return (deepest book entry seen in the game, fullmove number where book was left).

    The second element is None while the current position is still in book.
    """
    index = load_index()
    root = board.root()
    best: OpeningEntry | None = index.get(_pos_key(root))
    best_ply = 0
    limit = _max_book_plies() + 12  # transpositions into book this late are irrelevant
    replay = root.copy(stack=False)
    for i, mv in enumerate(board.move_stack):
        if i >= limit:
            break
        replay.push(mv)
        hit = index.get(_pos_key(replay))
        if hit is not None:
            best, best_ply = hit, i + 1
    if best is None:
        return None, None
    total = len(board.move_stack)
    if best_ply >= total:
        return best, None
    # First ply that is out of book is ply index best_ply (0-based) from the root.
    offset = 0 if root.turn == chess.WHITE else 1
    left_at = root.fullmove_number + (best_ply + offset) // 2
    return best, left_at


def opening_label(board: chess.Board) -> str | None:
    entry, left_at = identify_opening(board)
    if entry is None:
        return None
    label = f"{entry.eco} {entry.name}"
    if left_at is not None:
        label += f" (out of book since move {left_at})"
    return label
