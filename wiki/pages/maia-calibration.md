# Maia calibration (maia agent)

Code: `src/claude_chess/match/maia.py`, `src/claude_chess/match/calibration.py`,
`tests/test_maia.py`. CLI spec parsing in `src/claude_chess/cli.py`.

## What Maia is

[Maia](https://github.com/CSSLab/maia-chess) (CSSLab) is a set of Leela Chess Zero
(`lc0`) nets trained to **imitate human moves at a target Lichess rating**, not to
play the strongest chess possible. That makes it useful as a *human-like, rating-
labelled* opponent: unlike Stockfish at a matched Elo (which is strong-but-handicapped),
Maia's blunders and style are meant to resemble an actual human of that rating.

Standard Maia usage is **policy only, no search**: run it through `lc0` with
`go nodes 1` (`chess.engine.Limit(nodes=1)`), which makes lc0 evaluate the root
position once and play the top policy-head move, rather than running its normal
MCTS search. This is what `MaiaPlayer` does by default (`nodes=1`). Raising `nodes`
turns Maia into a much stronger, no-longer-human-like engine (search corrects the
net's human-like errors) — don't do that for calibration purposes.

## Getting the weights

`engines/` is gitignored (weights are ~1.2-1.3MB each but the dir shouldn't be
vendored). Download all 9 weight classes from the CSSLab v1.0 GitHub release:

```
mkdir -p engines/maia
for r in 1100 1200 1300 1400 1500 1600 1700 1800 1900; do
  curl -L -o engines/maia/maia-$r.pb.gz \
    https://github.com/CSSLab/maia-chess/releases/download/v1.0/maia-$r.pb.gz
done
```

Verify: `gzip -t engines/maia/*.pb.gz` (integrity) and file size should match the
release asset (`maia-1100.pb.gz` = 1,313,193 bytes; `maia-1500.pb.gz` = 1,258,199;
`maia-1900.pb.gz` = 1,262,607, checked 2026-09-24). `lc0 --weights=...` loading
successfully and returning a move under `Limit(nodes=1)` is the real smoke test —
run one manually if in doubt (see `src/claude_chess/match/maia.py` docstring).

## CLI usage

```
uv run claude-chess match --white maia:1100 --black maia:1900 --games 4 --parallel 4
uv run claude-chess match --white stockfish:1320 --black maia:1500 --games 2 --parallel 2
```

Spec: `maia:RATING` for `RATING` in `1100, 1200, ..., 1900` (step 100 — one weight
file per class). Player name is `maia-<rating>` (e.g. `maia-1500`).

`MaiaPlayer` opens its own `lc0` process (`Threads=1`, small `NNCacheSize`) per
instance, same one-engine-per-player-per-game pattern as `StockfishPlayer` in
[[match-and-analysis]] — this matters because `--parallel N` runs N games (and
therefore N engine processes) concurrently; `Threads=1` keeps each of them from
grabbing more CPU than its share.

## Weight -> Lichess rating table

Only three weight classes are deployed as public Lichess bots; those three are the
only ones with a *measured* rating. Fetched 2026-09-24 via
`https://lichess.org/api/user/<bot>` (`perf.<speed>.rating`); bot-to-weight mapping
confirmed from the maia-chess README ("maia1 is targeting ELO 1100, maia5 is
targeting ELO 1500, maia9 is targeting ELO 1900").

| Maia weight | Lichess bot | blitz | rapid | classical | games (blitz) |
|---|---|---|---|---|---|
| maia-1100 | [maia1](https://lichess.org/@/maia1) | 1387 | 1494 | 1651 | 438,000 |
| maia-1500 | [maia5](https://lichess.org/@/maia5) | 1453 | 1625 | 1720 | — |
| maia-1900 | [maia9](https://lichess.org/@/maia9) | 1612 | 1773 | 1731 | — |

The other six weight classes (1200, 1300, 1400, 1600, 1700, 1800) are real nets but
were never deployed as bots, so there is no ground-truth Lichess rating for them.
`calibration.interpolated_rating(weight, pool)` linearly interpolates between the
two nearest measured anchors and returns `estimated=True` — **treat these as a rough
guess, not a measurement.** The relationship is not obviously linear even between
the three anchors we do have: rapid gains ~131 points over the 1100->1500 weight
range but ~148 over 1500->1900, while classical gains ~69 over 1100->1500 but only
~11 over 1500->1900 (maia9's classical rating, 1731, is barely above maia5's, 1720,
despite the 400-point weight gap and a much bigger rapid/blitz gain over the same
range) — so a linearly-interpolated classical number for an untested weight is
especially unreliable.

## Caveats

- **Lichess rating != FIDE rating.** Online blitz/rapid pools run inflated relative
  to FIDE at most levels; don't quote a Maia "rating" as if it were an OTB strength.
- **The bots are rated from games against humans**, at whatever time control humans
  chose to challenge them at (mostly blitz/rapid). That rating reflects "how Maia
  fares against the Lichess population", not an absolute skill measurement.
- **`nodes=1`, no search.** This is intentional (see above) but means MaiaPlayer is
  not "Stockfish-strength-limited-to-X" — it's a distinct, much more human-shaped
  error profile (typical human blunders/misses, not engine-style deep miscalculation).
- **Interpolated weight classes are an estimate**, not a measurement — see table
  above.
- **A performance rating from a handful of games against a single Maia weight is
  very noisy.** See below.

## Reading a performance rating

`calibration.performance_rating(results)` takes `[(opponent_rating, score), ...]`
(one entry per game; `score` is 1/0.5/0) and returns `(estimate, lo95, hi95)`, an
iterative (FIDE-style) performance rating: it solves for the rating `R` such that
the sum of Elo-expected scores against each `opponent_rating` equals the sum of
actual scores. A `0.5`-weight drawn pseudo-game against the average opponent rating
is mixed into the equation so a perfect (or zero) score gives a large-but-finite
estimate instead of +-infinity.

The 95% CI comes from the binomial standard error of the overall score fraction
(continuity-corrected), mapped through the Elo curve around the average opponent
rating. This treats games as independent identical trials, which is a simplification
(games against a fixed opponent and a fixed player are not perfectly independent,
and mixing opponents of different strength blurs "average opponent" as a single
reference point) — good enough for a ballpark, not for anything you'd publish
without more games.

### Sample-size warning: CI half-width for a 50%-score match vs a 1500-rated Maia

| games | estimate | 95% CI | half-width |
|---|---|---|---|
| 4 | 1500 | [702, 2298] | ~798 |
| 10 | 1500 | [1248, 1752] | ~252 |
| 40 | 1500 | [1389, 1611] | ~111 |

A 4-game match tells you almost nothing about performance rating (+-~800 Elo).
Even 40 games leaves +-~110 Elo of uncertainty. Run matches in batches of 20-40+
games per Maia weight before treating the estimate as meaningful, and prefer
several weight classes (a "performance vs. the whole Maia ladder") over a single
opponent.

## Maia-3 (added 2026-09-25)
CSSLab's Maia-3 ("Chessformer", ICLR 2026, github.com/CSSLab/maia3): one transformer
conditioned on a *continuous* Elo (0–5000, linear blend of two learned embeddings) instead
of nine separate nets. Spec: `maia3:ELO[:5m|23m|79m][:T]`, default 23M, temperature 0
(argmax, matching Maia-1 + lc0 nodes=1; upstream default T=1 samples). Installed as an
isolated uv tool (`uv tool install --python 3.12 git+https://github.com/CSSLab/maia3`) so
torch stays out of the project venv; weights auto-download from HF `UofTCSSLab/Maia3-23M`.
~3 s load, ~30–100 ms/move on MPS.

Sanity vs Maia-1 `maia:1900` (8 games each, argmax, 23M):

| Maia-3 Elo | score vs maia-1900 | Maia-3 ACPL |
|---|---|---|
| 1900 | 6.5/8 | 39.6 |
| 2300 | 6.5/8 (0 losses) | 34.7 |
| 2700 | 8/8 | 21.4 |

Takeaways: the Elo knob is a real strength gradient; Maia-3 is stronger than Maia-1 *at the
same nominal Elo* (partly argmax of a better policy); nominal values above the human training
range are extrapolation — the "2700" label is NOT a Lichess/FIDE rating. No Lichess bot
anchors Maia-3 yet; its scale is only relative to maia-1900 here. Runs:
`runs/*_maia3-{1900,2300,2700}-vs-maia1900`.
