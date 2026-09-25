"""Endgame tablebase lookup (≤7 pieces): local Syzygy files first, then the Lichess API.

"Go look it up": in these endings the result is known exactly, so we give it to Claude
instead of asking it to calculate. Sources, in order:
  1. Syzygy files in $SYZYGY_PATH or engines/syzygy (python-chess `chess.syzygy`).
  2. https://tablebase.lichess.ovh (set CLAUDE_CHESS_TB_ONLINE=0 to disable). One failed
     request disables it for the rest of the process (sandboxes often block the host).
Results are memoised per position. WDL is from the SIDE TO MOVE's point of view.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import chess

from .paths import REPO_ROOT

MAX_PIECES = 7
LICHESS_URL = "https://tablebase.lichess.ovh/standard?fen="
_RANK = {"loss": -2, "blessed-loss": -1, "maybe-loss": -2, "draw": 0,
         "cursed-win": 1, "maybe-win": 2, "win": 2}


@dataclass
class TBResult:
    wdl: int  # -2 loss .. 0 draw .. 2 win (±1 = cursed/blessed: a draw under the 50-move rule)
    dtz: int | None
    moves: list[tuple[str, int, int | None]] = field(default_factory=list)  # (san, mover's wdl, dtz)
    source: str = ""

    @property
    def verdict(self) -> str:
        return {2: "WIN", 1: "draw (win only without the 50-move rule)", 0: "DRAW",
                -1: "draw (loss only without the 50-move rule)", -2: "LOSS"}[self.wdl]

    def best_moves(self) -> list[str]:
        """Moves that keep the best result; for wins fastest (smallest |DTZ|) first."""
        if not self.moves:
            return []
        top = max(w for _, w, _ in self.moves)
        best = [(s, d) for s, w, d in self.moves if w == top]
        if top > 0:
            best.sort(key=lambda t: abs(t[1]) if t[1] is not None else 999)
        elif top < 0:
            best.sort(key=lambda t: -(abs(t[1]) if t[1] is not None else 0))
        return [s for s, _ in best]


_memo: dict[str, TBResult | None] = {}
_lock = threading.Lock()
_online_ok = os.environ.get("CLAUDE_CHESS_TB_ONLINE", "1") != "0"
_local = None
_local_tried = False


def _local_tb():
    global _local, _local_tried
    if _local_tried:
        return _local
    _local_tried = True
    path = os.environ.get("SYZYGY_PATH") or os.path.join(REPO_ROOT, "engines", "syzygy")
    if os.path.isdir(path) and any(f.endswith(".rtbw") for f in os.listdir(path)):
        import chess.syzygy
        _local = chess.syzygy.open_tablebase(path)
    return _local


def _probe_local(board: chess.Board) -> TBResult | None:
    tb = _local_tb()
    if tb is None:
        return None
    try:
        wdl = tb.probe_wdl(board)
        dtz = tb.probe_dtz(board)
        moves = []
        for mv in board.legal_moves:
            b = board.copy(stack=False)
            b.push(mv)
            if b.is_checkmate():
                moves.append((board.san(mv), 2, 1))
                continue
            moves.append((board.san(mv), -tb.probe_wdl(b), -tb.probe_dtz(b)))
        return TBResult(wdl, dtz, moves, "syzygy")
    except (KeyError, chess.syzygy.MissingTableError):  # type: ignore[attr-defined]
        return None


def _probe_online(board: chess.Board) -> TBResult | None:
    global _online_ok
    if not _online_ok:
        return None
    url = LICHESS_URL + urllib.parse.quote(board.fen().replace(" ", "_"), safe="_/")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "claude_chess"}),
                                    timeout=4) as r:
            data = json.loads(r.read().decode())
    except Exception:
        _online_ok = False  # blocked / offline: don't pay the timeout on every move
        return None
    return parse_lichess(data)


def parse_lichess(data: dict) -> TBResult | None:
    cat = data.get("category")
    if cat not in _RANK:
        return None
    moves = []
    for m in data.get("moves") or []:
        # A move's category is from the OPPONENT's view (the side to move after it).
        mc = m.get("category")
        if mc not in _RANK:
            continue
        dtz = m.get("dtz")
        moves.append((m.get("san", m.get("uci", "?")), -_RANK[mc], -dtz if isinstance(dtz, int) else None))
    return TBResult(_RANK[cat], data.get("dtz"), moves, "lichess")


def probe(board: chess.Board) -> TBResult | None:
    if chess.popcount(board.occupied) > MAX_PIECES or board.castling_rights:
        return None
    key = board.fen()
    with _lock:
        if key in _memo:
            return _memo[key]
    res = _probe_local(board) or _probe_online(board)
    with _lock:
        _memo[key] = res
    return res
