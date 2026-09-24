"""Static positional features: material, phase, pawn structure, king safety, activity.

Every function returns short human sentences (colour named explicitly) plus, where
useful, machine tags that drive concept retrieval (see concepts.py).
"""

from __future__ import annotations

import chess

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
SYMBOL = {chess.KING: "K", chess.QUEEN: "Q", chess.ROOK: "R", chess.BISHOP: "B", chess.KNIGHT: "N", chess.PAWN: "P"}
CNAME = {chess.WHITE: "White", chess.BLACK: "Black"}
FILES = "abcdefgh"


def piece_name(board: chess.Board, sq: chess.Square) -> str:
    p = board.piece_at(sq)
    assert p is not None
    return f"{SYMBOL[p.piece_type]}{chess.square_name(sq)}"


def rel_rank(color: chess.Color, sq: chess.Square) -> int:
    """1..8 rank from `color`'s point of view."""
    r = chess.square_rank(sq)
    return r + 1 if color == chess.WHITE else 8 - r


# ── material & phase ─────────────────────────────────────────────────────────


def _count(board: chess.Board, color: chess.Color, pt: int) -> int:
    return chess.popcount(board.pieces_mask(pt, color))


def material_points(board: chess.Board, color: chess.Color) -> int:
    return sum(VALUES[pt] * _count(board, color, pt) for pt in VALUES)


def non_pawn_material(board: chess.Board, color: chess.Color) -> int:
    return sum(VALUES[pt] * _count(board, color, pt) for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))


def material(board: chess.Board, tags: set[str]) -> str:
    parts = []
    for color in (chess.WHITE, chess.BLACK):
        pieces = []
        for pt in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            pieces += [SYMBOL[pt]] * _count(board, color, pt)
        pawns = _count(board, color, chess.PAWN)
        parts.append(f"{CNAME[color]}: {' '.join(pieces) or '-'} P×{pawns} ({material_points(board, color)})")
    diff = material_points(board, chess.WHITE) - material_points(board, chess.BLACK)
    bal = "equal" if diff == 0 else f"{'White' if diff > 0 else 'Black'} +{abs(diff)}"
    notes = []
    wb, bb = _count(board, chess.WHITE, chess.BISHOP), _count(board, chess.BLACK, chess.BISHOP)
    for color, mine, theirs in ((chess.WHITE, wb, bb), (chess.BLACK, bb, wb)):
        if mine >= 2 and theirs < 2:
            notes.append(f"{CNAME[color]} has the bishop pair")
            tags.add("bishop-pair")
    wr, br = _count(board, chess.WHITE, chess.ROOK), _count(board, chess.BLACK, chess.ROOK)
    wm = _count(board, chess.WHITE, chess.KNIGHT) + wb
    bm = _count(board, chess.BLACK, chess.KNIGHT) + bb
    wq, bq = _count(board, chess.WHITE, chess.QUEEN), _count(board, chess.BLACK, chess.QUEEN)
    if wr - br == 1 and bm - wm == 1:
        notes.append("White is up the exchange")
        tags.add("exchange")
    elif br - wr == 1 and wm - bm == 1:
        notes.append("Black is up the exchange")
        tags.add("exchange")
    elif wm - bm >= 1 and wr == br and wq == bq and diff <= 0:
        notes.append(f"White has {wm - bm} extra minor piece(s) vs pawns")
    elif bm - wm >= 1 and wr == br and wq == bq and diff >= 0:
        notes.append(f"Black has {bm - wm} extra minor piece(s) vs pawns")
    if wq != bq and abs(wq - bq) == 1 and (wr + wm) != (br + bm):
        notes.append("queen vs pieces imbalance")
    if wb == 1 and bb == 1:
        wsq = next(iter(board.pieces(chess.BISHOP, chess.WHITE)))
        bsq = next(iter(board.pieces(chess.BISHOP, chess.BLACK)))
        if _sq_color(wsq) != _sq_color(bsq):
            notes.append("opposite-coloured bishops (drawish in endgames, attacking in middlegames)")
            tags.add("opposite-bishops")
    s = f"{parts[0]} | {parts[1]} | balance: {bal}"
    if notes:
        s += " | " + "; ".join(notes)
    return s


