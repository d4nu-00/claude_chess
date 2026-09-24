# Experiment `exp1` — Claude vs Maia

Cell = score / games (W-D-L) from Claude's side.

| config | maia-1100 | maia-1300 | maia-1500 | maia-1700 | maia-1900 | total | score % | Elo (95% CI) | ACPL | cost $ | $/game | $/move | s/move |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness | 1/3 (1-0-2) | – | 2.5/4 (2-1-1) | – | 2/4 (2-0-2) | 5.5/11 | 50% | 1545 (1066–1943) | 76 | 3.57 | 0.324 | 0.0087 | 15.4 |
| haiku-naive | 0/4 (0-0-4) | – | 0/4 (0-0-4) | – | 0/4 (0-0-4) | 0/12 | 0% | -10 (-10–-10) | 201 | 0.24 | 0.020 | 0.0018 | 4.5 |
| sonnet-harness | 3/4 (2-2-0) | 2.5/4 (2-1-1) | 2.5/4 (2-1-1) | 1.5/4 (1-1-2) | 1/4 (0-2-2) | 10.5/20 | 52% | 1528 (1332–1716) | 46 | 26.33 | 1.317 | 0.0345 | 18.7 |
| sonnet-naive | – | – | 0/2 (0-0-2) | – | 0/3 (0-0-3) | 0/5 | 0% | -10 (-10–-10) | 106 | 0.68 | 0.137 | 0.0077 | 4.8 |

## Harness vs no harness

| model (levels both arms played) | Δ mean score | permutation p (stratified) | Elo naive → harness | LR χ² | LR p | ACPL naive → harness | Mann-Whitney p | $/game naive → harness | extra $ per extra point |
|---|---|---|---|---|---|---|---|---|---|
| haiku (1100,1500,1900; 11 vs 12 games) | +0.50 | 0.0093 | -10 → 1545 | 15.6 | 8e-05 | 201 → 76 | 0.00022 | 0.020 → 0.324 | 0.61 |
| sonnet (1500,1900; 8 vs 5 games) | +0.44 | 0.0736 | -10 → 1640 | 4.3 | 0.039 | 106 → 48 | 0.0054 | 0.137 → 1.129 | 2.27 |

Notes: Elo is a performance rating against Maia's *nominal* ratings (Lichess-ish scale, see wiki maia-calibration); boundary values (0 or 3200) mean every game was lost/won. Aborted games (LLM outages) are excluded. Games may end by resign adjudication (Stockfish referee, never inside a player's decision).
