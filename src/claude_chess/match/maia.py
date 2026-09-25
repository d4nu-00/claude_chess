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


# ── Maia-3 (CSSLab, ICLR 2026 "Chessformer") ───────────────────────────────
#
# One transformer conditioned on a continuous Elo (0..5000, interpolated between two
# learned embeddings), instead of Maia-1's nine separate nets. Installed as a separate
# uv tool so torch stays out of this project's venv:
#
#     uv tool install --python 3.12 git+https://github.com/CSSLab/maia3
#
# Weights download from Hugging Face (UofTCSSLab/Maia3-{5M,23M,79M}) on first use.
# Default temperature 0 = argmax, matching Maia-1 + lc0 nodes=1 (top policy move); the
# upstream default is 1.0 (sampling), which is more human-like but noisier.
# Elo far outside the human training data is extrapolation — calibrate before trusting it.

MAIA3_PATH = os.environ.get("MAIA3_PATH") or shutil.which("maia3-uci") or os.path.expanduser(
    "~/.local/bin/maia3-uci")
MAIA3_MODELS = ("maia3-5m", "maia3-23m", "maia3-79m")
MAIA3_START_TIMEOUT = 600  # first run downloads weights


class Maia3Player:
    """Maia-3 at a given Elo, policy-only (nodes=1), via its own UCI wrapper."""

    def __init__(self, elo: int, model: str = "maia3-23m", temperature: float = 0.0,
                 device: str | None = None, path: str | None = None):
        self._engine: chess.engine.SimpleEngine | None = None
        if model not in MAIA3_MODELS:
            raise ValueError(f"unknown Maia-3 model {model!r}; have {MAIA3_MODELS}")
        if not 0 <= elo <= 5000:
            raise ValueError("Maia-3 Elo must be within 0..5000")
        self.elo, self.model, self.temperature = elo, model, temperature
        self.device = device or os.environ.get("MAIA3_DEVICE", "mps")
        self.path = path or MAIA3_PATH
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"maia3-uci not found at {self.path}. Install with:\n"
                                    "uv tool install --python 3.12 git+https://github.com/CSSLab/maia3")
        size = model.removeprefix("maia3-")
        self.name = f"maia3-{elo}" + ("" if size == "23m" else f"({size})") + \
                    ("" if temperature == 0 else f"[T{temperature:g}]")

    def _get_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            cmd = [self.path, "--model", self.model, "--use-uci-history", "--elo", str(self.elo),
                   "--temperature", str(self.temperature), "--device", self.device]
            if self.device == "cpu":
                cmd.append("--no-use-amp")
            self._engine = chess.engine.SimpleEngine.popen_uci(cmd, timeout=MAIA3_START_TIMEOUT)
        return self._engine

    def choose_move(self, board: chess.Board) -> MoveDecision:
        t0 = _time.monotonic()
        # --use-uci-history: the engine sees the move list, so pass the full game board.
        res = self._get_engine().play(board, chess.engine.Limit(nodes=1))
        mv = res.move
        return MoveDecision(move=mv, san=board.san(mv) if mv else None,
                            seconds=_time.monotonic() - t0,
                            forfeit_reason=None if mv else "engine returned no move")

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def __del__(self):
        self.close()
