"""Middlegame character and imbalances: what KIND of position is this, and what plans follow?

Classical classification of the centre (Pachman / Silman): open, closed (locked), dynamic
(pawn tension), mobile centre, semi-open — each implies different plans. Plus the
imbalance list a strong player checks before planning: minor pieces vs structure, space,
pawn chains and where they point, available pawn breaks, development.
All pure python-chess; every sentence names the colour explicitly.
"""

from __future__ import annotations

import chess

from .features import CNAME, rel_rank

CENTER_FILES = (3, 4)  # d, e

PLANS = {
    "open": ("Open centre: piece play dominates — bishops and rooks gain value, development "
             "and king safety are critical, open files/diagonals toward the king decide."),
    "closed": ("Closed (locked) centre: play happens on the wings via pawn breaks; attack on "
               "the side your pawn chain points to; knights often beat bishops; slow "
               "manoeuvring is fine because the centre cannot suddenly open."),
    "dynamic": ("Dynamic centre (pawn tension): whoever resolves the tension changes the "
                "character — calculate the exchanges; keep the tension if releasing it "
                "frees the opponent's pieces."),
    "mobile": ("Mobile pawn centre: the side with the centre wants to advance it to cramp "
               "and open lines; the other side must blockade or hit it with pawn levers "
               "and pieces before it rolls."),
    "semi-open": ("Semi-open centre: one side has a central pawn majority/space; use the "
                  "half-open files and pressure the remaining central pawns."),
}


def _pawn_at(board: chess.Board, sq: int, color: chess.Color) -> bool:
    p = board.piece_at(sq)
    return p is not None and p.piece_type == chess.PAWN and p.color == color


def _fwd(color: chess.Color) -> int:
    return 8 if color == chess.WHITE else -8


def center_type(board: chess.Board) -> tuple[str, str]:
    """(kind, detail) for the central pawn configuration."""
    locked: list[str] = []
    for f in CENTER_FILES:
        for sq in chess.SquareSet(board.pawns & board.occupied_co[chess.WHITE] & chess.BB_FILES[f]):
            ahead = sq + 8
            if ahead < 64 and _pawn_at(board, ahead, chess.BLACK):
                locked.append(f"{chess.square_name(sq)}/{chess.square_name(ahead)}")
    tension: list[str] = []
    zone = chess.SquareSet(chess.BB_FILES[2] | chess.BB_FILES[3] | chess.BB_FILES[4] | chess.BB_FILES[5])
    for color in (chess.WHITE, chess.BLACK):
        for sq in chess.SquareSet(board.pieces_mask(chess.PAWN, color) & int(zone)):
            for t in board.attacks(sq):
                if _pawn_at(board, t, not color) and t in zone:
                    tension.append(f"{chess.square_name(sq)}x{chess.square_name(t)}")
    center_pawns = {c: [sq for sq in board.pieces(chess.PAWN, c) if chess.square_file(sq) in CENTER_FILES]
                    for c in (chess.WHITE, chess.BLACK)}
    n = len(center_pawns[chess.WHITE]) + len(center_pawns[chess.BLACK])
    if tension:
        return "dynamic", "tension " + ", ".join(sorted(set(tension))[:4])
    if len(locked) >= 1 and n - 2 * len(locked) <= 1:
        return "closed", "blocked pawns " + ", ".join(locked)
    if n == 0:
        return "open", "no d/e-pawns"
    for c in (chess.WHITE, chess.BLACK):
        mine = center_pawns[c]
        files = {chess.square_file(s) for s in mine if rel_rank(c, s) >= 4}
        if files == {3, 4} and not center_pawns[not c]:
            return "mobile", f"{CNAME[c]} pawns " + "+".join(chess.square_name(s) for s in mine)
        if files == {3, 4} and all(rel_rank(not c, s) <= 3 for s in center_pawns[not c]):
            return "mobile", f"{CNAME[c]} pawns " + "+".join(chess.square_name(s) for s in mine)
    if n <= 2 or len(center_pawns[chess.WHITE]) != len(center_pawns[chess.BLACK]):
        return "semi-open", (f"d/e-pawns: White {len(center_pawns[chess.WHITE])}, "
                             f"Black {len(center_pawns[chess.BLACK])}")
    return "semi-open", "fluid centre"


def chain_direction(board: chess.Board, color: chess.Color) -> str | None:
    """Which wing a locked pawn chain points to (the side to attack on), if any."""
    right = left = 0  # chain rising toward the h-file / a-file (from color's view)
    for sq in board.pieces(chess.PAWN, color):
        ahead = sq + _fwd(color)
        if not (0 <= ahead < 64 and _pawn_at(board, ahead, not color)):
            continue  # only blocked pawns form a locked chain head/link
        back = -_fwd(color)
        f = chess.square_file(sq)
        if f > 0 and _pawn_at(board, sq + back - 1, color):
            right += 1  # supported from the a-side behind -> chain rises toward h
        if f < 7 and _pawn_at(board, sq + back + 1, color):
            left += 1
    if right > left and right:
        return "kingside"
    if left > right and left:
        return "queenside"
    return None


