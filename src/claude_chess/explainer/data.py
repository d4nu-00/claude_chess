"""Lichess open data (CC0) -> featurized shards for the explainer.

Sources (downloaded to data/raw/, see wiki/pages/explainer-model.md):
- lichess_db_eval.jsonl.zst — cloud evals: {"fen", "evals": [{"pvs": [{"cp"|"mate", "line"}], "depth"}]}.
  cp/mate are from WHITE's point of view; PVs are best-first for the side to move.
- lichess_db_puzzle.csv.zst — FEN is BEFORE the opponent's move; Moves[0] is that move,
  Moves[1:] the solution. Themes are human tags (fork, pin, mateIn2, ...).

Each kept position gets: board tokens (side-to-move POV), legal moves, soft policy target
over the PV moves, value (mover's win prob), root concepts, Δconcepts along the best and
alternative lines (8 plies), and move facts for both first moves. Shards are .npz (no
pickles); strings are stored as unicode arrays.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import multiprocessing as mp
from pathlib import Path
from typing import Iterator

import chess

from claude_chess.explainer import concepts as C

DATA_DIR = Path("data/explainer")
RAW_DIR = Path("data/raw")
EVAL_FILE = RAW_DIR / "lichess_db_eval.head400m.jsonl.zst"
PUZZLE_FILE = RAW_DIR / "lichess_db_puzzle.csv.zst"
LINE_PLIES = 8
MAX_PV = 5
MAX_LEGAL = 128
POLICY_TAU = 0.03  # win-prob temperature for the soft policy target over PV moves
FACT_KEYS = ("capture", "check", "castle", "promotion", "pawn_move", "king_move", "see", "retreat",
             "development", "offers_material", "exchange", "pawn_break", "creates_threat", "parries_threat")


# ── basic conversions ────────────────────────────────────────────────────────


def win_prob(cp: float | None = None, mate: int | None = None) -> float:
    """White's win probability 0..1 (Lichess win% formula); mate scores saturate."""
    if mate is not None:
        return 1.0 if mate > 0 else 0.0
    cp = max(-3000.0, min(3000.0, float(cp or 0.0)))
    return 1.0 / (1.0 + math.exp(-0.00368208 * cp))


def structure_split(board: chess.Board) -> int:
    """0 train / 1 val / 2 test by a hash of pawns + piece counts + side to move: positions from
    one analysis session (same structure, pieces shuffled) land in the same split."""
    sig = (board.pawns & board.occupied_co[chess.WHITE], board.pawns & board.occupied_co[chess.BLACK],
           tuple(len(board.pieces(pt, c)) for c in chess.COLORS for pt in chess.PIECE_TYPES), board.turn)
    h = int(hashlib.sha1(repr(sig).encode()).hexdigest(), 16) % 20
    return 2 if h == 0 else 1 if h == 1 else 0


def pov_square(sq: int, color: chess.Color) -> int:
    return sq if color == chess.WHITE else chess.square_mirror(sq)


def encode_board(board: chess.Board) -> tuple[list[int], list[int], int]:
    """64 tokens (0 empty, 1-6 our PNBRQK, 7-12 theirs) from the mover's view (board mirrored
    for Black), castling [us K, us Q, them K, them Q], en-passant file+1 (0 = none)."""
    us = board.turn
    toks = [0] * 64
    for sq, p in board.piece_map().items():
        toks[pov_square(sq, us)] = p.piece_type + (0 if p.color == us else 6)
    castle = [int(board.has_kingside_castling_rights(us)), int(board.has_queenside_castling_rights(us)),
              int(board.has_kingside_castling_rights(not us)), int(board.has_queenside_castling_rights(not us))]
    ep = chess.square_file(board.ep_square) + 1 if board.ep_square is not None and board.has_legal_en_passant() else 0
    return toks, castle, ep


def encode_move(board: chess.Board, move: chess.Move) -> int:
    """from*64+to in the mover's view (promotions share the from-to slot; queen assumed)."""
    return pov_square(move.from_square, board.turn) * 64 + pov_square(move.to_square, board.turn)


def decode_move(board: chess.Board, idx: int) -> chess.Move | None:
    fr, to = divmod(int(idx), 64)
    fr, to = pov_square(fr, board.turn), pov_square(to, board.turn)
    for mv in board.legal_moves:
        if mv.from_square == fr and mv.to_square == to and (mv.promotion in (None, chess.QUEEN)):
            return mv
    return None


# ── record builders (run in worker processes) ────────────────────────────────


