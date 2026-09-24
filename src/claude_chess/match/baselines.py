"""Reference opponents: Stockfish (strength-limited) and a uniform random mover.

Each StockfishPlayer owns its own engine process — never share one across threads.
"""

from __future__ import annotations

import os
import random
import shutil
import time as _time

import chess
import chess.engine

from claude_chess.types import MoveDecision

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish") or "/opt/homebrew/bin/stockfish"
MIN_UCI_ELO = 1320  # Stockfish 17's UCI_Elo floor; use skill level for weaker play


def open_stockfish(path: str | None = None) -> chess.engine.SimpleEngine:
    eng = chess.engine.SimpleEngine.popen_uci(path or STOCKFISH_PATH)
    eng.configure({"Threads": 1, "Hash": 16})
    return eng


class StockfishPlayer:
    def __init__(self, elo: int | None = None, skill: int | None = None, time: float = 0.05,
                 path: str | None = None):
        if elo is not None and elo < MIN_UCI_ELO:
            raise ValueError(f"UCI_Elo min is {MIN_UCI_ELO}; use skill=0..20 for weaker play")
        if skill is not None and not 0 <= skill <= 20:
            raise ValueError("skill must be 0..20")
        self.elo, self.skill, self.time, self.path = elo, skill, time, path
        if elo is not None:
            self.name = f"stockfish(elo{elo})"
        elif skill is not None:
            self.name = f"stockfish(skill{skill})"
        else:
            self.name = "stockfish(full)"
        self._engine: chess.engine.SimpleEngine | None = None

    def _get_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            eng = open_stockfish(self.path)
            if self.elo is not None:
                eng.configure({"UCI_LimitStrength": True, "UCI_Elo": self.elo})
            elif self.skill is not None:
                eng.configure({"Skill Level": self.skill})
            self._engine = eng
        return self._engine

    def choose_move(self, board: chess.Board) -> MoveDecision:
        t0 = _time.monotonic()
        res = self._get_engine().play(board, chess.engine.Limit(time=self.time))
        mv = res.move
        san = board.san(mv) if mv is not None else None
        return MoveDecision(move=mv, san=san, seconds=_time.monotonic() - t0,
                            forfeit_reason=None if mv else "engine returned no move")

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def __del__(self):  # best effort
        self.close()


class RandomPlayer:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.name = "random"

    def choose_move(self, board: chess.Board) -> MoveDecision:
        moves = list(board.legal_moves)
        if not moves:
            return MoveDecision(move=None, san=None, forfeit_reason="no legal moves")
        mv = self.rng.choice(moves)
        return MoveDecision(move=mv, san=board.san(mv))
