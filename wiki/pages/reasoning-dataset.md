# Reasoning dataset (for distilling a move-explainer transformer)

Code: `src/claude_chess/dataset.py`, CLI `claude-chess dataset [run_dir...] --out datasets/<name>
[--with-context]`. Test: `tests/test_dataset.py`. Card with schema: `datasets/<name>/README.md`.

## Capture
- Every LLM call is recorded by `_Tally` (engine/players.py) as a trace: role (from
  `prompts.ROLES`), model, FEN of the position in the prompt, full prompt, raw response,
  tokens, cost, latency → `MoveDecision.traces` → `runs/<id>/traces.jsonl` (kept out of
  decisions.jsonl to keep that small).
- The hybrid records per-candidate engine facts in `MoveDecision.search_info`
  (→ `decisions.jsonl["search"]`): source (claude/engine), prior, reason, tactical_cp,
  engine_reply, vetoed, threat_reply/idea/cp/verified, positional_cp, ab_value/line, decided_by.
- Runs before traces existed still export (candidates+reasons from decisions.jsonl), just
  without thinking/threat/positional text.

## Why this format
- **Canonical + derived.** `positions.jsonl` (structured, everything) and `calls.jsonl.gz`
  (raw, lossless) are the source of truth; `sft.jsonl` / `preferences.jsonl` are one
  templating of them. Re-template without re-buying LLM calls.
- **Split by game**, never by position (adjacent plies are near-duplicates → leakage).
- **Reason-then-answer** targets for causal LMs: Threats → Assessment → Candidates (with
  reasons) → Best move.
- **Provenance tags**: `[verified]` = checked by the search on a real board (refutation line,
  material, mate) — ground truth; untagged = Claude's opinion. The student can learn to
  ground claims; filters can drop unverified text.
- **Labels stored, not baked in**: Stockfish cp_loss/best move and game result let consumers
  filter (e.g. cp_loss < 100) or weight, instead of us deciding once.
- **Preference pairs** come for free: a sound played move vs a Claude candidate the engine
  refuted (with the refutation) — the most informative negative examples for DPO.
- Plain ASCII, FEN + SAN, short inputs (last 6 moves) — tokenizer friendly; `--with-context`
  adds the rendered Python context if the student will get it at inference too.

## Caveat
User confirmed use complies with the Anthropic terms they are on (2026-09-24).

## Export v1 (2026-09-24) — `datasets/reasoning_v1/`
`claude-chess dataset --out datasets/reasoning_v1` over all runs: **2,384 positions**
(1,976 harness, 408 naive; 1,883 with full agent traces), splits train/val/test
1,833/355/196 by game; **2,339 SFT examples** (1,854 with cp_loss < 100 — filter on
`quality.cp_loss`); **1,664 preference pairs**; 1.8 MB gzipped raw calls. Models: Haiku 4.5 and
Sonnet 5, thinking off. Every position has Stockfish labels.
Gotcha fixed before export: `move_analysis.jsonl` stores `game` as a string (see
[[match-and-analysis]]); without normalising, all labels were silently empty.

## Known LLM reasoning errors to filter/annotate (observed 2026-09-24)
- **Recapture called a win**: "Rxc7 wins the queen outright" after ...Qxc7 (Opus), "Bxg5 wins queen
  for bishop" after ...Qxg5 (Sonnet). The model scores the capture, not the exchange sequence.
- **Material-count drift**: "a pawn up" when three up; "loses the queen for a rook" when for a pawn.
- **Phantom captures** from the threat agent (Sonnet: "Bxd5" that did not exist).
Use `[verified]` material facts to correct or drop such sentences before training. Full example:
`experiments/opus/opus_thoughts.md`.
