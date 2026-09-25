# Experiment `exp1` — Claude vs Maia

Cell = score / games (W-D-L) from Claude's side.

| config | maia-1100 | maia-1300 | maia-1500 | maia-1700 | maia-1900 | total | score % | Elo (95% CI) | ACPL | cost $ | $/game | $/move | s/move |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness | 2/4 (2-0-2) | – | 2.5/4 (2-1-1) | – | 2/4 (2-0-2) | 6.5/12 | 54% | 1552 (1153–1960) | 72 | 3.75 | 0.313 | 0.0087 | 15.1 |
| haiku-naive | 0/4 (0-0-4) | – | 0/4 (0-0-4) | – | 0/4 (0-0-4) | 0/12 | 0% | -10 (-10–-10) | 201 | 0.24 | 0.020 | 0.0018 | 4.5 |
| sonnet-harness | 3/4 (2-2-0) | 2.5/4 (2-1-1) | 2.5/4 (2-1-1) | 1.5/4 (1-1-2) | 1/4 (0-2-2) | 10.5/20 | 52% | 1528 (1332–1716) | 46 | 26.33 | 1.317 | 0.0345 | 18.7 |
| sonnet-naive | 0/4 (0-0-4) | – | 0/4 (0-0-4) | – | 0/4 (0-0-4) | 0/12 | 0% | -10 (-10–-10) | 115 | 1.57 | 0.131 | 0.0077 | 4.2 |

## Harness vs no harness

| model (levels both arms played) | Δ mean score | permutation p (stratified) | Elo naive → harness | LR χ² | LR p | ACPL naive → harness | Mann-Whitney p | $/game naive → harness | extra $ per extra point |
|---|---|---|---|---|---|---|---|---|---|
| haiku (1100,1500,1900; 12 vs 12 games) | +0.54 | 0.0119 | -10 → 1552 | 16.3 | 5.3e-05 | 201 → 72 | 0.00014 | 0.020 → 0.313 | 0.54 |
| sonnet (1100,1500,1900; 12 vs 12 games) | +0.54 | 0.0010 | -10 → 1552 | 16.3 | 5.3e-05 | 115 → 46 | 0.00017 | 0.131 → 1.198 | 1.97 |

## Reliance on the Python tactical search (harness moves)

| config | moves | Claude's #1 played | #1 overruled by search | played move proposed by Claude | played move added by search | fail-low (all Claude ideas lose material) | decided without Claude's positional call |
|---|---|---|---|---|---|---|---|
| haiku-harness | 432 | 41% | 42% | 85% | 13% | 19% | 39% |
| sonnet-harness | 764 | 48% | 27% | 93% | 5% | 7% | 23% |

Notes: Elo is a performance rating against Maia's *nominal* ratings (Lichess-ish scale, see wiki maia-calibration); boundary values (0 or 3200) mean every game was lost/won. Aborted games (LLM outages) are excluded. Games may end by resign adjudication (Stockfish referee, never inside a player's decision).