def _sq_color(sq: chess.Square) -> int:
    return (chess.square_file(sq) + chess.square_rank(sq)) % 2


def phase(board: chess.Board) -> str:
    npm = non_pawn_material(board, chess.WHITE) + non_pawn_material(board, chess.BLACK)
    queens = chess.popcount(board.queens)
    if npm <= 18 or (queens == 0 and npm <= 26):
        return "endgame"
    undeveloped = 0
    for color, rank in ((chess.WHITE, 0), (chess.BLACK, 7)):
        for f in (1, 2, 5, 6):
            p = board.piece_at(chess.square(f, rank))
            if p and p.color == color and p.piece_type in (chess.KNIGHT, chess.BISHOP):
                undeveloped += 1
    if board.fullmove_number <= 8 or (board.fullmove_number <= 15 and undeveloped >= 3):
        return "opening"
    return "middlegame"


# ── pawn structure ───────────────────────────────────────────────────────────


def _pawn_files(board: chess.Board, color: chess.Color) -> list[list[chess.Square]]:
    files: list[list[chess.Square]] = [[] for _ in range(8)]
    for sq in board.pieces(chess.PAWN, color):
        files[chess.square_file(sq)].append(sq)
    return files


def _has(board: chess.Board, color: chess.Color, name: str) -> bool:
    p = board.piece_at(chess.parse_square(name))
    return p is not None and p.piece_type == chess.PAWN and p.color == color


def _no_file(files: list[list[chess.Square]], letter: str) -> bool:
    return not files[FILES.index(letter)]


def is_passed(board: chess.Board, color: chess.Color, sq: chess.Square) -> bool:
    f, r = chess.square_file(sq), chess.square_rank(sq)
    for esq in board.pieces(chess.PAWN, not color):
        ef, er = chess.square_file(esq), chess.square_rank(esq)
        if abs(ef - f) <= 1 and ((er > r) if color == chess.WHITE else (er < r)):
            return False
    return True


def _islands(files: list[list[chess.Square]]) -> int:
    n, inside = 0, False
    for f in files:
        if f and not inside:
            n += 1
        inside = bool(f)
    return n


def _sqlist(sqs: list[chess.Square]) -> str:
    return ", ".join(chess.square_name(s) for s in sorted(sqs))


