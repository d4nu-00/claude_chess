# Match and analysis (match agent)

Code: `src/claude_chess/match/{baselines,openings,runner,analysis}.py`, `src/claude_chess/cli.py`.

## How to run
```
uv run claude-chess match --white engine-ctx --black engine-noctx --games 8 --max-plies 160 \
    --model sonnet --depth 1 --candidates 4 --replies 2 --parallel 4 --label ctx-ablation
uv run claude-chess match --white naive --black stockfish:1320 --games 4
uv run claude-chess match --white random --black stockfish-skill:0 --games 2 --no-analysis
uv run claude-chess analyze runs/20260924_204429_ctx-ablation     # (re)analyse
uv run claude-chess context "1. e4 e5 2. Nf3 Nc6"                 # or a FEN
```
Specs: `naive | engine-ctx | engine-noctx | stockfish:ELO | stockfish-skill:N | stockfish | random`.
`--white` is player A, `--black` player B; **colours alternate** (A is White in games 0,2,4…).
Openings: each of 8 balanced starts (Ruy Lopez, Italian, Najdorf, French, Caro-Kann, QGD,
KID, English; 6-8 plies) is used twice in a row, once per colour. `--no-openings` disables.
Other flags: `--no-legal-moves`, `--illegal-policy`, `--max-retries`, `--backend`,
`--sf-time` (Stockfish player s/move, default 0.05), `--analysis-depth` (default 12).

## Output (`runs/<YYYYmmdd_HHMMSS>_<label>/`)
- `meta.json` — config + player names.
- `decisions.jsonl` — one row per non-book move, **appended as played**: game, ply, fen
  (before move), player, color, san/uci, candidates (san, reason, prior, score_cp, line),
  illegal_attempts, calls, cost, seconds, forfeit_reason, note, own_eval.
- `games.pgn` / `games.jsonl` — appended when each game finishes. PGN headers include
  `Termination`, `BookPlies`, `Opening`; move comments carry own eval / illegal / cost.
- `summary.json`, `report.md`, `move_analysis.jsonl` — written by analysis.
A crash loses only the in-flight games' results; `analyze` ignores decisions of unfinished games.

## Termination / adjudication
checkmate, stalemate, insufficient, repetition (3-fold, claimed automatically), fifty,
forfeit, adjudication. **Forfeit** (`decision.move is None`, an exception in `choose_move`,
or an illegal move returned) = loss for the mover. **Ply cap** (`--max-plies`, counts book
plies too) -> Stockfish eval of final position (depth 16 / 1s): |eval| >= 300cp -> win for
that side, else draw. Termination string records the eval, e.g. `adjudication (ply cap 160, SF eval +322cp)`.

## Metrics (analysis.py, Stockfish depth 12 per position, book plies excluded)
- **CPL** per move = eval_before - eval_after, both from the mover's view, clamped [0,1000].
  Mate = ±10000 before clamping, so allowing/missing mate costs 1000.
- **ACPL** per player; **inaccuracy** 50-99, **mistake** 100-299, **blunder** >=300 cp.
- **illegal rate** = fraction of moves with >=1 illegal attempt; also illegal attempts/move.
- forfeits, LLM calls/move, total cost, avg seconds/move, W/D/L and score.
- **rough Elo** = 3100·exp(-0.01·ACPL) — crude heuristic, only for eyeballing.

## Gotchas
- Stockfish `UCI_Elo` floor is **1320**; weaker needs `stockfish-skill:0..20`. Skill 0 at
  0.05s still plays ~1200-1400-ish club level — nowhere near random.
- Every player is built fresh per game by its factory and closed afterwards, so Stockfish
  processes are never shared across `--parallel` threads. Adjudication/analysis open their own.
- If both specs produce the same name (e.g. random vs random) they get `#A`/`#B` suffixes.
- CPL from short/weak analysis is noisy: use >= depth 12 and many games before concluding.

## Gotcha: game id types differ between files (found 2026-09-24)
`move_analysis.jsonl` writes `"game": "7"` (string); `decisions.jsonl`, `traces.jsonl`,
`games.jsonl` write `7` (int). Any join must normalise with `int(...)` — otherwise joins
silently match nothing (empty labels, missing ACPL).

## Resign adjudication and experiment reports (added 2026-09-24)
- `--resign-cp N --resign-plies K`: a per-game Stockfish referee (depth 12 / 0.2 s per ply)
  ends the game once the eval stays beyond ±N for K plies (cutechess/TCEC style). Saves the
  long tail of decided games; never influences a player's move.
- `--opening-offset i`: start the opening rotation at i (vary openings across matches while
  keeping both arms of an experiment paired).
- `claude-chess report PREFIX --out experiments/PREFIX`: cross table (per Maia level), score,
  performance Elo (MLE + bootstrap CI), ACPL, cost ($, $/game, $/move), s/move, and
  harness-vs-naive tests (stratified permutation, likelihood ratio, Mann-Whitney on ACPL).
  Code: `match/stats.py`. Experiment driver: `scripts/exp_harness_vs_naive.sh`.
- Live dashboard: `uv run python scripts/live_status.py PREFIX --expected N --loop 20` rewrites
  `experiments/PREFIX/LIVE.md` + `live.html` (auto-refresh) with the cross table so far,
  % complete, API cost, ETA and in-progress games. No LLM calls.
