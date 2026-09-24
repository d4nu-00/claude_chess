# Running in the Claude Code cloud sandbox

The dev machine is a Mac (Stockfish/lc0 via Homebrew). Cloud sessions are fresh Linux
containers: nothing below persists between sessions, so redo it each time (~5 min).

## Setup that works (2026-09-24)
```
apt-get install -y stockfish libopenblas-dev libeigen3-dev ninja-build meson zlib1g-dev
export STOCKFISH_PATH=/usr/games/stockfish          # apt puts it in /usr/games, not on PATH
git clone --depth 1 --branch v0.31.2 https://github.com/LeelaChessZero/lc0.git /tmp/lc0
cd /tmp/lc0 && meson setup build/release --buildtype=release --wrap-mode=nodownload \
  -Dgtest=false -Dopencl=false -Dcudnn=false -Dplain_cuda=false -Ddx=false -Donednn=false \
  -Dblas=true -Dopenblas=true -Dmkl=false -Ddnnl=false -Dispc=false \
  && ninja -C build/release -j4 && cp build/release/lc0 /usr/local/bin/
# Maia weights (GitHub release downloads are allowed): see [[maia-calibration]]
```
- `--wrap-mode=nodownload` + apt Eigen is required: meson's wrapdb (wrapdb.mesonbuild.com)
  is **blocked** by the egress proxy (403), and lc0 otherwise tries to fetch Eigen there.
- `tests/test_maia.py::test_cli_spec_parses_maia` needs `maia-1900.pb.gz` present.

## Blocked hosts (egress policy)
- `tablebase.lichess.ovh`, `tablebase.sesse.net` → no tablebases in the sandbox; the
  prober disables itself after one failure (see [[context-builder]]). Works on the Mac.
- GitHub (clone + release assets) and `claude -p` work.

## Claude calls from the sandbox
- `claude -p` is authenticated in the container and bills the user's account — watch
  spend; use `--thinking 0` (see [[llm-backend]]).

## Agent gotchas
- Waiting on a match with `while pgrep -f "claude-chess match"` never ends: the waiter's
  own command line matches. Use a bracket pattern: `pgrep -f "[b]in/claude-chess match"`.
- `runs/` is gitignored; results persist via `db/games.sqlite` (commit it) and
  `wiki/pages/results.md`. Exported datasets go under `datasets/`.
