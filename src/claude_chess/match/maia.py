"""Maia (CSSLab human-like) opponents, via lc0's UCI interface.

Maia is a set of neural nets trained to *imitate* human moves at a target Lichess
rating, rather than to play strong chess. Standard Maia usage is raw policy-head
output with **no search**: `Limit(nodes=1)` makes lc0 evaluate the root once and
play the top policy move, instead of running its normal MCTS search. Using more
nodes turns it into a (much stronger, no-longer-human-like) engine, so callers
should not raise `nodes` above 1 for calibration purposes.

Weights are NOT vendored (see `engines/` in .gitignore); download them with:

    mkdir -p engines/maia
    for r in 1100 1200 1300 1400 1500 1600 1700 1800 1900; do
      curl -L -o engines/maia/maia-$r.pb.gz \
        https://github.com/CSSLab/maia-chess/releases/download/v1.0/maia-$r.pb.gz
    done

One engine process per `MaiaPlayer` instance; `close()` (or `__del__`) quits it.
`Threads=1` and a small `NNCacheSize` keep many parallel games (`--parallel N`)
from oversubscribing the CPU / GPU backend — see [[maia-calibration]].
"""

from __future__ import annotations

import os
import shutil
import time as _time

import chess
import chess.engine

from claude_chess.match.baselines import ENGINE_START_TIMEOUT
from claude_chess.types import MoveDecision

LC0_PATH = os.environ.get("LC0_PATH") or shutil.which("lc0") or "/opt/homebrew/bin/lc0"

# Repo root: src/claude_chess/match/maia.py -> src/claude_chess/match -> src/claude_chess -> src -> repo root
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEIGHTS_DIR = os.path.join(_REPO_ROOT, "engines", "maia")

# Weights shipped by CSSLab/maia-chess v1.0.
AVAILABLE_RATINGS = (1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900)

DOWNLOAD_CMD = (
    "mkdir -p engines/maia && for r in 1100 1200 1300 1400 1500 1600 1700 1800 1900; do "
    "curl -L -o engines/maia/maia-$r.pb.gz "
    "https://github.com/CSSLab/maia-chess/releases/download/v1.0/maia-$r.pb.gz; done"
)


def weights_path(rating: int, weights_dir: str | None = None) -> str:
    d = weights_dir or WEIGHTS_DIR
    return os.path.join(d, f"maia-{rating}.pb.gz")


class MaiaPlayer:
    """A Maia weight class played through lc0, with no search (policy-only)."""

    def __init__(self, rating: int, nodes: int = 1, path: str | None = None,
                 weights_dir: str | None = None):
        self._engine: chess.engine.SimpleEngine | None = None  # set first so __del__ is always safe
        if rating not in AVAILABLE_RATINGS:
            raise ValueError(f"no Maia weights for rating {rating}; have {AVAILABLE_RATINGS}")
        self.rating = rating
        self.nodes = nodes
        self.path = path or LC0_PATH
        self.weights = weights_path(rating, weights_dir)
        if not os.path.exists(self.weights):
            raise FileNotFoundError(
                f"Maia weights not found at {self.weights}. Download with:\n{DOWNLOAD_CMD}")
        self.name = f"maia-{rating}"

    def _get_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            eng = chess.engine.SimpleEngine.popen_uci([self.path, f"--weights={self.weights}"],
                                                      timeout=ENGINE_START_TIMEOUT)
            # Threads=1 + a small cache: many parallel games must not oversubscribe the CPU/GPU.
            try:
                eng.configure({"Threads": 1, "NNCacheSize": 200000})
            except chess.engine.EngineError:
                eng.configure({"Threads": 1})
            self._engine = eng
        return self._engine

    def choose_move(self, board: chess.Board) -> MoveDecision:
        t0 = _time.monotonic()
        res = self._get_engine().play(board, chess.engine.Limit(nodes=self.nodes))
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
