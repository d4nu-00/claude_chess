"""Endgame classification + textbook K+P knowledge + tablebase lookup.

Endings are where "knowing" beats "calculating": the type of ending sets the plan
(rook behind the passer, opposite bishops draw, ...), pure pawn endings follow exact
geometric rules (rule of the square, opposition, key squares), and ≤7-piece positions are
simply looked up (tablebase.py).
"""

from __future__ import annotations

import chess

from .features import CNAME, SYMBOL, _sq_color, is_passed, rel_rank
from .tablebase import probe

GUIDE = {
    "pawn": ("Pawn ending: every tempo counts — activate the king first, count moves to "
             "promotion for both sides, use the opposition, create an outside passed pawn "
             "to deflect the enemy king."),
    "rook": ("Rook ending: activity beats material — rooks belong BEHIND passed pawns (own "
             "and enemy); cut the enemy king off; know Lucena (build a bridge) and Philidor "
             "(rook on the 3rd rank, then check from behind)."),
    "opposite-bishops": ("Opposite-coloured bishops: very drawish — the defender blockades on "
                         "his bishop's colour; the attacker needs two passers far apart."),
    "same-bishops": ("Same-coloured bishops: put your pawns on the opposite colour to your "
                     "bishop; attack pawns fixed on your bishop's colour."),
    "bishop-knight": ("Bishop vs knight: the bishop wants pawns on both wings and an open "
                      "board; the knight wants a closed, one-wing position and outposts."),
    "knight": ("Knight ending: like a pawn ending — king activity and outside passed pawns "
               "decide; knights struggle against rook pawns."),
    "queen": ("Queen ending: king safety and perpetual check dominate — shelter your king, "
              "centralise the queen, a far-advanced passer is worth a lot."),
    "mixed": ("Mixed ending: the side ahead in material should trade PIECES not pawns; the "
              "defender trades pawns and seeks a fortress."),
}


def _pieces(board: chess.Board, color: chess.Color) -> str:
    s = "K"
    for pt in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN):
        s += SYMBOL[pt] * chess.popcount(board.pieces_mask(pt, color))
    return s


def classify(board: chess.Board) -> str:
    q, r = board.queens, board.rooks
    b, n = board.bishops, board.knights
    if not (q | r | b | n):
        return "pawn"
    if r and not (q | b | n):
        return "rook"
    if q and not (r | b | n):
        return "queen"
    if b and not (q | r | n):
        wb = board.pieces(chess.BISHOP, chess.WHITE)
        bb = board.pieces(chess.BISHOP, chess.BLACK)
        if len(wb) == 1 and len(bb) == 1:
            return ("opposite-bishops" if _sq_color(next(iter(wb))) != _sq_color(next(iter(bb)))
                    else "same-bishops")
        return "mixed"
    if n and not (q | r | b):
        return "knight"
    if (b | n) and not (q | r):
        return "bishop-knight"
    return "mixed"


def _promo_square(color: chess.Color, sq: int) -> int:
    return chess.square(chess.square_file(sq), 7 if color == chess.WHITE else 0)


def _moves_to_promote(color: chess.Color, sq: int) -> int:
    r = rel_rank(color, sq)
    return 8 - r - (1 if r == 2 else 0)


def key_squares(color: chess.Color, sq: int) -> list[int]:
    """Key squares of a pawn (K+P vs K theory): the attacking king on one of them wins."""
    f, r = chess.square_file(sq), rel_rank(color, sq)
    up = 1 if color == chess.WHITE else -1
    rank0 = chess.square_rank(sq)
    if f in (0, 7):  # rook pawn: the two squares on the adjacent file in front of promotion
        af = 1 if f == 0 else 6
        return [chess.square(af, 6 if color == chess.WHITE else 1), chess.square(af, 7 if color == chess.WHITE else 0)]
    ranks = [rank0 + 2 * up] if r <= 4 else [rank0 + up, rank0 + 2 * up]
    out = []
    for rr in ranks:
        if 0 <= rr < 8:
            out += [chess.square(ff, rr) for ff in (f - 1, f, f + 1) if 0 <= ff < 8]
    return out


