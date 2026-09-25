"""Named tactical motifs, detected on the real board (context v4).

LLMs miss tactics mostly because they don't *see* the geometry; naming it helps. Pure
python-chess, no engine: each detector reports the pattern in plain chess words (pin, fork,
skewer, discovered attack, overloaded defender, weak back rank, trapped piece) for BOTH
sides — what the side to move can do now, and what the opponent would threaten if it were
their move. It never says whether a motif actually wins material: that is the tactical
search's and Claude's job.
"""

from __future__ import annotations

import chess

from .tactics import see

V = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)
CN = {chess.WHITE: "White", chess.BLACK: "Black"}


def _nm(board: chess.Board, sq: int) -> str:
    p = board.piece_at(sq)
    return f"{p.symbol().upper() if p.piece_type != chess.PAWN else ''}{chess.square_name(sq)}" if p else "?"


def _ray_beyond(frm: int, via: int) -> list[int]:
    """Squares beyond `via` on the line frm→via (empty if not on a line)."""
    fr, ff = divmod(frm, 8)
    vr, vf = divmod(via, 8)
    dr, df = vr - fr, vf - ff
    if not (dr == 0 or df == 0 or abs(dr) == abs(df)):
        return []
    sr, sf = (dr > 0) - (dr < 0), (df > 0) - (df < 0)
    out, r, f = [], vr + sr, vf + sf
    while 0 <= r < 8 and 0 <= f < 8:
        out.append(r * 8 + f)
        r, f = r + sr, f + sf
    return out


def _slides_along(pt: int, frm: int, to: int) -> bool:
    fr, ff = divmod(frm, 8)
    tr, tf = divmod(to, 8)
    straight = fr == tr or ff == tf
    return pt == chess.QUEEN or (pt == chess.ROOK and straight) or (pt == chess.BISHOP and not straight)


def _first_behind(board: chess.Board, frm: int, via: int) -> int | None:
    for sq in _ray_beyond(frm, via):
        if board.piece_at(sq):
            return sq
    return None


def pins_and_skewers(board: chess.Board, attacker: chess.Color) -> list[str]:
    """Lines where `attacker`'s slider hits an enemy piece with another enemy piece behind it."""
    out = []
    for sq in board.pieces(chess.BISHOP, attacker) | board.pieces(chess.ROOK, attacker) | \
            board.pieces(chess.QUEEN, attacker):
        pt = board.piece_type_at(sq)
        for front in board.attacks(sq):
            fp = board.piece_at(front)
            if not fp or fp.color == attacker:
                continue
            back = _first_behind(board, sq, front)
            if back is None or not _slides_along(pt, sq, back):
                continue
            bp = board.piece_at(back)
            if not bp or bp.color == attacker:
                continue
            if V[bp.piece_type] > V[fp.piece_type]:
                # relative pins matter only if what's behind is big (K/Q/R) or hangs
                if bp.piece_type not in (chess.KING, chess.QUEEN, chess.ROOK) and board.attackers(not attacker, back):
                    continue
                kind = "pinned to the king" if bp.piece_type == chess.KING else f"pinned to {_nm(board, back)}"
                out.append(f"{CN[not attacker]} {_nm(board, front)} is {kind} by {_nm(board, sq)} (pin)")
            elif V[fp.piece_type] > V[bp.piece_type] and fp.piece_type != chess.PAWN:
                out.append(f"{_nm(board, sq)} skewers {CN[not attacker]} {_nm(board, front)} "
                           f"with {_nm(board, back)} behind (skewer)")
    return out


def _targets(board: chess.Board, sq: int, color: chess.Color) -> list[int]:
    """Enemy pieces attacked from `sq` worth hitting: the king, more valuable pieces, or
    undefended ones."""
    p = board.piece_at(sq)
    out = []
    for t in board.attacks(sq):
        tp = board.piece_at(t)
        if not tp or tp.color == color:
            continue
        if tp.piece_type == chess.KING or V[tp.piece_type] > V[p.piece_type] or \
                not board.attackers(not color, t):
            out.append(t)
    return out


def _safe_on(board: chess.Board, sq: int, color: chess.Color) -> bool:
    """The `color` piece on `sq` can't be taken for free or by a cheaper piece."""
    enemies = board.attackers(not color, sq)
    if not enemies:
        return True
    v = V[board.piece_type_at(sq)]
    if any(V[board.piece_type_at(a)] < v for a in enemies):
        return False
    return bool(board.attackers(color, sq))


