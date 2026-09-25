# Experiment `exp3` — Claude vs Maia

Cell = score / games (W-D-L) from Claude's side.

| config | maia-1100 | maia-1500 | maia-1900 | total | score % | Elo (95% CI) | ACPL | cost $ | $/game | $/move | s/move |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness-ctx4 | 3/4 (2-2-0) | 1/4 (1-0-3) | 2/4 (1-2-1) | 6/12 | 50% | 1500 (1233–1833) | 64 | 4.52 | 0.377 | 0.0085 | 9.7 |

## Harness vs no harness

| comparison A vs B (levels both played) | Δ mean score | permutation p (stratified) | Elo naive → harness | LR χ² | LR p | ACPL naive → harness | Mann-Whitney p | $/game naive → harness | extra $ per extra point |
|---|---|---|---|---|---|---|---|---|---|

## Reliance on the Python tactical search (harness moves)

| config | moves | Claude's #1 played | #1 overruled by search | played move proposed by Claude | played move added by search | fail-low (all Claude ideas lose material) | decided without Claude's positional call |
|---|---|---|---|---|---|---|---|
| haiku-harness-ctx4 | 480 | 55% | 17% | 92% | 4% | 18% | 21% |

Notes: Elo is a performance rating against Maia's *nominal* ratings (Lichess-ish scale, see wiki maia-calibration); boundary values (0 or 3200) mean every game was lost/won. Aborted games (LLM outages) are excluded. Games may end by resign adjudication (Stockfish referee, never inside a player's decision).
