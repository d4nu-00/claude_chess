"""Human chess concepts as numbers: static concepts per side, move facts, line deltas, salience.

Everything is side-relative. `static(board, pov)` returns `us.*` (the `pov` side), `them.*`
and `g.*` (global) values, so a line delta reads "what the moving side gained or lost".

The explanation signal is *contrastive* (the programmatic version of Schut et al.'s
chosen-vs-rejected rollouts): `salience(...)` = Δconcepts along the best line minus
Δconcepts along the alternative line, scaled per concept. Large entries are what the best
move achieves that the alternative doesn't — the raw material for a condensed idea.

Pure python-chess, no engine. Speed matters (millions of boards): bitboards where possible.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from claude_chess.context.motifs import back_rank, discovered, forks, overloaded, pins_and_skewers, trapped
from claude_chess.context.tactics import see

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
_NOT_A = ~chess.BB_FILE_A & chess.BB_ALL
_NOT_H = ~chess.BB_FILE_H & chess.BB_ALL
_CENTER16 = 0
for _f in range(2, 6):
    for _r in range(2, 6):
        _CENTER16 |= chess.BB_SQUARES[chess.square(_f, _r)]
_LIGHT = chess.BB_LIGHT_SQUARES


# ── concept registry ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Spec:
    key: str
    name: str  # human words, used in rendered facts
    valence: int  # +1 more is good for the owner, -1 bad, 0 neutral/dual


SIDE: tuple[Spec, ...] = (
    Spec("material", "material (pawns)", +1),
    Spec("bishop_pair", "bishop pair", +1),
    Spec("passed_pawns", "passed pawns", +1),
    Spec("passer_rank", "most advanced passed pawn (rank)", +1),
    Spec("protected_passers", "protected passed pawns", +1),
    Spec("connected_passers", "connected passed pawns", +1),
    Spec("isolated_pawns", "isolated pawns", -1),
    Spec("doubled_pawns", "doubled pawns", -1),
    Spec("backward_pawns", "backward pawns", -1),
    Spec("pawn_islands", "pawn islands", -1),
    Spec("iqp", "isolated queen pawn", 0),
    Spec("hanging_pawns", "hanging pawns (c+d)", 0),
    Spec("majority_qs", "queenside pawn majority", +1),
    Spec("majority_ks", "kingside pawn majority", +1),
    Spec("space", "space", +1),
    Spec("king_shield", "king's pawn shield", +1),
    Spec("king_open_files", "open files next to the king", -1),
    Spec("king_zone_attacks", "attacks on the king zone", -1),
    Spec("king_attackers", "enemy pieces aiming at the king", -1),
    Spec("king_escape", "king flight squares", +1),
    Spec("back_rank_weak", "weak back rank", -1),
    Spec("castled", "king tucked in a corner", +1),
    Spec("king_center", "king stuck in the centre", -1),
    Spec("king_activity", "active king (endgame)", +1),
    Spec("mobility", "piece mobility", +1),
    Spec("outposts", "pieces on outposts", +1),
    Spec("bad_bishop", "bad bishops", -1),
    Spec("rook_open_file", "rooks on open files", +1),
    Spec("rook_semi_open", "rooks on half-open files", +1),
    Spec("rook_seventh", "rook/queen on the seventh rank", +1),
    Spec("doubled_rooks", "doubled rooks", +1),
    Spec("undeveloped", "undeveloped minor pieces", -1),
    Spec("centralization", "centralised pieces", +1),
    Spec("hanging", "own pieces en prise", -1),
    Spec("hanging_value", "material en prise", -1),
    Spec("checks_available", "checks available", +1),
    Spec("forks", "forks available", +1),
    Spec("pins", "pins/skewers on enemy pieces", +1),
    Spec("discovered", "discovered attacks available", +1),
    Spec("overloaded_enemy", "overloaded enemy defenders", +1),
    Spec("trapped_enemy", "trapped enemy pieces", +1),
    Spec("mate_threat", "mate in one available", +1),
    Spec("queen_present", "queen on the board", 0),
)
GLOBAL: tuple[Spec, ...] = (
    Spec("phase", "non-pawn material left (1=full)", 0),
    Spec("opposite_bishops", "opposite-coloured bishops", 0),
    Spec("opposite_castling", "kings on opposite wings", 0),
    Spec("closed_center", "locked central pawns", 0),
    Spec("open_center", "open central files (d/e)", 0),
    Spec("material_balance", "material balance (us minus them)", +1),
    Spec("checkmate", "checkmate on the board (+1 we mate, -1 we are mated)", +1),
)
# global keys that are still directional for `us` (everything else under g. is neutral)
_DIRECTIONAL_GLOBAL = {"material_balance", "checkmate"}
SIDE_KEYS = tuple(s.key for s in SIDE)
KEYS: tuple[str, ...] = tuple(f"us.{k}" for k in SIDE_KEYS) + tuple(f"them.{k}" for k in SIDE_KEYS) + \
    tuple(f"g.{s.key}" for s in GLOBAL)
_SPEC = {s.key: s for s in SIDE + GLOBAL}


def spec(key: str) -> Spec:
    return _SPEC[key.split(".", 1)[1]]


def goodness_sign(key: str) -> int:
    """+1 if an increase of `key` is good for the `us` side, -1 if bad, 0 if neutral."""
    side, k = key.split(".", 1)
    v = _SPEC[k].valence
    if side == "g":
        return v if k in _DIRECTIONAL_GLOBAL else 0
    return v if side == "us" else -v


def describe(key: str) -> str:
    side, k = key.split(".", 1)
    who = {"us": "our", "them": "their", "g": ""}[side]
    return f"{who} {_SPEC[k].name}".strip()


# ── bitboard helpers ─────────────────────────────────────────────────────────


def _pawn_attacks(pawns: int, color: chess.Color) -> int:
    if color == chess.WHITE:
        return ((pawns << 7) & _NOT_H | (pawns << 9) & _NOT_A) & chess.BB_ALL
    return ((pawns >> 9) & _NOT_H | (pawns >> 7) & _NOT_A) & chess.BB_ALL


def _rel_rank(color: chess.Color, sq: int) -> int:
    r = chess.square_rank(sq)
    return r if color == chess.WHITE else 7 - r


def _ahead_mask(color: chess.Color, sq: int, files: int) -> int:
    """Squares strictly ahead of `sq` (from `color`'s view) on the given file mask."""
    r = chess.square_rank(sq)
    m = 0
    rng = range(r + 1, 8) if color == chess.WHITE else range(0, r)
    for rr in rng:
        m |= chess.BB_RANKS[rr]
    return m & files


def _adj_files(f: int) -> int:
    m = 0
    if f > 0:
        m |= chess.BB_FILES[f - 1]
    if f < 7:
        m |= chess.BB_FILES[f + 1]
    return m


def _popcount(x: int) -> int:
    return x.bit_count()


def _to_move(board: chess.Board, color: chess.Color) -> chess.Board | None:
    """The board with `color` to move (null move if needed); None if that's illegal (check)."""
    if board.turn == color:
        return board
    if board.is_check():
        return None
    b = board.copy(stack=False)
    b.push(chess.Move.null())
    return b


# ── per-side concepts ────────────────────────────────────────────────────────


def _pawn_concepts(board: chess.Board, c: chess.Color, out: dict) -> None:
    own = board.pieces_mask(chess.PAWN, c)
    opp = board.pieces_mask(chess.PAWN, not c)
    opp_att = _pawn_attacks(opp, not c)
    own_att = _pawn_attacks(own, c)
    files_with = [bool(own & chess.BB_FILES[f]) for f in range(8)]
    passed = protected = isolated = doubled = backward = 0
    best_rank = 0
    passer_files: list[int] = []
    for sq in chess.scan_forward(own):
        f = chess.square_file(sq)
        span = chess.BB_FILES[f] | _adj_files(f)
        if not (_ahead_mask(c, sq, span) & opp):
            passed += 1
            best_rank = max(best_rank, _rel_rank(c, sq))
            passer_files.append(f)
            if own_att & chess.BB_SQUARES[sq]:
                protected += 1
        if not (own & _adj_files(f)):
            isolated += 1
        else:
            # backward: no own pawn on adjacent files level with or behind it, stop square hit by a pawn
            behind = _ahead_mask(not c, sq, _adj_files(f)) | (chess.BB_RANKS[chess.square_rank(sq)] & _adj_files(f))
            stop = sq + 8 if c == chess.WHITE else sq - 8
            if not (own & behind) and 0 <= stop < 64 and opp_att & chess.BB_SQUARES[stop]:
                backward += 1
    for f in range(8):
        n = _popcount(own & chess.BB_FILES[f])
        if n > 1:
            doubled += n - 1
    islands, prev = 0, False
    for has in files_with:
        if has and not prev:
            islands += 1
        prev = has
    out["passed_pawns"] = passed
    out["passer_rank"] = best_rank
    out["protected_passers"] = protected
    out["connected_passers"] = int(any(abs(a - b) == 1 for a in passer_files for b in passer_files))
    out["isolated_pawns"] = isolated
    out["doubled_pawns"] = doubled
    out["backward_pawns"] = backward
    out["pawn_islands"] = islands
    d_file = own & chess.BB_FILES[3]
    out["iqp"] = int(bool(d_file) and not files_with[2] and not files_with[4])
    out["hanging_pawns"] = int(files_with[2] and files_with[3] and not files_with[1] and not files_with[4])
    qs = chess.BB_FILES[0] | chess.BB_FILES[1] | chess.BB_FILES[2]
    ks = chess.BB_FILES[5] | chess.BB_FILES[6] | chess.BB_FILES[7]
    out["majority_qs"] = int(_popcount(own & qs) > _popcount(opp & qs))
    out["majority_ks"] = int(_popcount(own & ks) > _popcount(opp & ks))
    # space: squares in the enemy half our pawns control, plus advanced central pawns
    enemy_half = 0
    for rr in (range(4, 8) if c == chess.WHITE else range(0, 4)):
        enemy_half |= chess.BB_RANKS[rr]
    central = chess.BB_FILES[2] | chess.BB_FILES[3] | chess.BB_FILES[4] | chess.BB_FILES[5]
    out["space"] = _popcount(own_att & enemy_half & ~opp_att) + _popcount(own & enemy_half & central)


def _king_concepts(board: chess.Board, c: chess.Color, phase: float, out: dict) -> None:
    k = board.king(c)
    if k is None:
        for key in ("king_shield", "king_open_files", "king_zone_attacks", "king_attackers", "king_escape",
                    "back_rank_weak", "castled", "king_center", "king_activity"):
            out[key] = 0
        return
    kf, rr = chess.square_file(k), _rel_rank(c, k)
    own_p = board.pieces_mask(chess.PAWN, c)
    files = chess.BB_FILES[kf] | _adj_files(kf)
    shield = 0
    if rr <= 1:
        for step in (1, 2):
            r = chess.square_rank(k) + (step if c == chess.WHITE else -step)
            if 0 <= r < 8:
                shield += _popcount(own_p & files & chess.BB_RANKS[r])
    out["king_shield"] = shield
    out["king_open_files"] = sum(1 for f in range(max(0, kf - 1), min(7, kf + 1) + 1)
                                 if not own_p & chess.BB_FILES[f])
    zone = int(board.attacks_mask(k)) | chess.BB_SQUARES[k]
    attacks = attackers = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for sq in chess.scan_forward(board.pieces_mask(pt, not c)):
            hit = _popcount(board.attacks_mask(sq) & zone)
            if hit:
                attacks += hit
                attackers += 1
    attacks += _popcount(_pawn_attacks(board.pieces_mask(chess.PAWN, not c), not c) & zone)
    out["king_zone_attacks"] = attacks
    out["king_attackers"] = attackers
    own_occ = board.occupied_co[c]
    out["king_escape"] = sum(1 for sq in chess.scan_forward(board.attacks_mask(k) & ~own_occ)
                             if not board.is_attacked_by(not c, sq))
    # a back rank still full of undeveloped minors isn't "weak" — the motif needs an emptied rank
    home_rank = chess.BB_RANKS[0 if c == chess.WHITE else 7]
    minors_home = (board.pieces_mask(chess.KNIGHT, c) | board.pieces_mask(chess.BISHOP, c)) & home_rank
    out["back_rank_weak"] = int(not minors_home and bool(back_rank(board, c)))
    out["castled"] = int(rr == 0 and kf in (0, 1, 2, 6, 7))
    queens = board.pieces_mask(chess.QUEEN, not c)
    out["king_center"] = int(kf in (3, 4, 5) and bool(queens) and phase > 0.35)
    if phase <= 0.35:
        dist = max(abs(kf - 3.5), abs(chess.square_rank(k) - 3.5))
        out["king_activity"] = round(3.5 - dist, 1)
    else:
        out["king_activity"] = 0


def _piece_concepts(board: chess.Board, c: chess.Color, out: dict) -> None:
    own_occ = board.occupied_co[c]
    opp_p = board.pieces_mask(chess.PAWN, not c)
    opp_patt = _pawn_attacks(opp_p, not c)
    own_p = board.pieces_mask(chess.PAWN, c)
    own_patt = _pawn_attacks(own_p, c)
    mob = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for sq in chess.scan_forward(board.pieces_mask(pt, c)):
            mob += _popcount(board.attacks_mask(sq) & ~own_occ & ~opp_patt)
    out["mobility"] = mob
    outposts = 0
    for pt in (chess.KNIGHT, chess.BISHOP):
        for sq in chess.scan_forward(board.pieces_mask(pt, c)):
            if 3 <= _rel_rank(c, sq) <= 5 and own_patt & chess.BB_SQUARES[sq] and \
                    not (_ahead_mask(c, sq, _adj_files(chess.square_file(sq))) & opp_p):
                outposts += 1
    out["outposts"] = outposts
    # bad bishop: >=2 of our central (c-f) pawns fixed on its colour (blocked by any piece)
    central = chess.BB_FILES[2] | chess.BB_FILES[3] | chess.BB_FILES[4] | chess.BB_FILES[5]
    fwd = (own_p << 8 if c == chess.WHITE else own_p >> 8) & chess.BB_ALL
    blocked = ((fwd & board.occupied) >> 8 if c == chess.WHITE else (fwd & board.occupied) << 8) & chess.BB_ALL
    fixed = blocked & central
    bad = 0
    for sq in chess.scan_forward(board.pieces_mask(chess.BISHOP, c)):
        same = _LIGHT if chess.BB_SQUARES[sq] & _LIGHT else ~_LIGHT & chess.BB_ALL
        if _popcount(fixed & same) >= 2:
            bad += 1
    out["bad_bishop"] = bad
    all_p = own_p | opp_p
    rook_open = semi = seventh = doubled = 0
    rooks = board.pieces_mask(chess.ROOK, c)
    opp_k = board.king(not c)
    for sq in chess.scan_forward(rooks):
        f = chess.BB_FILES[chess.square_file(sq)]
        if not all_p & f:
            rook_open += 1
        elif not own_p & f:
            semi += 1
        if board.attacks_mask(sq) & rooks & f:
            doubled = 1
    for sq in chess.scan_forward(rooks | board.pieces_mask(chess.QUEEN, c)):
        if _rel_rank(c, sq) == 6 and ((opp_k is not None and _rel_rank(c, opp_k) == 7) or
                                      opp_p & chess.BB_RANKS[chess.square_rank(sq)]):
            seventh += 1
    out["rook_open_file"] = rook_open
    out["rook_semi_open"] = semi
    out["rook_seventh"] = seventh
    out["doubled_rooks"] = doubled
    home = (chess.B1, chess.G1, chess.C1, chess.F1) if c == chess.WHITE else (chess.B8, chess.G8, chess.C8, chess.F8)
    out["undeveloped"] = sum(1 for sq in home if (p := board.piece_at(sq)) and p.color == c and
                             p.piece_type in (chess.KNIGHT, chess.BISHOP))
    minors_q = board.pieces_mask(chess.KNIGHT, c) | board.pieces_mask(chess.BISHOP, c) | \
        board.pieces_mask(chess.QUEEN, c)
    out["centralization"] = _popcount(minors_q & _CENTER16)
    out["queen_present"] = int(bool(board.pieces_mask(chess.QUEEN, c)))
    out["bishop_pair"] = int(_popcount(board.pieces_mask(chess.BISHOP, c)) >= 2)
    out["material"] = sum(VAL[pt] * _popcount(board.pieces_mask(pt, c)) for pt in VAL)


def _en_prise(board: chess.Board, c: chess.Color) -> tuple[int, int]:
    """(count, max SEE) of `c` pieces the opponent could win by capturing."""
    b = _to_move(board, not c)
    if b is None:  # `c` is giving check: the opponent's capture options are moot this ply
        b = board.copy(stack=False)
        b.turn = not c
        b.ep_square = None
    n = best = 0
    for sq in chess.scan_forward(board.occupied_co[c] & ~board.kings):
        top = 0
        for a in chess.scan_forward(b.attackers_mask(not c, sq)):
            promo = chess.QUEEN if b.piece_type_at(a) == chess.PAWN and chess.square_rank(sq) in (0, 7) else None
            mv = chess.Move(a, sq, promotion=promo)
            if b.is_pseudo_legal(mv) and not b.is_into_check(mv):
                top = max(top, see(b, mv))
        if top > 0:
            n += 1
            best = max(best, top)
    return n, best


def _tactical_concepts(board: chess.Board, c: chess.Color, out: dict) -> None:
    out["hanging"], out["hanging_value"] = _en_prise(board, c)
    out["pins"] = len(pins_and_skewers(board, c))
    out["overloaded_enemy"] = len(overloaded(board, not c))
    out["trapped_enemy"] = len(trapped(board, not c))
    b = _to_move(board, c)
    if b is None:
        out["checks_available"] = out["forks"] = out["discovered"] = out["mate_threat"] = 0
        return
    checks = mate = 0
    for mv in b.legal_moves:
        if b.gives_check(mv):
            checks += 1
            if not mate:
                b.push(mv)
                mate = int(b.is_checkmate())
                b.pop()
    out["checks_available"] = checks
    out["mate_threat"] = mate
    out["forks"] = len(forks(b, limit=8))
    out["discovered"] = len(discovered(b, limit=4))


def phase_of(board: chess.Board) -> float:
    npm = sum(VAL[pt] * _popcount(board.pieces_mask(pt, chess.WHITE) | board.pieces_mask(pt, chess.BLACK))
              for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
    return round(min(1.0, npm / 62), 3)


def side(board: chess.Board, c: chess.Color, phase: float | None = None) -> dict[str, float]:
    ph = phase_of(board) if phase is None else phase
    out: dict[str, float] = {}
    _pawn_concepts(board, c, out)
    _king_concepts(board, c, ph, out)
    _piece_concepts(board, c, out)
    _tactical_concepts(board, c, out)
    return out


def global_concepts(board: chess.Board) -> dict[str, float]:
    ph = phase_of(board)
    wb, bb = board.pieces_mask(chess.BISHOP, chess.WHITE), board.pieces_mask(chess.BISHOP, chess.BLACK)
    opp_b = int(_popcount(wb) == 1 and _popcount(bb) == 1 and bool(wb & _LIGHT) != bool(bb & _LIGHT))
    wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
    opp_c = 0
    if wk is not None and bk is not None:
        wf, bf = chess.square_file(wk), chess.square_file(bk)
        opp_c = int((wf <= 2 and bf >= 5) or (wf >= 5 and bf <= 2))
    wp, bp = board.pieces_mask(chess.PAWN, chess.WHITE), board.pieces_mask(chess.PAWN, chess.BLACK)
    locked = _popcount((wp << 8) & bp & (chess.BB_FILES[2] | chess.BB_FILES[3] | chess.BB_FILES[4] | chess.BB_FILES[5]))
    open_c = sum(1 for f in (3, 4) if not (wp | bp) & chess.BB_FILES[f])
    return {"phase": ph, "opposite_bishops": opp_b, "opposite_castling": opp_c,
            "closed_center": locked, "open_center": open_c}


def static(board: chess.Board, pov: chess.Color | None = None) -> dict[str, float]:
    """All concepts for `board`, keyed us./them./g. relative to `pov` (default: side to move)."""
    pov = board.turn if pov is None else pov
    ph = phase_of(board)
    us, them = side(board, pov, ph), side(board, not pov, ph)
    out = {f"us.{k}": float(v) for k, v in us.items()}
    out.update({f"them.{k}": float(v) for k, v in them.items()})
    out.update({f"g.{k}": float(v) for k, v in global_concepts(board).items()})
    out["g.material_balance"] = out["us.material"] - out["them.material"]
    out["g.checkmate"] = (-1.0 if board.turn == pov else 1.0) if board.is_checkmate() else 0.0
    return out


def vector(d: dict[str, float]) -> list[float]:
    return [d.get(k, 0.0) for k in KEYS]


# ── moves and lines ──────────────────────────────────────────────────────────


def best_capture_see(board: chess.Board) -> int:
    best = 0
    for mv in board.legal_moves:
        if board.is_capture(mv):
            best = max(best, see(board, mv))
    return best


def move_facts(board: chess.Board, move: chess.Move) -> dict[str, float]:
    """What kind of move this is, from the mover's view (all numbers, for the dataset)."""
    c = board.turn
    pt = board.piece_type_at(move.from_square)
    cap = board.is_capture(move)
    f: dict[str, float] = {
        "capture": float(cap), "check": float(board.gives_check(move)),
        "castle": float(board.is_castling(move)), "promotion": float(bool(move.promotion)),
        "pawn_move": float(pt == chess.PAWN), "king_move": float(pt == chess.KING),
        "see": float(see(board, move)) if cap else 0.0,
    }
    fr, tr = _rel_rank(c, move.from_square), _rel_rank(c, move.to_square)
    f["retreat"] = float(pt not in (chess.PAWN, chess.KING) and tr < fr)
    f["development"] = float(pt in (chess.KNIGHT, chess.BISHOP) and fr == 0 and tr > 0)
    threat_before = _threat(board)
    our_before = best_capture_see(board)
    b = board.copy(stack=False)
    b.push(move)
    # material offered: what the opponent could now win on the destination square
    offered = 0
    for a in chess.scan_forward(b.attackers_mask(b.turn, move.to_square)):
        promo = chess.QUEEN if b.piece_type_at(a) == chess.PAWN and chess.square_rank(move.to_square) in (0, 7) else None
        mv = chess.Move(a, move.to_square, promotion=promo)
        if b.is_legal(mv):
            offered = max(offered, see(b, mv))
    f["offers_material"] = float(offered)
    f["exchange"] = float(cap and f["see"] == 0 and bool(b.attackers_mask(b.turn, move.to_square)))
    f["pawn_break"] = float(pt == chess.PAWN and bool(
        _pawn_attacks(chess.BB_SQUARES[move.to_square], c) & b.pieces_mask(chess.PAWN, not c)))
    # a NEW follow-up threat (if we could move again), and the opponent's threat before/after
    again = _to_move(b, c)
    f["creates_threat"] = float(max(0, best_capture_see(again) - our_before)) if again is not None else 0.0
    threat_after = _threat_against(b, c)
    f["parries_threat"] = float(max(0, threat_before - threat_after))
    return f


def _threat(board: chess.Board) -> int:
    """Opponent's best immediate gain against the side to move (null-move threat), mate = 50."""
    return _threat_against(board, board.turn)


def _threat_against(board: chess.Board, c: chess.Color) -> int:
    b = _to_move(board, not c)
    if b is None:
        return 0
    for mv in b.legal_moves:
        if b.gives_check(mv):
            b.push(mv)
            mate = b.is_checkmate()
            b.pop()
            if mate:
                return 50
    return best_capture_see(b)


def play_line(board: chess.Board, uci_line: list[str]) -> tuple[chess.Board, list[str]]:
    """Play a UCI line from `board`; stops at the first illegal move. Returns end board + SANs."""
    b = board.copy(stack=False)
    sans: list[str] = []
    for u in uci_line:
        try:
            mv = chess.Move.from_uci(u)
        except ValueError:
            break
        if not b.is_legal(mv):
            break
        sans.append(b.san(mv))
        b.push(mv)
    return b, sans


def line_end_concepts(board: chess.Board, uci_line: list[str], pov: chess.Color, plies: int = 8) -> dict[str, float]:
    """Concepts at the end of `uci_line` (truncated to `plies`), from `pov`, with material
    resolved one capture deep so a line cut mid-exchange isn't scored as a win."""
    end, _ = play_line(board, uci_line[:plies])
    d = static(end, pov)
    if not end.is_game_over():
        gain = best_capture_see(end)
        if gain > 0:
            d["us.material" if end.turn == pov else "them.material"] += gain
            d["g.material_balance"] += gain if end.turn == pov else -gain
    return d


def delta(root: dict[str, float], end: dict[str, float]) -> dict[str, float]:
    return {k: end.get(k, 0.0) - root.get(k, 0.0) for k in KEYS}


# Ranking weight per concept: primary causes (material, mate, passers, king) outrank their
# consequences (losing the queen also collapses mobility — a human says "wins the queen").
PRIORITY: dict[str, float] = {
    "material": 3.0, "material_balance": 3.0, "checkmate": 5.0, "mate_threat": 2.0, "passed_pawns": 1.5, "passer_rank": 1.2, "king_shield": 1.2,
    "king_zone_attacks": 1.0, "back_rank_weak": 1.3, "trapped_enemy": 1.3, "forks": 1.2,
    "hanging": 0.8, "hanging_value": 0.6, "mobility": 0.5, "centralization": 0.6, "queen_present": 0.3,
    "checks_available": 0.5, "king_escape": 0.7, "phase": 0.3, "pawn_islands": 0.6, "space": 0.8,
}


def priority(key: str) -> float:
    return PRIORITY.get(key.split(".", 1)[1], 1.0)


def salience(d_best: dict[str, float], d_alt: dict[str, float], scale: dict[str, float] | None = None,
             top: int = 4, min_z: float = 1.0) -> list[tuple[str, float, float]]:
    """Concepts the best line changes differently from the alt line.

    Returns [(key, z, goodness)] ranked by |z| × priority: z = (Δbest − Δalt) / scale[key]
    (scale = per-concept std of line deltas over the dataset); goodness = z × goodness_sign
    (>0: the best line is better for the mover on this concept, 0 for neutral concepts)."""
    out = []
    for k in KEYS:
        if k in ("us.material", "them.material"):  # an even trade moves both; the balance is the fact
            continue
        diff = d_best.get(k, 0.0) - d_alt.get(k, 0.0)
        if diff == 0:
            continue
        z = diff / ((scale or {}).get(k) or 1.0)
        if abs(z) >= min_z:
            out.append((k, round(z, 2), round(z * goodness_sign(k), 2)))
    out.sort(key=lambda t: (-abs(t[1]) * priority(t[0]), t[0]))
    return out[:top]
