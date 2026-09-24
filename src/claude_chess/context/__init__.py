"""Context builder: turn a board into a PositionContext and render it as compact markdown.

Pure Python (python-chess), no LLM calls. See wiki/pages/context-builder.md.
"""

from __future__ import annotations

import chess

from ..types import PositionContext
from . import concepts as _concepts
from .features import CNAME, king_safety, material, pawn_structure, phase, piece_activity
from .openings import identify_opening
from .tactics import tactics

__all__ = ["build_context", "render_context"]

_PIECE_ORDER = [
    (chess.KING, "King"), (chess.QUEEN, "Queen"), (chess.ROOK, "Rook"),
    (chess.BISHOP, "Bishop"), (chess.KNIGHT, "Knight"), (chess.PAWN, "Pawn"),
]


def _endgame_tags(board: chess.Board, tags: set[str]) -> None:
    minors = board.knights | board.bishops
    if not board.queens and not minors:
        if board.rooks:
            tags.add("rook-endgame")
        else:
            tags.add("pawn-endgame")
    tags.add("endgame")


def _legal_moves_grouped(board: chess.Board) -> list[str]:
    groups: dict[int, list[str]] = {pt: [] for pt, _ in _PIECE_ORDER}
    for mv in board.legal_moves:
        pt = board.piece_type_at(mv.from_square)
        groups[pt].append(board.san(mv))  # type: ignore[index]
    out: list[str] = []
    for pt, _ in _PIECE_ORDER:
        out += sorted(groups[pt])
    return out


def build_context(board: chess.Board, include_legal_moves: bool = True) -> PositionContext:
    tags: set[str] = set()
    structure_plans: list[str] = []
    ph = phase(board)
    if ph == "endgame":
        _endgame_tags(board, tags)
    elif ph == "opening":
        tags.add("opening")

    entry, left_at = identify_opening(board)
    opening = None
    if entry is not None:
        opening = f"{entry.eco} {entry.name}"
        if left_at is not None:
            opening += f" (out of book since move {left_at})"

    ctx = PositionContext(
        fen=board.fen(),
        side_to_move=CNAME[board.turn].lower(),
        phase=ph,
        opening=opening,
        material=material(board, tags),
        pawn_structure=pawn_structure(board, tags, structure_plans),
        king_safety=king_safety(board, tags, ph),
        piece_activity=piece_activity(board, tags, ph),
        tactics=tactics(board, tags),
    )

    concept_lines: list[str] = []
    if entry is not None and ph != "endgame":
        plan = _concepts.opening_plan(entry.name)
        if plan:
            concept_lines.append(f"Opening plans ({plan[0]}): {plan[1]}")
    concept_lines += [f"Structure plan — {p}" for p in structure_plans]
    for page in _concepts.retrieve(tags, k=3):
        concept_lines.append(f"{page.title}: " + " ".join(page.summary))
    ctx.concepts = concept_lines
    if include_legal_moves:
        ctx.legal_moves_san = _legal_moves_grouped(board)
    return ctx


def _group_legal(board_moves: list[str]) -> list[str]:
    """Group already piece-sorted SAN moves by their leading piece letter."""
    groups: dict[str, list[str]] = {}
    for san in board_moves:
        if san.startswith("O-O"):
            key = "King"
        else:
            key = {"K": "King", "Q": "Queen", "R": "Rook", "B": "Bishop", "N": "Knight"}.get(san[0], "Pawn")
        groups.setdefault(key, []).append(san)
    return [f"- {name}: {' '.join(groups[name])}" for _, name in _PIECE_ORDER if name in groups]


def render_context(ctx: PositionContext, include_legal_moves: bool = True) -> str:
    board = chess.Board(ctx.fen)
    lines = [
        "## Position",
        f"- FEN: `{ctx.fen}`",
        f"- Side to move: **{ctx.side_to_move}** (move {board.fullmove_number}), phase: {ctx.phase}",
    ]
    if ctx.opening:
        lines.append(f"- Opening: {ctx.opening}")
    lines += ["", "## Material", f"- {ctx.material}"]
    sections = [
        ("Tactics (side to move first)", ctx.tactics, 10),
        ("Pawn structure", ctx.pawn_structure, 12),
        ("King safety", ctx.king_safety, 4),
        ("Piece activity", ctx.piece_activity, 5),
        ("Guidance", ctx.concepts, 6),
    ]
    for title, items, cap in sections:
        if not items:
            continue
        lines += ["", f"## {title}"]
        lines += [f"- {it}" for it in items[:cap]]
    if include_legal_moves and ctx.legal_moves_san:
        lines += ["", f"## Legal moves ({len(ctx.legal_moves_san)})"]
        lines += _group_legal(ctx.legal_moves_san)
    return "\n".join(lines)
