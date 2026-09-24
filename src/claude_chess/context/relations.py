"""Context v3: relations, change and move-conditioned facts (see wiki/pages/context-research.md).

Our board-vision probe showed Claude knows WHERE pieces are but not WHAT THEY ATTACK, and
that blunders are refuted by replies that the pre-move context never mentions. These three
feature groups target that, all computed exactly on a real board:

- `relations(board)`   attack/defence map for attacked or loose pieces (+ overloaded defenders)
- `last_move(board)`   what the opponent's last move changed (new attacks, discovered attacks,
                       pieces it stopped defending, new threats)
- `move_delta(board, move)`  what OUR candidate changes (pieces it hangs or leaves undefended,
                       opponent's forcing replies, new attacks, king shelter, pawn structure)
- `temperature(board)` how tactical the position is — decides how context is budgeted.
"""

from __future__ import annotations

import chess

from .features import CNAME, VALUES, is_passed, piece_name
from .tactics import _en_prise, see

NAMES = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B", chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}


def _sq_names(board: chess.Board, squares) -> str:
    return ", ".join(piece_name(board, s) for s in sorted(squares, key=lambda s: -VALUES[board.piece_type_at(s)]))


def relations(board: chess.Board, limit: int = 8) -> list[str]:
    """Who attacks / defends each attacked piece; loose minor/major pieces; overloaded defenders."""
    items: list[tuple[int, str]] = []
    sole_defender: dict[int, list[int]] = {}
    for sq, p in board.piece_map().items():
        if p.piece_type == chess.KING:
            continue
        att = board.attackers(not p.color, sq)
        dfn = board.attackers(p.color, sq)
        who = f"{CNAME[p.color]} {piece_name(board, sq)}"
        if att:
            d = f"defended by {_sq_names(board, dfn)}" if dfn else "UNDEFENDED"
            items.append((VALUES[p.piece_type] * 10 + (5 if not dfn else 0),
                          f"{who}: attacked by {_sq_names(board, att)}; {d}"))
            if len(dfn) == 1:
                sole_defender.setdefault(next(iter(dfn)), []).append(sq)
        elif not dfn and p.piece_type != chess.PAWN:
            items.append((VALUES[p.piece_type], f"{who}: loose (undefended, not attacked yet)"))
    for dsq, guarded in sole_defender.items():
        if len(guarded) >= 2:
            items.append((50, f"OVERLOADED: {CNAME[board.color_at(dsq)]} {piece_name(board, dsq)} is the only "
                               f"defender of {_sq_names(board, guarded)}"))
    items.sort(key=lambda t: -t[0])
    return [s for _, s in items[:limit]]


def _attacks_on(board: chess.Board, frm: int, color: chess.Color) -> set[int]:
    return {t for t in board.attacks(frm) if board.color_at(t) == color}


def last_move(board: chess.Board) -> list[str]:
    """What the opponent's last move changed, from the side to move's point of view."""
    if not board.move_stack:
        return []
    mv = board.peek()
    before = board.copy(stack=True)
    before.pop()
    them, us = before.turn, board.turn
    san = before.san(mv)
    out = [f"{CNAME[them]} just played {san}" + (" (a capture)" if before.is_capture(mv) else "")]
    moved = board.piece_at(mv.to_square)
    if moved is not None:
        targets = [t for t in _attacks_on(board, mv.to_square, us) if board.piece_type_at(t) != chess.KING]
        if targets:
            out.append(f"{san} attacks: " + ", ".join(
                f"{piece_name(board, t)}{'' if board.attackers(us, t) else ' (undefended!)'}" for t in targets))
    # Discovered attacks: other enemy pieces that now hit our pieces they did not hit before.
    disc = []
    for sq in chess.SquareSet(board.pieces_mask(chess.BISHOP, them) | board.pieces_mask(chess.ROOK, them)
                              | board.pieces_mask(chess.QUEEN, them)):
        if sq == mv.to_square:
            continue
        new = _attacks_on(board, sq, us) - _attacks_on(before, sq, us)
        for t in new:
            if board.piece_type_at(t) != chess.KING:
                disc.append(f"{piece_name(board, sq)}→{piece_name(board, t)}")
    if disc:
        out.append("Discovered/opened attacks: " + ", ".join(disc))
    # Pieces the mover stopped defending (opportunities for us).
    if moved is not None:
        was = {t for t in before.attacks(mv.from_square) if before.color_at(t) == them}
        now = {t for t in board.attacks(mv.to_square) if board.color_at(t) == them}
        dropped = [t for t in was - now - {mv.to_square} if board.piece_at(t) and not board.attackers(them, t)
                   and board.attackers(us, t)]
        if dropped:
            out.append(f"{san} stopped defending: " + ", ".join(piece_name(board, t) for t in dropped)
                       + " (now attacked and undefended)")
    # New threats (null-move winning captures) that did not exist before the move.
    if not board.is_check():
        nb = board.copy(stack=False)
        nb.push(chess.Move.null())
        new_thr = []
        for m in nb.legal_moves:
            if nb.is_capture(m) and see(nb, m) > 0:
                new_thr.append(nb.san(m))
        if new_thr:
            out.append(f"{CNAME[them]} now threatens: " + ", ".join(new_thr[:4]))
    return out


