# Explainer: hypotheses and tests (round 2, 2026-10-03)

Context: [[explainer-model]] v1 — the Opus teacher's one-line ideas are 93% correct, the 1.7B
student's 10% (geometry/reasoning errors). The user then asked for a model that **chooses the move
and explains it** (the v1 student only explained Stockfish's or the encoder's move) and a GUI to
play it (`scripts/play.py`). Each hypothesis has a prediction written before the test.

## Settled

**J4 — one-ply value lookahead improves the encoder's move choice. REFUTED.**
Test: 600 held-out cloud-eval positions + 600 puzzles; pick the top-k policy move with the best
`1 − V(after)`. Prediction: +5-10 pts top-1. Result: worse — cloud-eval 31% (policy) → 29/27/23%
(k=3/5/8), puzzles 62% → 45/43/40%. The value head is unreliable on positions just after a
non-best move (it's trained on root positions of PV1 only). Use the policy; don't search on V.

**Encoder candidate recall** (Stockfish best among the encoder's top-k), same positions:
cloud-eval 31 / 56 / 67 / 78% at k = 1/3/5/8; puzzles 62 / 83 / 89 / 93%. A model that chooses among
6 candidates has a ceiling of ≈70% (cloud-eval) / ≈90% (puzzles) vs the 31% / 62% instinct.

**Geometry checker as a cheap judge proxy — PARTLY.** `explainer/geometry.py` checks prose piece
references ("the c4 knight") and attack/guard claims on real boards near the line. After removing
bare SAN (mostly later or hypothetical moves → 62% false flags on the teacher), it flags 32% of
student explanations vs 7% of the teacher's — it separates them. But it flags only 5% of student
*ideas*: the ideas' errors are wrong *reasons* ("…h3 strikes the centre"), not phantom pieces, so
it can't stand in for the judge on ideas. Useful as a training-data filter, not as the metric.

## Results so far

**Joint model A** (reason-first, relations; Qwen3-1.7B LoRA, 1 epoch, best checkpoint 1500, val 1.10),
250 held-out cloud-eval + 250 held-out puzzles, same positions for every variant:

| | cloud-eval | puzzles |
|---|---|---|
| encoder instinct (top policy move) | 25.6% | 62.8% |
| joint A, idea → move prompt | 28.0% | 58.4% |
| joint A, move-only prompt | 25.6% | 64.4% |
| ceiling: best among its 6 candidates | ≈67% | ≈89% |

- **J1 not supported** (n=250, differences within noise): the joint model ≈ its instinct. With the
  move-only prompt it reproduces the instinct exactly on cloud-eval — it learned "copy the top
  candidate". The verified consequences ("leaves Qd8 en prise") describe threats but don't
  resolve them, and 2,000 move examples aren't enough to learn to weigh them.
- **J3 (within A)**: writing the idea first changes the move: +2.4 pts on quiet positions,
  −6.0 on puzzles vs its own move-only answer. On tactics the idea seems to commit it to a
  general story ("develop, castle") and it then picks a move that fits the story.
- **Ideas** (blind Opus, 100 teacher test positions, judged against its *own* move): 13% entirely
  true, 26% a sound reason, **51% sound when it picked Stockfish's move** (39% of positions). Errors
  are still invented details ("with tempo" with no threat, "the extra piece" at equal material).
- GUI gotcha: **MLX streams are thread-local** — loading a model on the main thread and generating
  on a worker gives "There is no Stream(cpu, 1) in current thread". `scripts/play.py` loads and
  runs everything on its single model thread.

**Joint model D** = A + each candidate's verified forcing-play outcome (same positions, paired
McNemar on 250 + 250):

| | cloud-eval | puzzles |
|---|---|---|
| encoder instinct | 25.6% | 62.8% |
| D, move-only prompt | **30.4%** (+4.8, p=0.16) | **75.2%** (+12.4, p<0.001) |
| D, idea → move prompt | 29.2% (p=0.28) | 68.0% (+5.2, p=0.06) |
| D vs A (same prompt) | move-only +4.8 (p=0.13), explain +1.2 | move-only +10.8 (p<0.001), explain +9.6 (p=0.002) |

- **J5 SUPPORTED on tactics.** Telling the model what each candidate's forcing play nets (a
  2-ply material search, no engine) is what lets one small LM beat its own instinct — the
  hybrid-harness lesson again ([[computer-chess-principles]]): the LM shouldn't count exchanges.
  On quiet cloud-eval positions the gain (+4.8) isn't significant at n=250.