def pawn_structure(board: chess.Board, tags: set[str], plans: list[str]) -> list[str]:
    out: list[str] = []
    files = {c: _pawn_files(board, c) for c in (chess.WHITE, chess.BLACK)}
    passers: dict[chess.Color, list[chess.Square]] = {}
    for color in (chess.WHITE, chess.BLACK):
        own, name = files[color], CNAME[color]
        isolated, doubled, backward, passed = [], [], [], []
        for f in range(8):
            if len(own[f]) > 1:
                doubled.append(FILES[f])
            for sq in own[f]:
                neighbours = [s for nf in (f - 1, f + 1) if 0 <= nf < 8 for s in own[nf]]
                if not neighbours:
                    isolated.append(sq)
                elif _is_backward(board, color, sq, neighbours):
                    backward.append(sq)
                if is_passed(board, color, sq):
                    passed.append(sq)
        passers[color] = passed
        if isolated:
            out.append(f"{name} isolated pawn(s): {_sqlist(isolated)}")
            tags.add("weak-pawns")
        if doubled:
            out.append(f"{name} doubled pawns on the {', '.join(doubled)}-file")
            tags.add("weak-pawns")
        if backward:
            out.append(f"{name} backward pawn(s): {_sqlist(backward)} (stop square controlled by enemy pawn)")
            tags.add("weak-pawns")
        if passed:
            descr = []
            for sq in sorted(passed, key=lambda s: -rel_rank(color, s)):
                extra = []
                if board.attackers_mask(color, sq) & board.pieces_mask(chess.PAWN, color):
                    extra.append("protected")
                f = chess.square_file(sq)
                if any(abs(chess.square_file(o) - f) == 1 for o in passed):
                    extra.append("connected")
                extra.append(f"rank {rel_rank(color, sq)}")
                descr.append(f"{chess.square_name(sq)} ({', '.join(extra)})")
            out.append(f"{name} passed pawn(s): {'; '.join(descr)}")
            tags.add("passed-pawn")
        isl = _islands(own)
        if isl >= 3:
            out.append(f"{name} has {isl} pawn islands")
    wf, bf = files[chess.WHITE], files[chess.BLACK]
    open_f = [FILES[f] for f in range(8) if not wf[f] and not bf[f]]
    half_w = [FILES[f] for f in range(8) if not wf[f] and bf[f]]
    half_b = [FILES[f] for f in range(8) if wf[f] and not bf[f]]
    if open_f:
        out.append(f"Open files: {', '.join(open_f)}")
        tags.add("open-file")
    if half_w or half_b:
        out.append(f"Half-open files: White {', '.join(half_w) or '-'}; Black {', '.join(half_b) or '-'}")
    for wing, rng in (("queenside", range(0, 3)), ("kingside", range(5, 8))):
        w = sum(len(wf[f]) for f in rng)
        b = sum(len(bf[f]) for f in rng)
        if w != b and (w + b) > 0:
            leader = "White" if w > b else "Black"
            out.append(f"{leader} has a {wing} pawn majority ({max(w, b)} vs {min(w, b)})")
            tags.add("pawn-majority")
    out += _named_structures(board, files, tags, plans)
    return out


def _is_backward(board: chess.Board, color: chess.Color, sq: chess.Square, neighbours: list[chess.Square]) -> bool:
    r = rel_rank(color, sq)
    # Supported (or supportable) if a neighbour pawn is level or behind.
    if any(rel_rank(color, n) <= r for n in neighbours):
        return False
    step = 8 if color == chess.WHITE else -8
    stop = sq + step
    if not 0 <= stop < 64:
        return False
    enemy_pawns = board.pieces_mask(chess.PAWN, not color)
    return bool(board.attackers_mask(not color, stop) & enemy_pawns)