def forks(board: chess.Board, limit: int = 3) -> list[str]:
    """Moves for the side to move that hit two or more worthwhile targets from a square the
    moving piece can't simply lose (SEE >= 0 for the move)."""
    us = board.turn
    found = []
    for mv in board.legal_moves:
        if see(board, mv) < 0:
            continue
        b = board.copy(stack=False)
        b.push(mv)
        if not _safe_on(b, mv.to_square, us):  # a fork the opponent can just capture isn't one
            continue
        tg = _targets(b, mv.to_square, us)
        if len(tg) >= 2:
            names = " and ".join(_nm(b, t) for t in sorted(tg, key=lambda t: -V[b.piece_type_at(t)])[:3])
            score = sum(V[b.piece_type_at(t)] for t in tg)
            found.append((score, f"{board.san(mv)} forks {names} (fork)"))
    found.sort(key=lambda t: -t[0])
    return [f for _, f in found[:limit]]


def discovered(board: chess.Board, limit: int = 2) -> list[str]:
    """Own piece standing between an own slider and an enemy king/valuable piece: moving it
    discovers an attack (check if the target is the king)."""
    us = board.turn
    out = []
    for sq in board.pieces(chess.BISHOP, us) | board.pieces(chess.ROOK, us) | board.pieces(chess.QUEEN, us):
        pt = board.piece_type_at(sq)
        for blocker in board.attacks(sq):
            bp = board.piece_at(blocker)
            if not bp or bp.color != us:
                continue
            tgt = _first_behind(board, sq, blocker)
            if tgt is None or not _slides_along(pt, sq, tgt):
                continue
            tp = board.piece_at(tgt)
            if not tp or tp.color == us or not (tp.piece_type == chess.KING or V[tp.piece_type] > V[pt]):
                continue
            if not any(m.from_square == blocker for m in board.legal_moves):
                continue
            what = "discovered check" if tp.piece_type == chess.KING else f"discovered attack on {_nm(board, tgt)}"
            out.append(f"moving {_nm(board, blocker)} unmasks {_nm(board, sq)}: {what}")
    return out[:limit]


def overloaded(board: chess.Board, defender_color: chess.Color) -> list[str]:
    """A `defender_color` piece that is the ONLY defender of two or more attacked pieces."""
    duty: dict[int, list[int]] = {}
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.color != defender_color or p.piece_type == chess.KING:
            continue
        if not board.attackers(not defender_color, sq):
            continue
        defs = list(board.attackers(defender_color, sq))
        if len(defs) == 1:
            duty.setdefault(defs[0], []).append(sq)
    return [f"{CN[defender_color]} {_nm(board, d)} is overloaded: sole defender of "
            f"{', '.join(_nm(board, s) for s in sqs)}" for d, sqs in duty.items() if len(sqs) >= 2]


def back_rank(board: chess.Board, color: chess.Color) -> list[str]:
    """King on its back rank with no flight square off it, and enemy heavy pieces on the board."""
    k = board.king(color)
    home = 0 if color == chess.WHITE else 7
    if k is None or chess.square_rank(k) != home:
        return []
    if not (board.pieces(chess.ROOK, not color) | board.pieces(chess.QUEEN, not color)):
        return []
    for sq in board.attacks(k):
        if chess.square_rank(sq) != home and not board.piece_at(sq) and not board.attackers(not color, sq):
            return []
    return [f"{CN[color]}'s back rank is weak (king on the back rank, no flight square)"]


def trapped(board: chess.Board, color: chess.Color) -> list[str]:
    """Developed minor/major pieces of `color` that are attacked and have no safe square."""
    out = []
    b = board.copy(stack=False)
    b.turn = color
    b.ep_square = None
    for sq in chess.SQUARES:
        p = b.piece_at(sq)
        if not p or p.color != color or p.piece_type in (chess.PAWN, chess.KING):
            continue
        if not b.attackers(not color, sq):
            continue
        moves = [m for m in b.legal_moves if m.from_square == sq]
        if moves and all(see(b, m) < 0 for m in moves):
            out.append(f"{CN[color]} {_nm(b, sq)} is attacked and has no safe square (trapped)")
        elif not moves and not b.is_check():
            out.append(f"{CN[color]} {_nm(b, sq)} is attacked and cannot move (trapped)")
    return out


def motifs(board: chess.Board) -> list[str]:
    """Plain-words motif lines: side to move's chances first, then the opponent's."""
    us, them = board.turn, not board.turn
    ours = forks(board) + pins_and_skewers(board, us) + discovered(board) + overloaded(board, them) + \
        back_rank(board, them) + trapped(board, them)
    theirs: list[str] = pins_and_skewers(board, them) + overloaded(board, us) + back_rank(board, us) + trapped(board, us)
    if not board.is_check():
        nb = board.copy(stack=False)
        nb.push(chess.Move.null())
        theirs = [f"(if it were {CN[them]}'s move) {x}" for x in forks(nb, limit=2) + discovered(nb, limit=1)] + theirs
    lines = [f"{CN[us]} to move: {x}" for x in ours] + [f"Against {CN[us]}: {x}" for x in theirs]
    return lines