- **J3 (within D) — explaining first HURTS tactics, significantly**: move-only 75.2% vs
  idea-first 68.0% on puzzles (+29/−11, p=0.006); no difference on quiet positions. For a 1.7B
  model the stated idea is not the cause of a better move — it commits the model to a narrative.
  Model B (trained move-first) tests whether that's a training-order artefact.
- **Ideas didn't improve**: D's ideas 15% entirely true, 25% sound (46% when it found Stockfish's
  move) ≈ A. Better inputs fixed the moves, not the explanations.

**Joint model E** = D's input (relations + tactical outcomes), trained **move-first** (Move → Idea
→ Plan → Concepts); same positions, best checkpoint 1500 (val 1.046, lowest of all variants):

| | cloud-eval | puzzles |
|---|---|---|
| encoder instinct | 25.6% | 62.8% |
| E, explain prompt | **34.0%** (+25/−4 vs instinct, p<0.001) | **72.0%** (+25/−2, p<0.001) |
| E, move-only prompt | 33.6% | 72.8% |
| E explain vs D explain | +6.0 (p=0.10) | +4.0 (p=0.11) |

- **J3 answered: decide first, then explain.** E's explain mode costs nothing (vs its move-only:
  p=1.0 / 0.63), whereas D's idea-first mode cost 7 pts on tactics (p=0.006). For a 1.7B model the
  stated idea is not what makes the move good; writing it first pulls the move toward a narrative.
  So the model's explanation is a *post-hoc account of its own decision*, made by the same network
  from the same input — honest framing for the GUI.
- E's ideas: 19% entirely true, 26% sound, 52% sound when it found Stockfish's move — slightly
  better than A/D, still the weak part. `joint_best` → E (the GUI default).
