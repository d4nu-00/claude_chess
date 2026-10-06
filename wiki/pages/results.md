# Results

## 2026-10-04 — explainer round 2: one model that picks the move AND explains it
Hypotheses, predictions and details: [[explainer-hypotheses]]. GUI: `scripts/play.py`.
Joint model = Qwen3-1.7B LoRA choosing among the encoder's 6 candidates from verified text facts
(no engine in its input); trained on 2,000 Stockfish-move examples + 573 Claude ideas ×2.
Same 250 held-out cloud-eval + 250 puzzle positions for every row; paired McNemar.

| model | cloud-eval (explain / move-only) | puzzles (explain / move-only) | ideas sound (judge) |
|---|---|---|---|
| encoder instinct | 25.6% | 62.8% | – |
| A: idea→move, relations | 28.0 / 25.6 | 58.4 / 64.4 | 26% |
| D: A + tactical outcome per candidate | 29.2 / 30.4 | 68.0 / **75.2** | 25% |
| **E: D's input, move→idea** | **34.0** / 33.6 | **72.0** / 72.8 | 26% (52% when best) |
| E with depth-4 tactics (J6) | 34.8 / 34.8 | 73.2 / 74.8 | 28% (56% when best) |

- One-ply value lookahead on the encoder: refuted (puzzles 63% → 40-45%).
- Verified forcing-play outcomes are what let the LM beat its instinct (D vs A on puzzles +10.8,
  p<0.001). Writing the idea first hurts tactics (D: 68 vs 75, p=0.006); training move-first (E)
  removes the penalty → **decide, then explain**.
- Human game vs D: lost to a pawn fork the 2-ply search scored "material holds"; depth 4 sees it.
- Ideas are still the weak part (≈25% sound); move quality improved, explanations didn't.

## 2026-10-05 — explainer round 3: more explanation data (J7)
+2,000 Opus labels (batched 5/call, $40 notional, 3 session windows) → 2,550 teacher positions.
Same 500 positions + same 100 judged positions as round 2:

| model | cloud-eval / puzzles (explain) | ideas sound | ideas true | sound when best |
|---|---|---|---|---|
| E (573 labels) | 34.0 / 72.0 | 26% | 19% | 52% |
| E2 (+~600) | 32.8 / 74.0 | 37% | 21% | 57% |
| **E3 (+2,000)** | **34.8 / 76.0** | **39%** (p=0.035 vs E) | **28%** | **60%** |

More explanation labels make the ideas significantly better; moves unchanged within noise.

## 2026-10-03 — explainer v1: encoder, concept discovery, condensed-explanation student
Design: [[explainer-model]]; discovery: [[concept-discovery]]; reproduce: `experiments/explainer/README.md`.
Data: 400k Lichess cloud-eval positions (≥2 PVs) + 150k puzzles, structure-hash splits.

**Encoder enc_v1** (MLX, 7.46M params, value+policy trained; concept heads stop-grad), test split
(28.5k): value MAE 8.8 win-% pts, Stockfish top move 29%, puzzle first move 63%, puzzle-theme
AUC 0.83, concept probe R² 0.47 (material/phase/queens/development ≈ 0.87-0.99; tactical motifs
≤ 0.10). Same probes on a frozen **random** trunk: R² 0.28, theme AUC 0.71, puzzle 11% → play training adds +0.19 R² of human-concept information (McGrath-style baseline).

**Teacher**: 782 Claude Opus 5.5 labels (effort medium, ≈$0.035/position, $27.38 notional),
97% pass the fact checker after re-verification; ideas average 12-13 words. Two plan session
limits hit; stopped at 480 train / 151 val / 151 test to keep usage for evaluation.