def normalize_line(board: chess.Board, uci: list[str]) -> list[str]:
    """Standard UCI for a line, stopping at the first illegal move. Lichess writes some
    castles king-takes-rook (e8h8); python-chess accepts both, our move encoding must not."""
    b = board.copy(stack=False)
    out = []
    for u in uci:
        try:
            mv = b.parse_uci(u)
        except ValueError:
            break
        out.append(mv.uci())
        b.push(mv)
    return out


def _pick_eval(rec: dict) -> dict | None:
    """The eval with the most PVs (ties: deepest)."""
    evs = rec.get("evals") or []
    if not evs:
        return None
    return max(evs, key=lambda e: (len(e.get("pvs") or []), e.get("depth", 0)))


def _empty_vec() -> list[float]:
    return [0.0] * len(C.KEYS)


def _facts(board: chess.Board, uci: str) -> list[float]:
    f = C.move_facts(board, chess.Move.from_uci(uci))
    return [f[k] for k in FACT_KEYS]


def _common(board: chess.Board, moves: list[tuple[str, float]], best_line: list[str], alt_line: list[str]) -> dict:
    toks, castle, ep = encode_board(board)
    legal = sorted(encode_move(board, m) for m in board.legal_moves)[:MAX_LEGAL]
    root = C.static(board)
    rv = C.vector(root)
    pov = board.turn
    d_best = C.vector(C.delta(root, C.line_end_concepts(board, best_line, pov, LINE_PLIES))) if best_line else _empty_vec()
    d_alt = C.vector(C.delta(root, C.line_end_concepts(board, alt_line, pov, LINE_PLIES))) if alt_line else _empty_vec()
    wbest = max(w for _, w in moves)
    pol = [(encode_move(board, chess.Move.from_uci(u)), math.exp((w - wbest) / POLICY_TAU)) for u, w in moves]
    z = sum(w for _, w in pol)
    pol = [(i, w / z) for i, w in pol][:MAX_PV]
    return {
        "fen": board.fen(), "tokens": toks, "castle": castle, "ep": ep, "legal": legal,
        "pol_idx": [i for i, _ in pol] + [-1] * (MAX_PV - len(pol)),
        "pol_w": [w for _, w in pol] + [0.0] * (MAX_PV - len(pol)),
        "root": rv, "d_best": d_best, "d_alt": d_alt,
        "f_best": _facts(board, best_line[0]) if best_line else [0.0] * len(FACT_KEYS),
        "f_alt": _facts(board, alt_line[0]) if alt_line else [0.0] * len(FACT_KEYS),
        "has_best": int(bool(best_line)), "has_alt": int(bool(alt_line)),
        "best_line": " ".join(best_line), "alt_line": " ".join(alt_line),
        "moves": json.dumps([[u, round(w, 4)] for u, w in moves]),
        "split": structure_split(board),
    }


def featurize_eval(line: str) -> dict | None:
    try:
        rec = json.loads(line)
        ev = _pick_eval(rec)
        if ev is None or len(ev.get("pvs") or []) < 2:
            return None
        board = chess.Board(rec["fen"])
    except (ValueError, KeyError):
        return None
    if board.is_game_over() or not board.is_valid():
        return None
    moves, lines = [], []
    for pv in ev["pvs"][:MAX_PV]:
        uci = normalize_line(board, (pv.get("line") or "").split())
        if not uci:
            continue
        w = win_prob(pv.get("cp"), pv.get("mate"))
        moves.append((uci[0], w if board.turn == chess.WHITE else 1.0 - w))
        lines.append(uci)
    if len(moves) < 2 or len({u for u, _ in moves}) != len(moves):
        return None
    out = _common(board, moves, lines[0], lines[1])
    out.update(src=0, value=moves[0][1], value_alt=moves[1][1], depth=int(ev.get("depth", 0)), themes="",
               rating=0)
    return out


def featurize_puzzle(row: list[str]) -> dict | None:
    """Puzzle position = after the opponent's setup move; best line = the solution."""
    try:
        _pid, fen, moves_s, rating, *_rest = row
        themes = row[7]
        board = chess.Board(fen)
        uci = moves_s.split()
        board.push(chess.Move.from_uci(uci[0]))
    except (ValueError, IndexError):
        return None
    sol = normalize_line(board, uci[1:])
    if not sol or board.is_game_over():
        return None
    out = _common(board, [(sol[0], 1.0)], sol, [])
    out.update(src=1, value=float("nan"), value_alt=float("nan"), depth=0, themes=themes, rating=int(rating))
    return out


# ── streaming ────────────────────────────────────────────────────────────────