def pawn_breaks(board: chess.Board, color: chess.Color, limit: int = 4) -> list[str]:
    """Pawn pushes that would attack an enemy pawn (levers), ignoring whose turn it is."""
    out = []
    fwd = _fwd(color)
    for sq in board.pieces(chess.PAWN, color):
        steps = [sq + fwd]
        if rel_rank(color, sq) == 2:
            steps.append(sq + 2 * fwd)
        for to in steps:
            if not 0 <= to < 64 or board.piece_at(to) is not None:
                break
            if rel_rank(color, to) >= 8:
                break
            f = chess.square_file(to)
            hits = []
            for df in (-1, 1):
                if 0 <= f + df < 8:
                    t = to + fwd + df
                    if 0 <= t < 64 and _pawn_at(board, t, not color):
                        hits.append(chess.square_name(t))
            if hits:
                out.append(f"{chess.square_name(to)} (hits {'+'.join(hits)})")
    return out[:limit]


def _space(board: chess.Board, color: chess.Color) -> int:
    """Squares in the opponent's half attacked by own pawns (+ own pawns standing there)."""
    enemy_half = chess.BB_RANK_5 | chess.BB_RANK_6 | chess.BB_RANK_7 if color == chess.WHITE else \
        chess.BB_RANK_4 | chess.BB_RANK_3 | chess.BB_RANK_2
    attacked = chess.SquareSet()
    for sq in board.pieces(chess.PAWN, color):
        attacked |= board.attacks(sq)
    return len(chess.SquareSet(int(attacked) & enemy_half)) + \
        chess.popcount(board.pieces_mask(chess.PAWN, color) & enemy_half)


def _undeveloped(board: chess.Board, color: chess.Color) -> int:
    rank = 0 if color == chess.WHITE else 7
    n = 0
    for f in (1, 2, 5, 6):
        p = board.piece_at(chess.square(f, rank))
        if p and p.color == color and p.piece_type in (chess.KNIGHT, chess.BISHOP):
            n += 1
    king = board.king(color)
    if king is not None and chess.square_file(king) == 4 and chess.square_rank(king) == rank:
        n += 1  # uncastled king still in the centre
    return n


def middlegame_character(board: chess.Board, tags: set[str]) -> list[str]:
    kind, detail = center_type(board)
    tags.add(f"centre-{kind}")
    out = [f"Type: {kind} centre ({detail}). {PLANS[kind]}"]
    if kind == "closed":
        for c in (chess.WHITE, chess.BLACK):
            d = chain_direction(board, c)
            if d:
                out.append(f"{CNAME[c]} pawn chain points to the {d} — {CNAME[c]}'s natural "
                           f"play is on the {d}.")
    for c in (chess.WHITE, chess.BLACK):
        br = pawn_breaks(board, c)
        if br:
            out.append(f"{CNAME[c]} pawn breaks available: {', '.join(br)}")
    wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
    if wk is not None and bk is not None:
        wf, bf = chess.square_file(wk), chess.square_file(bk)
        if (wf >= 5 and bf <= 2) or (wf <= 2 and bf >= 5):
            out.append("Kings on opposite wings: a race — throw pawns at the enemy king, "
                       "speed matters more than material.")
    return out


def imbalances(board: chess.Board, tags: set[str]) -> list[str]:
    out: list[str] = []
    kind, _ = center_type(board)
    closed = kind == "closed"
    pawns = chess.popcount(board.pawns)
    nb = {c: chess.popcount(board.pieces_mask(chess.BISHOP, c)) for c in (chess.WHITE, chess.BLACK)}
    nn = {c: chess.popcount(board.pieces_mask(chess.KNIGHT, c)) for c in (chess.WHITE, chess.BLACK)}
    for c in (chess.WHITE, chess.BLACK):
        o = not c
        if nb[c] > nb[o] and nn[o] > nn[c]:
            fav = ("favours the knight(s) (closed position)" if closed or pawns >= 14
                   else "favours the bishop(s) (open lines, pawns on both wings)")
            out.append(f"Minor pieces: {CNAME[c]} bishop(s) vs {CNAME[o]} knight(s) — the structure {fav}.")
    sw, sb = _space(board, chess.WHITE), _space(board, chess.BLACK)
    if abs(sw - sb) >= 3:
        big, small = (chess.WHITE, chess.BLACK) if sw > sb else (chess.BLACK, chess.WHITE)
        out.append(f"Space: {CNAME[big]} {max(sw, sb)} vs {CNAME[small]} {min(sw, sb)} (squares in the "
                   f"enemy half held by pawns) — {CNAME[big]} should avoid exchanges; "
                   f"{CNAME[small]} is cramped and benefits from trades and freeing breaks.")
        tags.add("space")
    uw, ub = _undeveloped(board, chess.WHITE), _undeveloped(board, chess.BLACK)
    if abs(uw - ub) >= 2 and board.fullmove_number <= 20:
        lead = chess.WHITE if uw < ub else chess.BLACK
        out.append(f"Development: {CNAME[lead]} leads by {abs(uw - ub)} tempi — open the "
                   f"position now before {CNAME[not lead]} catches up.")
        tags.add("development")
    return out