**Discovery**: TopK SAEs on encoder latents; 3% (static) / 0% (dynamic) of features match one
hand-written concept at |r| ≥ 0.5. Best-minus-alternative (dynamic) features named by Claude
and predicted on unseen positions: king out of the centre 10/10, castle short 9/10, avoid the
queen trade 9/10, grab hanging material 8/10. Teachability (Schut's filter; weaker
step-2000 student fine-tuned 40 steps on 300 prototypes vs 300 random positions, top-move accuracy
on 100 held-out prototypes, 2 seeds): king out of the centre +7.5 pts, castle short +5.5, avoid
queen trade +1.5, capture hanging queen +1.5, simplifying trades −1.0, grab hanging material −10.9
(46 test positions). Only the king-safety concepts transfer; ±5 pts is within noise at n=100.

**Student** (Qwen3-1.7B + LoRA via mlx-lm, 573 train examples, checkpoint 500 of 600 by val loss
1.271; v1.1 input = facts with piece list / named captures / threats), 100 held-out test positions:

| | student | untuned Qwen3-1.7B | teacher (Opus 5.5) |
|---|---|---|---|
| follows format | 100% | 0% | – |
| passes our fact checker | 95% (v1 without piece facts: 87%) | 0% | – |
| concept tags vs teacher (F1) | 0.43 | – | 1 |
| idea length (words) | 11.9 | – | 12.5 |
| whole explanation judged correct (Opus, blind) | 0% | 3% | 93% |
| one-line idea judged correct (Opus) | **10%** | – | **93%** |
| pairwise | loses 100/100 to teacher; beats base 65% (13% loss, 22% tie) | | |
| reader (Haiku) picks best move with masked hint | 88% | – (no hint: 64%) | 90% |

- **The student learned the form, not the chess.** Condensation, format, concept vocabulary and
  hint usefulness transfer; correctness does not. Judge reasons are almost all board geometry:
  "Rd8 guards f6", "White has no c1 bishop", "the d5 pawn doesn't attack the queen". Our fact
  checker (moves exist, material claims) misses these, so 95% "verified" ≠ correct.
- **The transfer test is confounded**: a masked hint like "recapture with the knight" still
  identifies the move. It shows hints point at the right move, not that the reasoning is right.