def _named_structures(board, files, tags, plans) -> list[str]:
    W, B = chess.WHITE, chess.BLACK
    wf, bf = files[W], files[B]
    out: list[str] = []

    def add(name: str, tag: str, sentence: str, plan: str) -> None:
        out.append(f"Structure: {name} — {sentence}")
        tags.add(tag)
        plans.append(f"{name}: {plan}")

    # IQP (either colour): isolated d-pawn, no c/e pawns for its owner.
    for color in (W, B):
        own, opp = files[color], files[not color]
        if own[3] and len(own[3]) == 1 and not own[2] and not own[4] and not opp[3]:
            sq = own[3][0]
            if rel_rank(color, sq) in (4, 5):
                o, x = CNAME[color], CNAME[not color]
                add(f"IQP ({o} d-pawn on {chess.square_name(sq)})", "iqp",
                    f"{o} has an isolated queen's pawn",
                    f"{o}: keep pieces, attack the king, use e5/c5 outposts, prepare the d-pawn break. "
                    f"{x}: blockade the square in front, trade minor pieces, aim for an endgame.")
    # Hanging pawns: c+d pawns side by side, no b/e pawns of owner, opponent lacks c/d.
    for color in (W, B):
        own, opp = files[color], files[not color]
        if own[2] and own[3] and not own[1] and not own[4] and not opp[2] and not opp[3]:
            c, d = own[2][0], own[3][0]
            if rel_rank(color, c) == rel_rank(color, d) == 4:
                o, x = CNAME[color], CNAME[not color]
                add(f"Hanging pawns ({o} c+d)", "hanging-pawns",
                    f"{o} has hanging pawns on {chess.square_name(c)}/{chess.square_name(d)}",
                    f"{o}: keep them side by side, use half-open b/e files, push one when it gains tempo. "
                    f"{x}: pressure them with pieces and ...b/e-pawn levers to force one to advance or fall.")
    # Carlsbad (White minority-attack structure).
    if (_has(board, W, "d4") and _has(board, W, "e3") and _no_file(wf, "c")
            and _has(board, B, "d5") and _has(board, B, "c6") and _no_file(bf, "e")):
        tags.add("minority-attack")
        add("Carlsbad", "carlsbad", "QGD Exchange pawn structure",
            "White: minority attack b4-b5 to create a weak c-pawn, or central f3+e4. "
            "Black: kingside piece play, knight to e4, ...f5 setups; avoid passivity.")
    if (_has(board, B, "d5") and _has(board, B, "e6") and _no_file(bf, "c")
            and _has(board, W, "d4") and _has(board, W, "c3") and _no_file(wf, "e")):
        add("Reversed Carlsbad", "carlsbad", "Black can play the minority attack ...b5-b4",
            "Black: ...b5-b4 minority attack. White: kingside play, Ne5, f4-f5.")
    # Maroczy bind / Hedgehog.
    if _has(board, W, "c4") and _has(board, W, "e4") and _no_file(wf, "d") and _no_file(bf, "c") and bf[3]:
        if _has(board, B, "b6") and _has(board, B, "e6") and _has(board, B, "d6"):
            add("Hedgehog", "hedgehog", "Black pawns a6/b6/d6/e6 behind White's c4+e4",
                "White: restrain ...b5 and ...d5, gain space, avoid overextending. "
                "Black: wait compactly, then strike with ...b5 or ...d5 when prepared.")
        else:
            add("Maroczy bind", "maroczy", "White pawns c4+e4 clamp d5",
                "White: keep the bind, control d5, play on the queenside (c5 break, Rc1). "
                "Black: trade pieces (especially dark-squared bishops), aim for ...b5 or ...f5 breaks.")
    # Sicilian small centres.
    elif _has(board, W, "e4") and _no_file(wf, "d") and _no_file(bf, "c") and _has(board, B, "d6"):
        if _has(board, B, "e6"):
            add("Scheveningen small centre", "sicilian", "Black d6+e6 vs White e4",
                "White: kingside pawn storm (g4-g5, f4-f5) or e4-e5 break. "
                "Black: ...d5 or ...b5-b4 counterplay, half-open c-file.")
        elif _has(board, B, "e5"):
            add("Najdorf/Boleslavsky structure", "sicilian", "Black d6+e5, hole on d5",
                "White: occupy/control d5 (Nd5, Bxf6), play on the queenside or f4. "
                "Black: challenge d5 with ...d5 break, use the c-file, ...b5.")
    # French / Caro advance chains.
    if _has(board, W, "d4") and _has(board, W, "e5") and _has(board, B, "d5"):
        if _has(board, B, "e6"):
            add("French advance chain", "french-chain", "White d4-e5 vs Black d5-e6",
                "White: space on the kingside, f4-f5 attack, maintain d4. "
                "Black: attack the chain base with ...c5 and ...f6, pressure d4.")
    # KID locked centre.
    if _has(board, W, "d5") and _has(board, W, "e4") and _has(board, B, "d6") and _has(board, B, "e5"):
        add("King's Indian locked centre", "kid-locked", "White d5+e4 vs Black d6+e5",
            "White: queenside expansion c4-c5, b4, attack d6/c7. "
            "Black: kingside pawn storm ...f5-f4, ...g5-g4 against White's king.")
    # Modern Benoni.
    if _has(board, W, "d5") and _has(board, B, "c5") and _has(board, B, "d6") and _no_file(bf, "e") and _no_file(wf, "c"):
        add("Benoni structure", "benoni", "White d5 vs Black c5+d6, Black queenside majority",
            "White: e4-e5 break, blockade/pressure d6, restrain ...b5. "
            "Black: ...b5 queenside expansion, use e-file and long diagonal, ...f5 break.")
    # Stonewall.
    for color, trio in ((W, ("d4", "e3", "f4")), (B, ("d5", "e6", "f5"))):
        if all(_has(board, color, s) for s in trio):
            o = CNAME[color]
            hole = "e4" if color == W else "e5"
            add(f"Stonewall ({o})", "stonewall", f"{o} pawns {'-'.join(trio)}, hole on {hole}",
                f"{o}: occupy the outpost with a knight, kingside attack (g-/h-pawn, rook lift). "
                f"Opponent: exploit the {hole} hole and the bad bishop, trade good minors.")
    return out