- **Human game (user vs D, 1-0, 44 moves)**: fine opening (Scandinavian, ≤ +0.7 for 8 moves); lost
  a piece to 9...Nxe5? 10.dxe5, a pawn fork of Bd6 and Nf6 that the 2-ply tactical search scored
  "material holds" (horizon). Depth 3 also misses it; **depth 4 sees it** (−1.3) at ≈1.6 s per
  candidate. In the long endgame its ideas collapsed into one template ("Block the check with the
  king so it is safe" with no check) — distribution shift: few long endgames in training.

**J6 — deeper verified tactics at inference (depth 4 instead of 2, no retraining) — SMALL, ONE-WAY
GAIN.** E_depth4 on the same 500 positions: cloud-eval 34.8 / 34.8% (explain / move-only; vs 34.0 /
33.6), puzzles 73.2 / 74.8% (vs 72.0 / 72.8). Every changed puzzle decision improved (+3/−0 explain,
+5/−0 move-only, p=0.25 / 0.06). Ideas sound 28% (56% when best). Cost ≈ 10 s/move (CPU search).
Horizon blunders are rare in these test sets, so the average gain is small, but it is never worse:
the GUI defaults to depth 4. E (depth 2 or 4) plays 9...O-O in the user's game, not the losing Nxe5.

## Round 3: more explanation data (J7, 2026-10-04)
Collected 2,000 new Opus labels (1,980 positions, 97% pass the fact checker, $40 notional, 3 plan
session windows ~09:40-19:39; batched 5 per call, endgame-weighted) → `teacher_v2.jsonl`.
- **E2** (E's format; 573 old + the first window's ≈600 new labels, one epoch): ideas sound
  26% → **37%** (+24/−13, p=0.10), entirely true 19% → 21% (n.s.), sound-when-best 52% → 57%;
  moves unchanged (34.0→32.8% / 72.0→74.0%, n.s.). More labels move the ideas toward the right
  *reason*; invented details ("with tempo" with nothing attacked, a non-existent check) persist.
- **E3** (all ≈2,550 teacher positions ×2 + 2,000 move-only = 6,994 examples, 3,497 iterations):
  ideas sound **39%** (vs E +23/−10, **p=0.035**), entirely true **28%** (p=0.15), sound-when-best
  **60%**; moves 34.8% / **76.0%** (explain mode; vs instinct 25.6 / 62.8, vs E n.s.). **J7
  SUPPORTED**: 4.4× the explanation labels → +13 pts sound ideas; returns flatten on "sound"
  (E2→E3 +2) but "true" keeps climbing (+7). E3 is `joint_best` (GUI default).

## Where this leaves the idea (2026-10-04)
- A 1.7B model *can* choose moves better than its intuition network (+9 pts on both test sets) when
  the facts it reads include resolved tactics; it explains after deciding at no cost.
- The explanations are the bottleneck: ≈25-28% judged sound overall, ≈55% when it finds the best
  move. Errors are invented details (pieces on wrong squares, "with tempo" with no threat) and,
  in long endgames, template collapse ("Block the check…").
- Next, by expected value: (1) more Claude labels for the *explanation* part — only 573 so far vs
  2,000 move examples; (2) constrain the explanation to facts already in its input (copy-only
  pointer to verified facts, or rejection sampling with `geometry.py` + the move verifier);
  (3) endgame-heavy data to stop template collapse; (4) a bigger student (Qwen3-4B, 4-bit LoRA);
  (5) C (relations ablation) and B (move-first without tactics) remain untested.

**J5 — a verified forcing-play outcome per candidate lets the model beat its instinct.** Variant D =
A + each candidate's result from the repo's material-only tactical search (`engine/tactical.py`,
2-ply full width + quiescence, ≈50 ms/candidate, no Stockfish): "forcing play: loses ~9 (best reply
Bxd8)". Prediction: beats the instinct on puzzles (> 62.8%) — the same lesson as the hybrid
harness ([[computer-chess-principles]]): LLMs don't count exchanges, a tiny search does.

**J1 — one LM can pick moves better than the encoder's instinct.** Joint model
(`explainer/joint.py`): Qwen3-1.7B LoRA sees the position spelled out (pieces, threats, who attacks
what) and 6 encoder candidates with verified consequences ("leaves Qd8 en prise"), no engine
anywhere; outputs idea + move + plan + concepts. Data: 2,000 cheap move-only examples (Stockfish's
move, no LLM cost) + 573 teacher explanations ×2. Prediction: move accuracy above the encoder's
instinct on both test sets (> 31% / > 62%), mainly by avoiding tactical blunders on puzzles.

**J3 — stating the idea before the move improves the move.** A (Idea → Move) vs B (Move → Idea),
identical inputs/candidates. Prediction: A ≥ B on move accuracy (reasoning-first), and both ≥ their
own move-only prompt. Alternative: small models' "reasoning" is decoration → no difference.

**J2 — who-attacks-what relations help.** Both A and B include them; ablation C (without) if time.

## Evaluation protocol
`scripts/explainer_joint_eval.py ADAPTER NAME`: 250 held-out cloud-eval + 250 puzzles, move accuracy
under the explain prompt and the move-only prompt, encoder instinct and recall@6 on the same
positions; ideas judged by blind Opus (true? sound reason for its own move?) on the 100 teacher test
positions used for v1.1 — per-item results stored for paired comparisons.
