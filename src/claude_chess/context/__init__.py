"""Context builder: turn a board into a PositionContext and render it as compact markdown.

Pure Python (python-chess), no LLM calls. See wiki/pages/context-builder.md.
"""

from __future__ import annotations

import chess

from ..types import PositionContext
from . import concepts as _concepts
from . import learned as _learned
from .character import imbalances, middlegame_character
from .endgame import endgame_info
from .relations import last_move, relations, temperature
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


def build_context(board: chess.Board, include_legal_moves: bool = True, version: int = 2) -> PositionContext:
    """version 2 = original context; 3 adds piece relations, last-move changes, tactical
    temperature (adaptive ordering in render_context) and keeps only the top concept page."""
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
    if ph == "endgame":
        ctx.endgame = endgame_info(board, tags)
    else:
        ctx.character = middlegame_character(board, tags) + imbalances(board, tags)

    concept_lines: list[str] = []
    if entry is not None and ph != "endgame":
        plan = _concepts.opening_plan(entry.name)
        if plan:
            concept_lines.append(f"Opening plans ({plan[0]}): {plan[1]}")
    concept_lines += [f"Structure plan — {p}" for p in structure_plans]
    for page in _concepts.retrieve(tags, k=1 if version >= 3 else 3):
        concept_lines.append(f"{page.title}: " + " ".join(page.summary))
    ctx.concepts = concept_lines
    ctx.tags = sorted(tags)
    ctx.lessons = [f"{les.title}: " + " ".join(les.summary) for les in _learned.retrieve(tags, k=1)]
    if version >= 3:
        ctx.relations = relations(board)
        ctx.last_move = last_move(board)
        ctx.temperature = temperature(board)
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
        ("Endgame", ctx.endgame, 10),
        ("Middlegame character & imbalances", ctx.character, 8),
        ("Pawn structure", ctx.pawn_structure, 12),
        ("King safety", ctx.king_safety, 4),
        ("Piece activity", ctx.piece_activity, 5),
        ("Lessons from your past games", ctx.lessons, 1),
        ("Guidance", ctx.concepts, 6),
    ]
    if ctx.temperature is not None:  # v3: budget context by how tactical the position is
        hot = ctx.temperature >= 4
        lines[-1] += f", {'SHARP (tactics first)' if hot else 'quiet (plans first)'}"
        last = ("Opponent's last move", ctx.last_move, 5)
        rel = ("Piece relations (attackers / defenders)", ctx.relations, 8 if hot else 4)
        tac = ("Tactics (side to move first)", ctx.tactics, 10)
        eg = ("Endgame", ctx.endgame, 10)
        if hot:
            sections = [last, tac, rel, eg, ("Middlegame character & imbalances", ctx.character, 3),
                        ("King safety", ctx.king_safety, 4), ("Pawn structure", ctx.pawn_structure, 4),
                        ("Piece activity", ctx.piece_activity, 3),
                        ("Lessons from your past games", ctx.lessons, 1), ("Guidance", ctx.concepts, 2)]
        else:
            sections = [last, tac, ("Middlegame character & imbalances", ctx.character, 8), eg,
                        ("Pawn structure", ctx.pawn_structure, 8), rel, ("King safety", ctx.king_safety, 4),
                        ("Piece activity", ctx.piece_activity, 4),
                        ("Lessons from your past games", ctx.lessons, 1), ("Guidance", ctx.concepts, 3)]
    for title, items, cap in sections:
        if not items:
            continue
        lines += ["", f"## {title}"]
        lines += [f"- {it}" for it in items[:cap]]
    if include_legal_moves and ctx.legal_moves_san:
        lines += ["", f"## Legal moves ({len(ctx.legal_moves_san)})"]
        lines += _group_legal(ctx.legal_moves_san)
    return "\n".join(lines)
