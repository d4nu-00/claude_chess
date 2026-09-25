"""Material-only tactical search: alpha-beta + quiescence on a real board (python-chess).

Classic engine machinery, deliberately *without* positional knowledge: it only answers
"what happens to the material (and the king) if both sides play the forcing moves?".
Claude still supplies the chess understanding (candidate moves + positional judgement);
this layer covers the part LLMs are worst at — counting exchanges, seeing that a move
hangs a piece or allows mate. See wiki/pages/computer-chess-principles.md.

Scores are centipawns from the SIDE TO MOVE's view (negamax), mate = ±(MATE_CP - ply).
No Stockfish anywhere (wiki/pages/decisions.md).

NOTE — material is not the only thing that matters. This search counts pieces, so a real
sacrifice (material given up for an attack on the king, the initiative, a passed pawn,
a lasting bind) looks like a plain loss here. That is a *blind spot of this module*, not
a verdict: when Claude proposes a move as a sacrifice and names the compensation, the
hybrid player exempts it from the material veto and lets Claude's positional judgement
award compensation (up to the material given) — see ClaudeEnginePlayer._veto/_compare.
Only a verified forced mate against the mover still vetoes a declared sacrifice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

MATE_CP = 10000
MATE_BAND = MATE_CP - 1000  # |score| above this means a forced mate was found
VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500,
          chess.QUEEN: 900, chess.KING: 0}
MAX_QDEPTH = 8
MAX_EXT_PLY = 6  # no check extensions beyond this ply (keeps perpetual-check lines bounded)  # capture sequences longer than this are cut (stand-pat)


def material(board: chess.Board) -> int:
    """Material balance from WHITE's view."""
    s = 0
    for pt, v in VALUES.items():
        s += v * (len(board.pieces(pt, chess.WHITE)) - len(board.pieces(pt, chess.BLACK)))
    return s


def _stm_material(board: chess.Board) -> int:
    m = material(board)
    return m if board.turn == chess.WHITE else -m


def _mvv_lva(board: chess.Board, mv: chess.Move) -> int:
    victim = VALUES[chess.PAWN] if board.is_en_passant(mv) else VALUES.get(board.piece_type_at(mv.to_square) or 0, 0)
    attacker = VALUES.get(board.piece_type_at(mv.from_square) or 0, 0)
    promo = VALUES[mv.promotion] if mv.promotion else 0
    return 10 * (victim + promo) - attacker


