"""Board-vision probe: Claude states where it thinks the pieces are and what is attacked;
python-chess scores that against the real board.

Two uses: (1) diagnostics — does a blunder coincide with a misread board or a missed
threat? (2) a "look before you move" step: writing out the position before proposing is a
cheap form of chain-of-thought aimed at the LLM's known weakness (board state tracking).
See wiki/pages/board-vision.md.
"""

from __future__ import annotations

import re

import chess

from claude_chess.engine import tactical

INSTRUCTION = """
Before choosing, READ THE BOARD and add these keys to your JSON object:
"board": {"white": ["Kg1", "Qd1", "Pe4", ...], "black": [...]}  (every piece: letter K/Q/R/B/N/P + square),
"threats": ["<SAN moves the OPPONENT could play next that would win material or mate if it were their turn>"],
"hanging": ["<squares of YOUR pieces that the opponent can win>"]"""

_TOKEN = re.compile(r"([KQRBNPkqrbnp]?)\s*([a-h][1-8])")


def _true_pieces(board: chess.Board, color: chess.Color) -> set[str]:
    return {chess.piece_symbol(p.piece_type).upper() + chess.square_name(sq)
            for sq, p in board.piece_map().items() if p.color == color}


def _claimed_pieces(items) -> set[str]:
    if isinstance(items, str):
        items = re.split(r"[,\s]+", items)
    out = set()
    for it in items or []:
        m = _TOKEN.search(str(it))
        if m:
            out.add((m.group(1).upper() or "P") + m.group(2))
    return out


def real_threats(board: chess.Board) -> list[str]:
    """Opponent moves that win material (SEE-free: via the tactical search) or mate,
    computed as if the opponent were to move (null move)."""
    if board.is_check():
        return []
    nb = board.copy(stack=False)
    nb.push(chess.Move.null())
    cands = tactical.forcing_moves(nb)
    out = []
    for v in tactical.score_moves(nb, cands, depth=1, node_limit=5_000):
        if v.mate > 0 or v.score >= 100:
            out.append(nb.san(v.move))
    return out


def real_hanging(board: chess.Board) -> list[str]:
    """Squares of the side-to-move's pieces the opponent could win (from real_threats)."""
    if board.is_check():
        return []
    nb = board.copy(stack=False)
    nb.push(chess.Move.null())
    sqs = set()
    for san in real_threats(board):
        mv = nb.parse_san(san)
        if nb.is_capture(mv) and nb.piece_at(mv.to_square) is not None:
            sqs.add(chess.square_name(mv.to_square))
    return sorted(sqs)


def score(board: chess.Board, data: dict) -> dict:
    """Compare Claude's reported position with the truth. Board = position Claude saw."""
    out: dict = {}
    claimed_board = data.get("board")
    if isinstance(claimed_board, dict):
        total = correct = 0
        missing: list[str] = []
        phantom: list[str] = []
        for color, key in ((chess.WHITE, "white"), (chess.BLACK, "black")):
            truth = _true_pieces(board, color)
            claim = _claimed_pieces(claimed_board.get(key))
            total += len(truth)
            correct += len(truth & claim)
            missing += sorted(truth - claim)
            phantom += sorted(claim - truth)
        out.update(pieces_total=total, pieces_correct=correct,
                   piece_accuracy=round(correct / total, 3) if total else None,
                   missing=missing, phantom=phantom)
    truth_threats = real_threats(board)
    if "threats" in data:
        claimed = {str(t).strip().rstrip("+#") for t in (data.get("threats") or [])}
        real = {t.rstrip("+#") for t in truth_threats}
        out.update(threats_real=truth_threats, threats_claimed=sorted(claimed),
                   threats_seen=sorted(real & claimed), threats_missed=sorted(real - claimed))
    if "hanging" in data:
        claimed_h = {m.group(2) for h in (data.get("hanging") or []) if (m := _TOKEN.search(str(h)))}
        real_h = set(real_hanging(board))
        out.update(hanging_real=sorted(real_h), hanging_claimed=sorted(claimed_h),
                   hanging_missed=sorted(real_h - claimed_h))
    return out
