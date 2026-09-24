# Experiment `exp` — Claude vs Maia

Cell = score / games (W-D-L) from Claude's side.

| config | maia-1100 | maia-1300 | maia-1500 | maia-1700 | maia-1900 | total | score % | Elo (95% CI) | ACPL | cost $ | $/game | $/move | s/move |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness | 2/4 (2-0-2) | – | 2.5/4 (2-1-1) | – | 2/4 (2-0-2) | 6.5/12 | 54% | 1552 (1153–1960) | 72 | 3.75 | 0.313 | 0.0087 | 15.1 |
| haiku-harness-ctx3 | 3.5/4 (3-1-0) | – | 1/4 (1-0-3) | – | 3/4 (3-0-1) | 7.5/12 | 62% | 1659 (1321–2043) | 72 | 4.46 | 0.372 | 0.0093 | 12.4 |
| haiku-naive | 0/8 (0-0-8) | – | 0/8 (0-0-8) | – | 0/8 (0-0-8) | 0/24 | 0% | -10 (-10–-10) | 212 | 0.46 | 0.019 | 0.0018 | 4.1 |
| sonnet-harness | 3/4 (2-2-0) | 2.5/4 (2-1-1) | 2.5/4 (2-1-1) | 1.5/4 (1-1-2) | 1/4 (0-2-2) | 10.5/20 | 52% | 1528 (1332–1716) | 46 | 26.33 | 1.317 | 0.0345 | 18.7 |
| sonnet-naive | 0/4 (0-0-4) | – | 0/4 (0-0-4) | – | 0/4 (0-0-4) | 0/12 | 0% | -10 (-10–-10) | 115 | 1.57 | 0.131 | 0.0077 | 4.2 |

## Harness vs no harness

| comparison A vs B (levels both played) | Δ mean score | permutation p (stratified) | Elo naive → harness | LR χ² | LR p | ACPL naive → harness | Mann-Whitney p | $/game naive → harness | extra $ per extra point |
|---|---|---|---|---|---|---|---|---|---|
| haiku (1100,1500,1900; 12 vs 24 games) | +0.54 | 0.0004 | -10 → 1552 | 23.6 | 1.2e-06 | 212 → 72 | 6.9e-06 | 0.019 → 0.313 | 0.54 |
| haiku ctx3 (1100,1500,1900; 12 vs 24 games) | +0.62 | 0.0000 | -10 → 1659 | 29.5 | 5.5e-08 | 212 → 72 | 3.7e-05 | 0.019 → 0.372 | 0.56 |
| haiku ctx3 vs ctx2 (1100,1500,1900; 12 vs 12 games) | +0.08 | 0.8479 | 1552 → 1659 | 0.3 | 0.58 | 72 → 72 | 0.56 | 0.313 → 0.372 | 0.71 |
| sonnet (1100,1500,1900; 12 vs 12 games) | +0.54 | 0.0010 | -10 → 1552 | 16.3 | 5.3e-05 | 115 → 46 | 0.00017 | 0.131 → 1.198 | 1.97 |

## Reliance on the Python tactical search (harness moves)

| config | moves | Claude's #1 played | #1 overruled by search | played move proposed by Claude | played move added by search | fail-low (all Claude ideas lose material) | decided without Claude's positional call |
|---|---|---|---|---|---|---|---|
| haiku-harness | 432 | 41% | 42% | 85% | 13% | 19% | 39% |
| haiku-harness-ctx3 | 479 | 65% | 16% | 95% | 2% | 15% | 26% |
| sonnet-harness | 764 | 48% | 27% | 93% | 5% | 7% | 23% |

Notes: Elo is a performance rating against Maia's *nominal* ratings (Lichess-ish scale, see wiki maia-calibration); boundary values (0 or 3200) mean every game was lost/won. Aborted games (LLM outages) are excluded. Games may end by resign adjudication (Stockfish referee, never inside a player's decision).