# ── king safety ──────────────────────────────────────────────────────────────


def king_zone(board: chess.Board, color: chess.Color) -> chess.SquareSet:
    k = board.king(color)
    if k is None:
        return chess.SquareSet()
    return chess.SquareSet(chess.BB_KING_ATTACKS[k] | chess.BB_SQUARES[k])


def king_safety(board: chess.Board, tags: set[str], ph: str) -> list[str]:
    out: list[str] = []
    castled_side: dict[chess.Color, str | None] = {}
    for color in (chess.WHITE, chess.BLACK):
        k = board.king(color)
        if k is None:
            continue
        name = CNAME[color]
        kf, kr = chess.square_file(k), rel_rank(color, k)
        if ph == "endgame":
            status, side = f"king on {chess.square_name(k)}", None
        elif kr <= 2 and kf >= 5:
            status, side = "king on kingside", "king"
        elif kr <= 2 and kf <= 2:
            status, side = "king on queenside", "queen"
        else:
            side = None
            rights = []
            if board.has_kingside_castling_rights(color):
                rights.append("O-O")
            if board.has_queenside_castling_rights(color):
                rights.append("O-O-O")
            status = "king in centre" + (f" (can still {'/'.join(rights)})" if rights else " (castling rights lost)")
        castled_side[color] = side
        bits = [f"{name}: {status}"]
        if ph != "endgame":
            # Pawn shield on the three files around the king.
            holes, open_near = [], []
            for f in range(max(0, kf - 1), min(7, kf + 1) + 1):
                shield_ok = False
                for dr in (1, 2):
                    rr = kr + dr
                    if rr > 8:
                        continue
                    r_abs = rr - 1 if color == chess.WHITE else 8 - rr
                    p = board.piece_at(chess.square(f, r_abs))
                    if p and p.piece_type == chess.PAWN and p.color == color:
                        shield_ok = True
                if not shield_ok:
                    holes.append(FILES[f])
                own_pawn = board.pieces_mask(chess.PAWN, color) & chess.BB_FILES[f]
                if not own_pawn:
                    open_near.append(FILES[f])
            if holes and kr <= 2 and kf not in (3, 4):
                bits.append(f"shield missing on {','.join(holes)}-file")
            if open_near:
                bits.append(f"open/half-open file(s) near king: {','.join(open_near)}")
                tags.add("king-safety")
            zone = king_zone(board, color)
            attackers = set()
            for sq in zone:
                for a in board.attackers(not color, sq):
                    if board.piece_type_at(a) != chess.PAWN:
                        attackers.add(a)
            if attackers:
                names = ", ".join(piece_name(board, a) for a in sorted(attackers))
                bits.append(f"enemy pieces hitting king zone: {names}")
                if len(attackers) >= 3:
                    tags.add("king-safety")
        if board.is_check() and board.turn == color:
            bits.append("IN CHECK")
        out.append("; ".join(bits))
    w, b = castled_side.get(chess.WHITE), castled_side.get(chess.BLACK)
    if w and b and w != b and ph != "endgame":
        out.append("Opposite-side castling: pawn storms and speed of attack decide")
        tags.add("opposite-castling")
    elif ph == "endgame":
        out.append("Endgame: activate the king (centralise it)")
    return out


# ── piece activity ───────────────────────────────────────────────────────────


def mobility(board: chess.Board, color: chess.Color) -> int:
    b = board.copy(stack=False)
    b.turn = color
    b.ep_square = None
    return sum(1 for _ in b.pseudo_legal_moves)