def _zstd_lines(path: Path) -> Iterator[str]:
    import zstandard

    with open(path, "rb") as fh:
        reader = zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(fh, read_size=1 << 20)
        text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        try:
            yield from text
        except zstandard.ZstdError:  # truncated head download: stop at the cut
            return


def eval_lines(path: Path = EVAL_FILE) -> Iterator[str]:
    for ln in _zstd_lines(path):
        if ln.endswith("\n"):
            yield ln


def puzzle_rows(path: Path = PUZZLE_FILE) -> Iterator[list[str]]:
    rows = csv.reader(_zstd_lines(path))
    next(rows, None)  # header
    yield from rows


# ── shard writing ────────────────────────────────────────────────────────────

ARRAY_FIELDS = {  # name -> numpy dtype
    "tokens": "int8", "castle": "int8", "ep": "int8", "pol_idx": "int16", "pol_w": "float32",
    "root": "float32", "d_best": "float32", "d_alt": "float32", "f_best": "float32", "f_alt": "float32",
    "has_best": "int8", "has_alt": "int8", "value": "float32", "value_alt": "float32", "src": "int8",
    "split": "int8", "depth": "int16", "rating": "int16",
}
STR_FIELDS = ("fen", "best_line", "alt_line", "moves", "themes")


def write_shard(recs: list[dict], path: Path) -> None:
    import numpy as np

    arrays = {k: np.asarray([r[k] for r in recs], dtype=dt) for k, dt in ARRAY_FIELDS.items()}
    for k in STR_FIELDS:
        arrays[k] = np.asarray([r[k] for r in recs], dtype=str)
    flat = [i for r in recs for i in r["legal"]]
    arrays["legal_idx"] = np.asarray(flat, dtype=np.int16)
    arrays["legal_off"] = np.cumsum([0] + [len(r["legal"]) for r in recs]).astype(np.int64)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def _batched(it, n):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf


def _work_eval(lines: list[str]) -> list[dict]:
    return [r for r in map(featurize_eval, lines) if r is not None]


def _work_puzzle(rows: list[list[str]]) -> list[dict]:
    return [r for r in map(featurize_puzzle, rows) if r is not None]


def build(kind: str, n_target: int, out_dir: Path = DATA_DIR, workers: int = 9, chunk: int = 2000,
          shard_size: int = 50_000, log=print) -> int:
    """Stream `kind` ('eval' | 'puzzle') through the featurizer until n_target records."""
    src = eval_lines() if kind == "eval" else puzzle_rows()
    fn = _work_eval if kind == "eval" else _work_puzzle
    kept: list[dict] = []
    n_written = shard = 0
    with mp.Pool(workers) as pool:
        for recs in pool.imap(fn, _batched(src, chunk)):
            kept.extend(recs)
            while len(kept) >= shard_size:
                write_shard(kept[:shard_size], out_dir / f"{kind}_{shard:03d}.npz")
                n_written += shard_size
                kept = kept[shard_size:]
                shard += 1
                log(f"[data] {kind}: {n_written} written")
            if n_written + len(kept) >= n_target:
                break
        pool.terminate()
    rest = kept[: max(0, n_target - n_written)]
    if rest:
        write_shard(rest, out_dir / f"{kind}_{shard:03d}.npz")
        n_written += len(rest)
    log(f"[data] {kind}: done, {n_written} records")
    return n_written


def load(kinds: tuple[str, ...] = ("eval", "puzzle"), out_dir: Path = DATA_DIR) -> dict:
    """Concatenate all shards of the given kinds into one dict of arrays."""
    import numpy as np

    parts: dict[str, list] = {}
    legal_parts, off_parts, base = [], [], 0
    for kind in kinds:
        for p in sorted(out_dir.glob(f"{kind}_*.npz")):
            z = np.load(p)
            for k in list(ARRAY_FIELDS) + list(STR_FIELDS):
                parts.setdefault(k, []).append(z[k])
            legal_parts.append(z["legal_idx"])
            off_parts.append(z["legal_off"][:-1] + base)
            base += len(z["legal_idx"])
    out = {k: np.concatenate(v) for k, v in parts.items()}
    out["legal_idx"] = np.concatenate(legal_parts)
    out["legal_off"] = np.concatenate(off_parts + [np.asarray([base])])
    return out


def delta_scale(data: dict) -> dict[str, float]:
    """Per-concept std of (Δbest − Δalt) on the train split: the salience z-score scale."""
    import numpy as np

    m = (data["split"] == 0) & (data["has_alt"] == 1)
    diff = data["d_best"][m] - data["d_alt"][m]
    std = diff.std(axis=0)
    return {k: float(max(s, 0.25)) for k, s in zip(C.KEYS, std)}