@dataclass
class TacticalSearch:
    """Negamax alpha-beta (full width to `depth`) + captures-only quiescence.

    `nodes` counts visited positions so callers can budget; `node_limit` is a soft cap
    after which the search stops expanding and falls back to static material.
    """

    node_limit: int = 200_000
    nodes: int = 0
    _tt: dict = field(default_factory=dict)

    # quiescence -----------------------------------------------------------

    def qsearch(self, board: chess.Board, alpha: int, beta: int, ply: int, qdepth: int = 0) -> int:
        self.nodes += 1
        in_check = board.is_check()
        if in_check:
            # Check evasion: every legal move must be tried (stand-pat is not allowed in check).
            moves = list(board.legal_moves)
            if not moves:
                return -(MATE_CP - ply)
            if qdepth >= MAX_QDEPTH or self.nodes > self.node_limit:
                return _stm_material(board)
            best = -MATE_CP
            for mv in sorted(moves, key=lambda m: -_mvv_lva(board, m) if board.is_capture(m) else 0):
                board.push(mv)
                sc = -self.qsearch(board, -beta, -alpha, ply + 1, qdepth + 1)
                board.pop()
                if sc > best:
                    best = sc
                if sc > alpha:
                    alpha = sc
                if alpha >= beta:
                    break
            return best
        stand = _stm_material(board)
        if stand >= beta or qdepth >= MAX_QDEPTH or self.nodes > self.node_limit:
            return stand
        alpha = max(alpha, stand)
        caps = [m for m in board.generate_legal_captures()]
        caps += [m for m in board.generate_legal_moves(board.pawns & board.occupied_co[board.turn])
                 if m.promotion == chess.QUEEN and not board.is_capture(m)]
        caps.sort(key=lambda m: -_mvv_lva(board, m))
        for mv in caps:
            board.push(mv)
            sc = -self.qsearch(board, -beta, -alpha, ply + 1, qdepth + 1)
            board.pop()
            if sc >= beta:
                return sc
            if sc > alpha:
                alpha = sc
        return alpha

    # full-width -----------------------------------------------------------

    def search(self, board: chess.Board, depth: int, alpha: int = -MATE_CP - 1,
               beta: int = MATE_CP + 1, ply: int = 0) -> int:
        """Negamax score from the side to move's view."""
        if ply > 0 and (board.is_repetition(2) or board.halfmove_clock >= 100):
            return 0  # repetition inside the tree = draw (cheap stand-in for can_claim_draw)
        moves = list(board.legal_moves)
        if not moves:
            return -(MATE_CP - ply) if board.is_check() else 0
        if board.is_check() and 0 < depth and ply < MAX_EXT_PLY:
            depth += 1  # check extension: forcing sequences are searched a ply deeper
        if depth <= 0 or self.nodes > self.node_limit:
            return self.qsearch(board, alpha, beta, ply)
        self.nodes += 1
        key = (board._transposition_key(), depth)
        hit = self._tt.get(key)  # used for move ordering only (no bound-based cutoffs)
        tt_move = hit[1] if hit else None

        def order(m: chess.Move) -> int:
            if m == tt_move:
                return 1_000_000
            if board.is_capture(m):
                return 10_000 + _mvv_lva(board, m)
            if m.promotion:
                return 9_000
            return 0

        moves.sort(key=order, reverse=True)
        best, best_mv = -MATE_CP - 1, None
        for mv in moves:
            board.push(mv)
            sc = -self.search(board, depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            if sc > best:
                best, best_mv = sc, mv
            if sc > alpha:
                alpha = sc
            if alpha >= beta:
                break
        self._tt[key] = (best, best_mv)
        return best

    def principal_reply(self, board: chess.Board, depth: int) -> tuple[chess.Move | None, int]:
        """Best move for the side to move (full width), and its score."""
        best, best_mv = -MATE_CP - 1, None
        for mv in board.legal_moves:
            board.push(mv)
            sc = -self.search(board, depth - 1, -MATE_CP - 1, -best, 1)
            board.pop()
            if sc > best:
                best, best_mv = sc, mv
        return best_mv, best


@dataclass
class MoveVerdict:
    move: chess.Move
    score: int  # material outcome after the forcing play, mover's view, relative to now
    refutation: str = ""  # opponent's best reply (SAN) found by the search, if any
    mate: int = 0  # >0: we mate in N plies; <0: we get mated in N plies


def score_moves(board: chess.Board, moves: list[chess.Move], depth: int = 2,
                node_limit: int = 60_000) -> list[MoveVerdict]:
    """Tactical verdict for each root move: play it, then search `depth` plies full width
    (opponent first) + quiescence. `score` is the material swing for the mover (0 = keeps
    material level with the current position), or ±MATE-ish for forced mates.
    """
    base = _stm_material(board)
    out: list[MoveVerdict] = []
    ts = TacticalSearch(node_limit=node_limit)
    for mv in moves:
        ts.nodes = 0
        b = board.copy(stack=True)
        b.push(mv)
        if b.is_checkmate():
            out.append(MoveVerdict(mv, MATE_CP - 1, mate=1))
            continue
        reply, reply_sc = ts.principal_reply(b, depth) if depth > 0 else (None, ts.qsearch(b, -MATE_CP - 1, MATE_CP + 1, 1))
        if reply is None and depth > 0:  # stalemate / no replies
            sc = 0
        else:
            sc = -reply_sc
        mate = 0
        if sc > MATE_BAND:
            mate = MATE_CP - sc
            rel = sc
        elif sc < -MATE_BAND:
            mate = -(MATE_CP + sc)
            rel = sc
        else:
            rel = sc - base
        out.append(MoveVerdict(mv, rel, refutation=b.san(reply) if reply is not None else "", mate=mate))
    return out


def forcing_moves(board: chess.Board) -> list[chess.Move]:
    """Checks, captures and queen promotions — the moves engines never prune."""
    return [m for m in board.legal_moves
            if board.is_capture(m) or m.promotion == chess.QUEEN or board.gives_check(m)]
