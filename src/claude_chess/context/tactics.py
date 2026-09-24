"""Tactical flags: en prise pieces, checks, captures with SEE, pins, threats, mate-in-1.

LLMs are weakest at noticing one-move tactics, so these are the most valuable lines in
the context. Everything is computed on real boards with python-chess.
"""

from __future__ import annotations

import chess

from .features import CNAME, VALUES, piece_name

SEE_VALUES = {**VALUES, chess.KING: 100}


def _value_at(board: chess.Board, sq: chess.Square) -> int:
    pt = board.piece_type_at(sq)
    return SEE_VALUES[pt] if pt else 0


def _least_valuable_capture(board: chess.Board, sq: chess.Square) -> chess.Move | None:
    best, best_v = None, 1000
    for a in board.attackers(board.turn, sq):
        v = SEE_VALUES[board.piece_type_at(a)]  # type: ignore[index]
        if v >= best_v:
            continue
        promo = None
        if board.piece_type_at(a) == chess.PAWN and chess.square_rank(sq) in (0, 7):
            promo = chess.QUEEN
        mv = chess.Move(a, sq, promotion=promo)
        if board.is_legal(mv):
            best, best_v = mv, v
    return best


def _recapture_gain(board: chess.Board, sq: chess.Square, depth: int = 0) -> int:
    """Best material the side to move gains by (optionally) recapturing on sq."""
    if depth > 12:
        return 0
    mv = _least_valuable_capture(board, sq)
    if mv is None:
        return 0
    gain = _value_at(board, sq) + (8 if mv.promotion else 0)
    board.push(mv)
    gain -= _recapture_gain(board, sq, depth + 1)
    board.pop()
    return max(0, gain)


def see(board: chess.Board, move: chess.Move) -> int:
    """Static exchange evaluation of a capture, in pawns, from the mover's view."""
    if board.is_en_passant(move):
        gained = 1
    else:
        gained = _value_at(board, move.to_square)
    if move.promotion:
        gained += SEE_VALUES[move.promotion] - 1
    b = board.copy(stack=False)
    b.push(move)
    return gained - _recapture_gain(b, move.to_square)


def _fmt_see(v: int) -> str:
    return f"+{v}" if v > 0 else str(v)


def _attacker_to_move(board: chess.Board, attacker: chess.Color) -> chess.Board:
    b = board.copy(stack=False)
    if b.turn != attacker:
        b.turn = attacker
        b.ep_square = None
    return b


def _en_prise(board: chess.Board, color: chess.Color) -> list[tuple[chess.Square, str]]:
    """Pieces of `color` the opponent could capture with a positive static exchange."""
    b = _attacker_to_move(board, not color)
    out = []
    for sq, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        best: tuple[int, chess.Move] | None = None
        for a in b.attackers(not color, sq):
            promo = chess.QUEEN if b.piece_type_at(a) == chess.PAWN and chess.square_rank(sq) in (0, 7) else None
            mv = chess.Move(a, sq, promotion=promo)
            if not b.is_legal(mv):
                continue
            v = see(b, mv)
            if best is None or v > best[0]:
                best = (v, mv)
        if best is None or best[0] <= 0:
            continue
        defenders = board.attackers(color, sq)
        why = "undefended" if not defenders else f"{piece_name(board, best[1].from_square)} wins ~{best[0]}"
        out.append((sq, why))
    return out


def _mates_in_one(board: chess.Board) -> list[str]:
    mates = []
    for mv in board.legal_moves:
        if not board.gives_check(mv):
            continue
        board.push(mv)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            mates.append(board.san(mv))
    return mates


def _winning_captures(board: chess.Board) -> list[tuple[str, int]]:
    caps = []
    for mv in board.legal_moves:
        if board.is_capture(mv):
            caps.append((board.san(mv), see(board, mv)))
    caps.sort(key=lambda t: -t[1])
    return caps


def tactics(board: chess.Board, tags: set[str]) -> list[str]:
    out: list[str] = []
    us, them = board.turn, not board.turn
    U, T = CNAME[us], CNAME[them]

    mates = _mates_in_one(board)
    if mates:
        out.append(f"!! {U} has MATE IN 1: {', '.join(mates)}")
        tags.add("tactics")

    # Our loose pieces.
    ours = _en_prise(board, us)
    if ours:
        out.append(f"{U} pieces en prise: " + "; ".join(f"{piece_name(board, s)} ({why})" for s, why in ours))
        tags.add("tactics")
    theirs = _en_prise(board, them)
    if theirs:
        out.append(f"{T} pieces en prise: " + "; ".join(f"{piece_name(board, s)} ({why})" for s, why in theirs))
        tags.add("tactics")

    caps = _winning_captures(board)
    if caps:
        shown = [f"{san} (SEE {_fmt_see(v)})" for san, v in caps[:8]]
        more = f" …+{len(caps) - 8} more" if len(caps) > 8 else ""
        out.append(f"Captures for {U}: {', '.join(shown)}{more}")
        if caps[0][1] > 0:
            tags.add("tactics")

    checks = [board.san(mv) for mv in board.legal_moves if board.gives_check(mv)]
    if checks:
        more = f" …+{len(checks) - 10} more" if len(checks) > 10 else ""
        out.append(f"Checks for {U}: {', '.join(checks[:10])}{more}")
    else:
        out.append(f"Checks for {U}: none")

    pins = []
    for color in (us, them):
        king = board.king(color)
        if king is None:
            continue
        for sq, p in board.piece_map().items():
            if p.color == color and p.piece_type != chess.KING and board.is_pinned(color, sq):
                pinner = next((a for a in board.attackers(not color, sq)
                               if chess.BB_SQUARES[king] & chess.ray(a, sq)), None)
                by = f" by {piece_name(board, pinner)}" if pinner is not None else ""
                pins.append(f"{CNAME[color]} {piece_name(board, sq)} pinned to king{by}")
    if pins:
        out.append("Pins: " + "; ".join(pins))
        tags.add("tactics")

    # Opponent's threats: what would they do if it were their move?
    if board.is_check():
        out.append(f"{U} is in check — must respond to it")
    else:
        nb = board.copy(stack=False)
        nb.push(chess.Move.null())
        threats = []
        opp_mates = _mates_in_one(nb)
        if opp_mates:
            threats.append(f"MATE IN 1 with {', '.join(opp_mates)}")
        for san, v in _winning_captures(nb):
            if v > 0:
                threats.append(f"{san} (wins ~{v})")
        if threats:
            out.append(f"{T} threatens: " + "; ".join(threats[:5]))
            tags.add("tactics")
        else:
            out.append(f"{T} threatens: nothing immediate (no winning captures or mates)")
    return out