def pawn_ending_facts(board: chess.Board) -> list[str]:
    out = []
    kings = {c: board.king(c) for c in (chess.WHITE, chess.BLACK)}
    if None in kings.values():
        return out
    for c in (chess.WHITE, chess.BLACK):
        o = not c
        passers = [sq for sq in board.pieces(chess.PAWN, c) if is_passed(board, c, sq)]
        for sq in passers:
            n = _moves_to_promote(c, sq)
            d = chess.square_distance(kings[o], _promo_square(c, sq))
            reach = n if board.turn == o else n - 1
            name = chess.square_name(sq)
            if d > reach:
                out.append(f"{CNAME[c]} passed pawn {name}: OUTSIDE the square — the {CNAME[o]} king "
                           f"cannot catch it (pawn needs {n}, king {d} moves).")
            else:
                out.append(f"{CNAME[c]} passed pawn {name}: the {CNAME[o]} king is inside its square "
                           f"(pawn needs {n}, king {d} moves).")
            ks = key_squares(c, sq)
            if kings[c] in ks:
                out.append(f"{CNAME[c]} king on key square {chess.square_name(kings[c])} of the {name}-pawn "
                           f"— winning in K+P vs K if the pawn is safe.")
            else:
                out.append(f"Key squares of the {name}-pawn: {', '.join(chess.square_name(k) for k in ks)} "
                           f"({CNAME[c]} king wants to reach one; {CNAME[o]} king must keep it out).")
            others = [s for s in chess.SquareSet(board.pawns) if s != sq]
            if len(others) >= 2 and min(abs(chess.square_file(s) - chess.square_file(sq)) for s in others) >= 3:
                out.append(f"{CNAME[c]} {name} is an OUTSIDE passed pawn — use it as a decoy.")
    wk, bk = kings[chess.WHITE], kings[chess.BLACK]
    fd = abs(chess.square_file(wk) - chess.square_file(bk))
    rd = abs(chess.square_rank(wk) - chess.square_rank(bk))
    if (fd == 0 and rd % 2 == 0) or (rd == 0 and fd % 2 == 0) or (fd == rd and fd % 2 == 0):
        holder = not board.turn  # the side that just moved (NOT to move) holds the opposition
        straight = fd == 0 or rd == 0
        kind = ("direct" if max(fd, rd) == 2 else "distant") if straight else "diagonal"
        out.append(f"Kings in {kind} opposition — {CNAME[holder]} has the opposition "
                   f"({CNAME[board.turn]} to move must give way).")
    return out


def endgame_info(board: chess.Board, tags: set[str]) -> list[str]:
    kind = classify(board)
    tags.add(f"eg-{kind}")
    sig = f"{_pieces(board, chess.WHITE)} vs {_pieces(board, chess.BLACK)}"
    out = [f"Type: {kind.replace('-', ' ')} ending ({sig}). {GUIDE[kind]}"]
    tb = probe(board)
    if tb is not None:
        side = CNAME[board.turn]
        best = tb.best_moves()
        line = f"TABLEBASE ({tb.source}, exact): {tb.verdict} for {side} (side to move)"
        if best:
            what = {2: "winning", 1: "best", 0: "drawing", -1: "best", -2: "longest-resisting"}[tb.wdl]
            line += f"; {what} moves: {', '.join(best[:6])}"
        out.append(line)
        tags.add("tablebase")
    if kind == "pawn":
        out += pawn_ending_facts(board)
    else:
        # Passed pawns racing a lone king still obey the rule of the square.
        for c in (chess.WHITE, chess.BLACK):
            if not board.occupied_co[not c] & ~board.kings & ~board.pawns:
                out += [f for f in pawn_ending_facts(board) if f.startswith(CNAME[c]) and "square" in f]
    for c in (chess.WHITE, chess.BLACK):
        mine = board.occupied_co[c] & ~board.kings
        if not board.pieces(chess.PAWN, c) and chess.popcount(mine) == 1 and \
                (board.knights | board.bishops) & mine:
            out.append(f"{CNAME[c]} has a lone minor piece and no pawns: cannot win.")
    return out
