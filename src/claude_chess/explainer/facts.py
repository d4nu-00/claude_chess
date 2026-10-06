"""Render one position's engine lines + verified concept facts as compact text.

The same block is the teacher's (Claude's) input and the student LM's input, so the student
learns to condense exactly what the teacher saw. Every line here is computed (Stockfish or
python-chess); nothing is LLM opinion.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import chess

from claude_chess.explainer import concepts as C

CN = {chess.WHITE: "White", chess.BLACK: "Black"}


@dataclass
class PositionFacts:
    fen: str
    best_line: list[str]  # UCI
    alt_line: list[str]
    value: float  # mover's win prob after the best move
    value_alt: float
    root: dict[str, float] = field(default_factory=dict)
    d_best: dict[str, float] = field(default_factory=dict)
    d_alt: dict[str, float] = field(default_factory=dict)
    sal: list[tuple[str, float, float]] = field(default_factory=list)
    f_best: dict[str, float] = field(default_factory=dict)
    f_alt: dict[str, float] = field(default_factory=dict)
    best_san: list[str] = field(default_factory=list)
    alt_san: list[str] = field(default_factory=list)


def compute(fen: str, best_line: list[str], alt_line: list[str], value: float, value_alt: float,
            scale: dict[str, float] | None = None, plies: int = 8) -> PositionFacts:
    b = chess.Board(fen)
    root = C.static(b)
    pov = b.turn
    d_best = C.delta(root, C.line_end_concepts(b, best_line, pov, plies))
    d_alt = C.delta(root, C.line_end_concepts(b, alt_line, pov, plies))
    _, best_san = C.play_line(b, best_line[:plies])
    _, alt_san = C.play_line(b, alt_line[:plies])
    return PositionFacts(
        fen=fen, best_line=best_line, alt_line=alt_line, value=value, value_alt=value_alt, root=root,
        d_best=d_best, d_alt=d_alt, sal=C.salience(d_best, d_alt, scale, top=5),
        f_best=C.move_facts(b, chess.Move.from_uci(best_line[0])),
        f_alt=C.move_facts(b, chess.Move.from_uci(alt_line[0])), best_san=best_san, alt_san=alt_san)


def numbered(board: chess.Board, sans: list[str]) -> str:
    out, n, white = [], board.fullmove_number, board.turn == chess.WHITE
    for i, s in enumerate(sans):
        if white:
            out.append(f"{n}.{s}")
        else:
            out.append(f"{n}...{s}" if i == 0 else s)
            n += 1
        white = not white
    return " ".join(out)


def eval_words(p_mover: float, mover: chess.Color) -> str:
    """'+1.3 (White is better)' from the mover's win probability."""
    p = min(max(p_mover, 1e-4), 1 - 1e-4)
    cp = math.log(p / (1 - p)) / 0.00368208
    cp_white = cp if mover == chess.WHITE else -cp
    a = abs(cp_white)
    side = "White" if cp_white > 0 else "Black"
    verdict = ("equal" if a < 50 else f"{side} is slightly better" if a < 150 else
               f"{side} is better" if a < 300 else f"{side} is winning")
    num = "mate" if p_mover > 0.999 or p_mover < 0.001 else f"{cp_white / 100:+.1f}"
    return f"{num} ({verdict})"


def ascii_board(board: chess.Board) -> str:
    rows = []
    for r in range(7, -1, -1):
        cells = []
        for f in range(8):
            p = board.piece_at(chess.square(f, r))
            cells.append(p.symbol() if p else ".")
        rows.append(f"{r + 1} " + " ".join(cells))
    rows.append("  a b c d e f g h")
    return "\n".join(rows)


PIECE_WORD = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
              chess.QUEEN: "queen", chess.KING: "king"}
_VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def piece_list(board: chess.Board) -> str:
    """Every piece in words-friendly SAN-ish form — a small LM can't decode a FEN."""
    out = []
    for c in (chess.WHITE, chess.BLACK):
        pcs = []
        for pt in (chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            pcs += [f"{chess.piece_symbol(pt).upper()}{chess.square_name(s)}" for s in sorted(board.pieces(pt, c))]
        pawns = [chess.square_name(s) for s in sorted(board.pieces(chess.PAWN, c))]
        out.append(f"{CN[c]}: {' '.join(pcs)}" + (f"; pawns {' '.join(pawns)}" if pawns else "; no pawns"))
    return ". ".join(out)


def _captured(board: chess.Board, mv: chess.Move) -> int | None:
    if board.is_en_passant(mv):
        return chess.PAWN
    return board.piece_type_at(mv.to_square) if board.is_capture(mv) else None


def annotated_line(board: chess.Board, uci_line: list[str], plies: int = 8) -> str:
    """Numbered SAN with what each capture takes: 1...fxg3(takes bishop) 2.O-O-O."""
    b = board.copy(stack=False)
    out, white = [], b.turn == chess.WHITE
    for i, u in enumerate(uci_line[:plies]):
        mv = chess.Move.from_uci(u)
        if not b.is_legal(mv):
            break
        cap = _captured(b, mv)
        san = b.san(mv) + (f"(takes {PIECE_WORD[cap]})" if cap else "")
        n = b.fullmove_number
        out.append(f"{n}.{san}" if white else (f"{n}...{san}" if i == 0 else san))
        b.push(mv)
        white = not white
    return " ".join(out)


def _targets_after(board: chess.Board, mv: chess.Move) -> list[str]:
    """Enemy pieces the moved piece attacks after the move that are worth hitting
    (king, a more valuable piece, or an undefended one)."""
    b = board.copy(stack=False)
    mover = b.turn
    pt = b.piece_type_at(mv.from_square)
    b.push(mv)
    out = []
    for sq in chess.scan_forward(b.attacks_mask(mv.to_square) & b.occupied_co[not mover]):
        tp = b.piece_type_at(sq)
        if tp == chess.KING or _VAL[tp] > _VAL[pt or chess.PAWN] or not b.attackers_mask(not mover, sq):
            out.append(f"{PIECE_WORD[tp]} {chess.square_name(sq)}")
    return out


def threats(board: chess.Board, limit: int = 3) -> list[str]:
    """Winning captures / mates for the side to move now, and for the opponent if it were their move."""
    from claude_chess.context.tactics import see

    def gains(b: chess.Board) -> list[str]:
        out = []
        for mv in b.legal_moves:
            if b.gives_check(mv):
                b.push(mv)
                mate = b.is_checkmate()
                b.pop()
                if mate:
                    out.append((100, f"{b.san(mv)} is mate"))
                    continue
            if b.is_capture(mv):
                s = see(b, mv)
                if s > 0:
                    out.append((s, f"{b.san(mv)} wins ~{s} (takes {PIECE_WORD[_captured(b, mv)]})"))
        return [x for _, x in sorted(out, key=lambda t: -t[0])[:limit]]

    us = board.turn
    lines = []
    ours = gains(board)
    lines.append(f"{CN[us]} can win material now: " + ("; ".join(ours) if ours else "nothing by force"))
    if not board.is_check():
        nb = board.copy(stack=False)
        nb.push(chess.Move.null())
        theirs = gains(nb)
        lines.append(f"{CN[not us]} threatens (if it were their move): " + ("; ".join(theirs) if theirs else "nothing"))
    else:
        lines.append(f"{CN[us]} is in check.")
    return lines


def _move_desc(board: chess.Board, uci: str, f: dict[str, float]) -> str:
    mv = chess.Move.from_uci(uci)
    pt = chess.piece_name(board.piece_type_at(mv.from_square) or chess.PAWN)
    bits = []
    if f.get("castle"):
        bits.append("castles")
    elif f.get("capture"):
        s = int(f.get("see", 0))
        cap = _captured(board, mv)
        bits.append(f"{pt} takes the {PIECE_WORD[cap or chess.PAWN]} on {chess.square_name(mv.to_square)}" +
                    (f" (exchange balance {s:+d})" if s else " (even trade)" if f.get("exchange") else ""))
    else:
        bits.append(f"quiet {pt} move to {chess.square_name(mv.to_square)}")
    hits = _targets_after(board, mv)
    if hits:
        bits.append("then attacks " + ", ".join(hits))
    for k, w in (("check", "check"), ("promotion", "promotes"), ("development", "develops"),
                 ("retreat", "retreats"), ("pawn_break", "pawn break (contacts an enemy pawn)")):
        if f.get(k):
            bits.append(w)
    if f.get("offers_material", 0) > 0:
        bits.append(f"leaves material en prise on the destination (~{int(f['offers_material'])})")
    if f.get("creates_threat", 0) > 0:
        bits.append(f"creates a new capture threat (~{int(f['creates_threat'])})")
    if f.get("parries_threat", 0) > 0:
        bits.append("parries a mate threat" if f["parries_threat"] >= 50 else
                    f"parries a threat (~{int(f['parries_threat'])})")
    return ", ".join(bits)


def imbalances(root: dict[str, float], limit: int = 6) -> list[str]:
    out = []
    for k in C.SIDE_KEYS:
        u, t = root[f"us.{k}"], root[f"them.{k}"]
        if u == t or k in ("queen_present", "material", "mobility", "pawn_islands"):
            continue
        spec = C.spec(f"us.{k}")
        if spec.valence == 0 and not (u or t):
            continue
        out.append((abs(u - t) * C.priority(f"us.{k}"), f"{spec.name}: us {u:g}, them {t:g}"))
    out.sort(key=lambda x: -x[0])
    lines = [s for _, s in out[:limit]]
    for k in ("opposite_bishops", "opposite_castling"):
        if root.get(f"g.{k}"):
            lines.append(C.spec(f"g.{k}").name)
    return lines


def render(pf: PositionFacts, board_diagram: bool = True) -> str:
    b = chess.Board(pf.fen)
    us = b.turn
    mat = pf.root["us.material"] - pf.root["them.material"]
    lines = [f"Position: {CN[us]} to move. FEN: {pf.fen}"]
    if board_diagram:
        lines += [ascii_board(b)]
    else:  # the student can't read a FEN: spell the pieces out
        lines += [f"Pieces: {piece_list(b)}."]
    lines += [
        f"Material: {'equal' if mat == 0 else (CN[us] if mat > 0 else CN[not us]) + f' is up {abs(mat):g}'} "
        f"(pawn units). Phase: {pf.root['g.phase']:.2f} of non-pawn material left.",
        "",
        "Engine (Stockfish, deep search):",
        f"- BEST {pf.best_san[0]}: {annotated_line(b, pf.best_line)}  -> {eval_words(pf.value, us)}",
        f"- ALTERNATIVE {pf.alt_san[0]}: {annotated_line(b, pf.alt_line)}  -> {eval_words(pf.value_alt, us)}",
        f"- Win-chance cost of the alternative for {CN[us]}: {100 * (pf.value - pf.value_alt):.0f} points (of 100)",
        "",
        f"Best move {pf.best_san[0]}: {_move_desc(b, pf.best_line[0], pf.f_best)}.",
        f"Alternative {pf.alt_san[0]}: {_move_desc(b, pf.alt_line[0], pf.f_alt)}.",
        "",
    ] + threats(b)
    imb = imbalances(pf.root)
    if imb:
        lines += ["", f"Imbalances now (us = {CN[us]}):"] + [f"- {x}" for x in imb]
    if pf.sal:
        lines += ["", "Verified concept changes, best line vs alternative (after up to 8 plies, us = "
                  f"{CN[us]}):"]
        for key, _z, good in pf.sal:
            r = pf.root.get(key, 0.0)
            tag = " [favours best]" if good > 0 else " [favours alternative]" if good < 0 else ""
            lines.append(f"- {C.describe(key)}: now {r:g}; after best {r + pf.d_best[key]:g}; "
                         f"after alternative {r + pf.d_alt[key]:g}{tag}")
    return "\n".join(lines)


def from_record(rec: dict, scale: dict[str, float] | None = None) -> PositionFacts:
    """Build facts from a featurized record (data.py fields)."""
    return compute(rec["fen"], rec["best_line"].split(), rec["alt_line"].split(), float(rec["value"]),
                   float(rec["value_alt"]), scale)


def moves_list(rec: dict) -> list[tuple[str, float]]:
    return [(u, float(w)) for u, w in json.loads(rec["moves"])]
