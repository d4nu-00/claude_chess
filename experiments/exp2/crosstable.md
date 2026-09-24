# Experiment `exp2` — Claude vs Maia

Cell = score / games (W-D-L) from Claude's side.

| config | maia-1100 | maia-1500 | maia-1900 | total | score % | Elo (95% CI) | ACPL | cost $ | $/game | $/move | s/move |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness-ctx3 | 3.5/4 (3-1-0) | 1/4 (1-0-3) | 3/4 (3-0-1) | 7.5/12 | 62% | 1659 (1321–2043) | 72 | 4.46 | 0.372 | 0.0093 | 12.4 |
| haiku-naive | 0/4 (0-0-4) | 0/4 (0-0-4) | 0/4 (0-0-4) | 0/12 | 0% | -10 (-10–-10) | 223 | 0.22 | 0.018 | 0.0018 | 3.7 |

## Harness vs no harness

| comparison A vs B (levels both played) | Δ mean score | permutation p (stratified) | Elo naive → harness | LR χ² | LR p | ACPL naive → harness | Mann-Whitney p | $/game naive → harness | extra $ per extra point |
|---|---|---|---|---|---|---|---|---|---|
| haiku ctx3 (1100,1500,1900; 12 vs 12 games) | +0.62 | 0.0025 | -10 → 1659 | 20.7 | 5.5e-06 | 223 → 72 | 0.00028 | 0.018 → 0.372 | 0.57 |

## Reliance on the Python tactical search (harness moves)

| config | moves | Claude's #1 played | #1 overruled by search | played move proposed by Claude | played move added by search | fail-low (all Claude ideas lose material) | decided without Claude's positional call |
|---|---|---|---|---|---|---|---|
| haiku-harness-ctx3 | 479 | 65% | 16% | 95% | 2% | 15% | 26% |

Notes: Elo is a performance rating against Maia's *nominal* ratings (Lichess-ish scale, see wiki maia-calibration); boundary values (0 or 3200) mean every game was lost/won. Aborted games (LLM outages) are excluded. Games may end by resign adjudication (Stockfish referee, never inside a player's decision).