def _is_outpost(board: chess.Board, color: chess.Color, sq: chess.Square) -> bool:
    r = rel_rank(color, sq)
    if r not in (4, 5, 6):
        return False
    own_pawns = board.pieces_mask(chess.PAWN, color)
    if not (board.attackers_mask(color, sq) & own_pawns):
        return False
    f = chess.square_file(sq)
    # No enemy pawn can ever attack it: none on adjacent files further up the board.
    for esq in board.pieces(chess.PAWN, not color):
        ef = chess.square_file(esq)
        if abs(ef - f) == 1 and rel_rank(color, esq) > r:
            return False
    return True


def piece_activity(board: chess.Board, tags: set[str], ph: str) -> list[str]:
    out: list[str] = []
    mw, mb = mobility(board, chess.WHITE), mobility(board, chess.BLACK)
    out.append(f"Mobility (pseudo-legal moves): White {mw}, Black {mb}")
    for color in (chess.WHITE, chess.BLACK):
        name = CNAME[color]
        notes: list[str] = []
        own_files = _pawn_files(board, color)
        opp_files = _pawn_files(board, not color)
        for sq in board.pieces(chess.KNIGHT, color) | board.pieces(chess.BISHOP, color):
            if _is_outpost(board, color, sq):
                notes.append(f"{piece_name(board, sq)} on an outpost")
                tags.add("outpost")
        for sq in board.pieces(chess.ROOK, color) | board.pieces(chess.QUEEN, color):
            f = chess.square_file(sq)
            is_rook = board.piece_type_at(sq) == chess.ROOK
            if is_rook and not own_files[f]:
                notes.append(f"{piece_name(board, sq)} on {'open' if not opp_files[f] else 'half-open'} {FILES[f]}-file")
            if rel_rank(color, sq) == 7:
                notes.append(f"{piece_name(board, sq)} on the 7th rank")
                tags.add("seventh-rank")
        for sq in board.pieces(chess.BISHOP, color):
            colour = _sq_color(sq)
            same = [p for p in board.pieces(chess.PAWN, color) if _sq_color(p) == colour]
            other = chess.popcount(board.pieces_mask(chess.PAWN, color)) - len(same)
            step = 8 if color == chess.WHITE else -8
            # "Fixed" = blocked by an enemy pawn, so it will stay on the bishop's colour.
            fixed = [p for p in same if chess.square_file(p) in (2, 3, 4, 5) and 0 <= p + step < 64
                     and board.piece_at(p + step) == chess.Piece(chess.PAWN, not color)]
            if len(same) >= 3 and len(same) > other and len(fixed) >= 2:
                notes.append(f"{piece_name(board, sq)} is a bad bishop ({len(same)} own pawns on its colour)")
                tags.add("bad-bishop")
        if ph != "endgame":
            home = 0 if color == chess.WHITE else 7
            undeveloped = []
            for f in (1, 2, 5, 6):
                sq = chess.square(f, home)
                p = board.piece_at(sq)
                if p and p.color == color and p.piece_type in (chess.KNIGHT, chess.BISHOP):
                    undeveloped.append(piece_name(board, sq))
            if undeveloped and board.fullmove_number >= 4:
                notes.append(f"undeveloped: {', '.join(undeveloped)}")
                if len(undeveloped) >= 2:
                    tags.add("development")
        # Empty outpost squares a knight could use (central files only, keep it short).
        spots = [] if not board.pieces(chess.KNIGHT, color) else [chess.square_name(s) for s in chess.SQUARES
                 if chess.square_file(s) in (2, 3, 4, 5) and rel_rank(color, s) in (5, 6)
                 and board.piece_at(s) is None and _is_outpost(board, color, s)]
        if spots:
            notes.append(f"outpost squares available: {', '.join(spots[:4])}")
            tags.add("outpost")
        if notes:
            out.append(f"{name}: " + "; ".join(notes))
    return out