- **Takeaway for v2**: (1) give the student explicit attack/defence relations (context
  builder's `relations()`), not just a piece list; (2) 5-10× more teacher labels (the Opus teacher
  is reliable: 93%); (3) a larger student (Qwen3-4B QLoRA) or encoder→LM soft-prompt fusion so
  geometry comes from the chess encoder; (4) a geometry fact checker (claims of "X attacks/guards
  Y") to filter training text and to build DPO pairs (teacher vs student) as a reward signal.
- Cost: teacher $27.38, discovery $1.6, judge $4.7 + idea judge $3.3, reader ≈$0.3 (notional,
  `claude -p` on the plan).

## 2026-09-24 — Haiku 4.5 vs Maia-1100: naive vs hybrid (thinking off, --board-read)
Runs `20260924_203947_{naive,hybrid-ctx}-haiku-vs-maia1100` (in `db/games.sqlite`; runs/ is
gitignored). 4 games each, colours alternate, 6-ply book openings, SF depth-12 analysis.

| player | score | ACPL | blunders | calls/move | $ total (4 games) | s/move |
|---|---|---|---|---|---|---|
| naive Haiku | 0/4 (4 mated) | 220 | 16 | 1.05 | 0.22 | 6 |
| hybrid-ctx Haiku | 1.5/4 (3 draws, 1 loss) | 113 | 14 | 1.69 | 0.96 | 12.5 |

- All 3 hybrid draws were repetitions from level/worse positions (SF −73, −196, and one
  where Maia was mating and repeated checks) — no won games thrown away.
- Remaining hybrid blunders cluster in (a) **checks** Claude proposes (Bb4+, Bxb3+, Qf2+,
  Rd5+ — materially "safe" at depth 2 but positionally/tactically bad deeper) and
  (b) **lost-endgame king walks** into mating nets beyond depth 2.
- Board vision ([[board-vision]]): piece placement 91% (naive) / 97% (hybrid) correct;
  threat detection only 14/90 (naive) and 42/111 (hybrid) — seeing attacks is the gap.
- n=4 per arm: direction is clear (0 vs 1.5, ACPL halved), magnitude is not.

## 2026-09-24 — hybrid v2 (context v2 + threat agent) vs Maia-1100, 8 games
Run `20260924_210922_hybrid2-haiku-vs-maia1100`, Haiku 4.5, thinking off, --board-read,
--threat-agent, one game per opening in the 8-opening rotation.

| player | score | ACPL | blunders | calls/move | $ total (8 games) | s/move |
|---|---|---|---|---|---|---|
| hybrid v2 Haiku | **6/8** (6 W, 2 L; 1 L was a forfeit bug) | **63** | 7 | 2.33 | 2.82 | 14 |

- vs v1 (1.5/4, ACPL 113) and naive (0/4, ACPL 220). Same opponent/settings.
- The forfeit was a harness bug, not chess: compare + threat calls ran in parallel on the
  SAME board and the context builder push/pops on it → corrupted board → exception.
  Fixed (each thread gets `board.copy()`). The game was otherwise ongoing.
- Decision anatomy over 264 moves: candidates vetoed in 187, "only tactically sound
  candidate" (no compare call) 73, forcing moves injected 30, fail-low re-search 31,
  mates found 9, **threat agent verified refutation changed scores 9×**, forced moves 5.
- Remaining ≥300cp errors: 7 in 8 games; 3 in an already-lost K+P ending (tablebase
  unavailable in the sandbox — would have been exact on a normal machine).
- Tablebase + Lichess unreachable here; K+P rules in context were the only endgame help.

## 2026-09-25 — exp3: context v4 (named tactical motifs) in games (Haiku, Maia 1100/1500/1900, 4 games each)
Report `experiments/exp3/`. Same openings/colours/settings as exp1/exp2 (paired), played locally
via `claude -p`. Harness also includes the new declared-sacrifice path (see [[engine]]).

| Haiku config | 1100 | 1500 | 1900 | total | Elo (95% CI) | ACPL | blunder rate | $/game | s/move |
|---|---|---|---|---|---|---|---|---|---|
| harness ctx v3 (exp2) | 3.5/4 | 1/4 | 3/4 | 7.5/12 | 1659 (1321–2043) | 72 | 4.8% | 0.37 | 12.4 |
| harness ctx v4 (exp3) | 3/4 | 1/4 | 2/4 | 6/12 | 1500 (1233–1833) | 64 | 3.6% | 0.38 | 9.7 |

- v4 vs v3, paired by opening/colour/level: −0.125 points/game (p = 0.62); per-game ACPL −8
  (p = 0.67); 6/12 identical results → **no measurable difference at n = 12**. Directionally:
  fewer ≥300cp blunders (4.8% → 3.6%), faster moves (12.4 → 9.7 s), same cost.
- Reliance: Claude's #1 played 55% (v3 65%), overruled 17% (16%), fail-low 18% (15%).
- **Sacrifice path barely matters with Haiku**: 39 declared "sacrifices" survived the veto, but
  Haiku labels loosely (e.g. Kxa6, Rgd8) and its own compare step awarded too little
  compensation for 38 of them; 1 was played (55…Rxe6, −800 material in a fail-low position,
  −415cp by SF). Watch this with Opus, which declares sacrifices more deliberately.
- To separate motifs from sacrifices and get power: ≥40 paired games per arm, or the offline
  position suite (paired, much cheaper) — see [[context-research]].

## 2026-09-24 — showcase: Opus 5.5 + harness (ctx v3, threat agent) vs Maia-1900, 1 game
Run `20260924_225106_opus-harness-vs-maia1900`; viewer `experiments/opus/game_opus_vs_maia1900.html`
(`scripts/game_viewer.py`). Opus as White, Ruy Lopez Exchange, **won** (resign adjudication at
+38 after 55.g4). **ACPL 19.7**, 0 blunders, one mistake (24.Nd2, −2.2); cost **$5.53** (52
moves × $0.106, 2.8 calls/move, 23 s/move — ≈17× Haiku per game).
Reliance on the tactical search: Claude's #1 played 38/52 (73%), overruled **1/52**, moves added
by search **0**, fail-low **0** — Opus played essentially all of its own chess; the harness only
checked. Key moments: 9.Qg3 double attack (e5+g7) → 10.Qxe5 wins a pawn; 18.Ra7 invasion (+1.9);
26.Qxc7 into a won ending; passed d-pawn 36.d5–39.d6; 41–44 wins the bishop; Maia's 52...h5?? ends it.
n = 1: a showcase, not a measurement.

## 2026-09-24 — exp2: context v3 in games (Haiku, Maia 1100/1500/1900, 4 games each)
Reports: `experiments/exp2/`, combined with exp1 in `experiments/exp1_exp2_combined/`
(`claude-chess report exp`). Same openings/colours/settings as exp1; 24 games, ≈ $4.7.

| Haiku config | 1100 | 1500 | 1900 | total | Elo (95% CI) | ACPL | $/game | s/move |
|---|---|---|---|---|---|---|---|---|
| harness ctx v2 (exp1) | 2/4 | 2.5/4 | 2/4 | 6.5/12 | 1552 (1153–1960) | 72 | 0.31 | 15.1 |
| harness ctx v3 (exp2) | 3.5/4 | 1/4 | 3/4 | 7.5/12 | 1659 (1321–2043) | 72 | 0.37 | 12.4 |
| naive (exp1+exp2) | 0/8 | 0/8 | 0/8 | 0/24 | – | 212 | 0.02 | 4.1 |

- v3 vs v2: +0.08 points/game, permutation p = 0.85 → **no measurable strength change in
  games** at n=12 (ACPL identical, 72).
- v3 vs naive: +0.62/game, p < 0.0001. Naive Haiku now 0/24.
- **Big shift in WHO plays the moves** (reliance on the Python tactical search):

| | Claude's #1 played | #1 overruled by search | move added by search | no Claude value call |
|---|---|---|---|---|
| ctx v2 | 41% | 42% | 13% | 39% |
| ctx v3 | **65%** | **16%** | **2%** | 26% |

  With the material check / relations / last-move context, Claude proposes safe moves itself;
  the same strength is now reached with far less Python override — more of the chess is
  Claude's (also better training data for [[reasoning-dataset]]). Slightly dearer per game
  (+19%) but faster per move (fewer vetoes → fewer extra calls).

## 2026-09-24 — exp1: harness vs no harness × Haiku/Sonnet × Maia ladder (FINAL)
Full report: `experiments/exp1/crosstable.md` (+ `games.csv`, `stats.json`); script
`scripts/exp_harness_vs_naive.sh`; report `claude-chess report exp1`. Thinking off for all;
resign adjudication ±1000cp × 6 plies; openings paired by Maia level. Budget-trimmed (user):
Sonnet-harness at 5 levels, other arms at 1100/1500/1900. 8 games that failed at engine
start-up were re-run with `--only-games` (same opening/colour). 56 games, ≈ $32 API.

| config | 1100 | 1300 | 1500 | 1700 | 1900 | total | Elo (95% CI) | ACPL | $/game | s/move |
|---|---|---|---|---|---|---|---|---|---|---|
| haiku-harness | 2/4 | – | 2.5/4 | – | 2/4 | 6.5/12 | 1552 (1153–1960) | 72 | 0.31 | 15 |
| haiku-naive | 0/4 | – | 0/4 | – | 0/4 | 0/12 | – (all lost) | 201 | 0.02 | 4.5 |
| sonnet-harness | 3/4 | 2.5/4 | 2.5/4 | 1.5/4 | 1/4 | 10.5/20 | 1528 (1332–1716) | 46 | 1.32 | 19 |
| sonnet-naive | 0/4 | – | 0/4 | – | 0/4 | 0/12 | – (all lost) | 115 | 0.13 | 4.2 |

Harness vs no harness (levels both arms played, 12 vs 12 games each):
- Haiku: +0.54 points/game, stratified permutation p = 0.012, LR p = 5e-5, ACPL 201→72
  (Mann-Whitney p = 1e-4); $0.54 extra per extra point.
- Sonnet: +0.54 points/game, permutation p = 0.001, LR p = 5e-5, ACPL 115→46 (p = 2e-4);
  $1.97 extra per extra point.
- **Naive Claude lost all 24 games** (both models, all levels). The harness is significantly
  better for both models.
- Haiku-harness ≈ Sonnet-harness in score (Elo CIs overlap heavily). Sonnet is more accurate
  (ACPL 46 vs 72) and leans less on the tactical search (#1 overruled 27% vs 42%, moves added
  by search 5% vs 13%) but costs ~4× per game. Haiku's 2/4 vs Maia-1900 (Sonnet 1/4) = two
  comebacks after Maia blunders (Maia is policy-only, blunders tactically) vs Sonnet saving two
  lost games by repetition — noise at n=4.
- Maia's nominal ratings are used for Elo; treat absolute Elo as rough ([[maia-calibration]]).

## 2026-09-24 — offline suite A/B: context v2 vs v3 (Haiku, 100 positions)
Suite `suites/v1.jsonl` (100 positions from our games, half "hard"; SF depth 14 labels; built by
`claude-chess suite build`). One decision per position, paired. (Code on branch `ctx-v3`,
merged after exp1.)

| player | mean cp loss | SF best played | blunders ≥200 | proposer recall (SF best among Claude's candidates) | $/position |
|---|---|---|---|---|---|
| naive Haiku | 471 | 14% | 66% | 14% | 0.0019 |
| harness, context v2 | 177 | 39% | 23% | 49% | 0.0082 |
| harness, context v3 | **160** | 40% | **17%** | **68%** | 0.0093 |

- Harness vs naive: −294 cp/position, paired permutation p = 5e-5.
- v3 vs v2: −17 cp (p = 0.35, n.s.); blunders 10 fixed vs 4 new (McNemar p = 0.18, n.s.);
  **proposer recall 22 gained vs 3 lost (McNemar p = 0.0002)** — the legal-move material check
  and last-move/relations context make Claude propose the right move far more often.
- Cost +13%/position. Next: a larger suite to resolve blunder rate, then v3 in games.

## 2026-09-24 — hybrid v3 alpha-beta (`--search alphabeta`) vs Maia-1100, 8 games
Run `20260924_213321_hybrid-ab-haiku-vs-maia1100`, same settings as v2 (Haiku, thinking off,
--board-read; threat agent supplies replies).

| player | score | ACPL | blunders | calls/move | $ total (8 games) | s/move |
|---|---|---|---|---|---|---|
| hybrid v2 compare+threat | **6/8** | **63** | 7 | 2.33 | 2.82 | 14 |
| hybrid v3 alpha-beta | 3.5/8 (2W 3D 3L) | 114 | 38 | 3.7 | 4.96 | 18 |

- Alpha-beta pruned ~40% of leaves (e.g. 3/7) but is **worse and dearer** than v2.
- Why (inspected every ≥300cp error; no search bug):
  1. Most blunders were decided before any search: every Haiku candidate lost material and
     the veto picked the least bad ("only tactically sound candidate"); the Stockfish best
     move was never proposed. Fail-low only fires below −tac_margin (−100), so "all lose a
     pawn" cases never widen to all legal moves. → lower the fail-low threshold to 0.
  2. **Pointwise positional scores are noisy**: independent leaf calls scored a king walk
     (Kd2, +45) above O-O-O (+45 tie → prior) etc. v2's single *listwise* compare call ranks
     siblings on one scale — consistent with LLM-as-judge findings (comparative > absolute).
  3. Lost endgames: depth-2 + ±150 positional can't see king-walk mating nets.
- Verdict: keep `compare` as the default harness; alpha-beta over LLM leaves needs a
  comparative leaf evaluator (e.g. batch all leaves under one root) to pay off.

## Earlier
- Sonnet naive vs Maia-1100 (2 finished games, others aborted by spend limit): 0/2, both mated.
  Stockfish: 9/53 moves lost ≥200cp, all short tactics — see [[computer-chess-principles]].