def move_delta(board: chess.Board, move: chess.Move, limit: int = 5) -> list[str]:
    """What OUR candidate `move` changes (short facts; empty list = nothing notable)."""
    us = board.turn
    after = board.copy(stack=False)
    after.push(move)
    facts: list[str] = []
    if after.is_checkmate():
        return ["checkmate"]
    hung_before = {s for s, _ in _en_prise(board, us)}
    hung_after = [(s, why) for s, why in _en_prise(after, us) if s not in hung_before]
    for s, why in hung_after:
        facts.append(f"leaves {piece_name(after, s)} en prise ({why})")
    hung_after_all = {x for x, _ in _en_prise(after, us)}
    fixed = [s for s in hung_before if s not in hung_after_all and after.piece_at(s)]
    if move.from_square in hung_before and move.to_square not in hung_after_all:
        fixed.append(move.to_square)  # the attacked piece itself moved to safety
    if fixed:
        facts.append("rescues " + ", ".join(piece_name(after, s) for s in fixed))
    ignored = [s for s in hung_before if s in hung_after_all and s != move.to_square]
    if ignored:
        facts.append("IGNORES the threat to " + ", ".join(piece_name(after, s) for s in ignored))
    checks = [after.san(m) for m in after.legal_moves if after.gives_check(m)]
    if checks:
        facts.append("allows checks: " + ", ".join(checks[:4]))
    wins = [after.san(m) for m in after.legal_moves if after.is_capture(m) and see(after, m) > 0]
    if wins:
        facts.append("opponent then wins material with: " + ", ".join(wins[:3]))
    new_targets = [t for t in _attacks_on(after, move.to_square, not us)
                   if after.piece_type_at(t) != chess.KING and
                   (not after.attackers(not us, t) or VALUES[after.piece_type_at(t)] > VALUES[after.piece_type_at(move.to_square)])]
    if new_targets:
        facts.append("creates threats on " + ", ".join(piece_name(after, t) for t in new_targets))
    p = board.piece_at(move.from_square)
    if p is not None and p.piece_type == chess.PAWN:
        f = chess.square_file(move.to_square)
        own = [s for s in after.pieces(chess.PAWN, us) if abs(chess.square_file(s) - f) == 1]
        if is_passed(after, us, move.to_square) and not is_passed(board, us, move.from_square):
            facts.append("creates a passed pawn")
        if not own and any(abs(chess.square_file(s) - chess.square_file(move.from_square)) == 1
                           for s in board.pieces(chess.PAWN, us)):
            facts.append("pawn becomes isolated")
        king = board.king(us)
        if king is not None and abs(chess.square_file(move.from_square) - chess.square_file(king)) <= 1 \
                and chess.square_distance(move.from_square, king) <= 2:
            facts.append("weakens own king shelter")
    return facts[:limit]


def temperature(board: chess.Board) -> int:
    """0 = quiet … higher = sharp: winning captures, pieces en prise, checks, threats."""
    t = 0
    t += sum(1 for m in board.legal_moves if board.is_capture(m) and see(board, m) > 0) * 2
    t += len(_en_prise(board, board.turn)) * 3
    t += sum(1 for m in board.legal_moves if board.gives_check(m))
    if board.is_check():
        t += 3
    return t
