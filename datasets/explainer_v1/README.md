# explainer_v1 — engine-grounded, condensed chess explanations

Built by `python -m claude_chess.explainer` (see `wiki/pages/explainer-model.md`).

## Files
- `teacher.jsonl` — one row per labelled position:
  - `fen`, `split` (0 train / 1 val / 2 test, by pawn-structure hash — near-duplicate positions
    share a split), `best_line` / `alt_line` (UCI, Stockfish multi-PV from the Lichess cloud-eval
    DB), `best_san` / `alt_san`, `value` / `value_alt` (side-to-move win probability, Lichess formula);
  - `salience` — `[concept key, z, goodness]`: what the best line changes differently from the
    alternative after ≤8 plies, computed by `explainer/concepts.py` on a real board;
  - `facts` — the exact text block the teacher (and the student) saw;
  - `label` — Claude Opus 5.5 (effort medium): `idea` (≤15 words), `assessment`, `why_best`,
    `why_not_alt`, `concepts` (1-3 ids from `explainer/vocab.py`), `novel_concept`, `plan`,
    `difficulty` (obvious / natural / hard / computer);
  - `verify` — fact-checker result (`ok`, `flags`, `unsupported_concepts`). Re-run it with
    the current verifier rather than trusting the stored flags: `lm.build_sft` does.
  - `cost_usd`, `seconds`, `model`.
- `teacher_v2.jsonl` — round 3: Opus 5.5 labels batched 5 per call (same schema), new train-split
  positions weighted 20/40/40 opening/middlegame/endgame. Seeded with the teacher pilot's 40 Opus
  rows (20 positions labelled twice — de-duplicated by FEN when training, first label wins).
- `sft/` — chat-format train/valid/test for mlx-lm (verified labels only; idea first).
- `discovered_concepts.json` — SAE features on the encoder, Claude's names, simulation scores.

## Selection
Cloud-eval positions with ≥2 PVs where the alternative costs 4-60 win-% points and the position
isn't already decided for both moves; stratified 30/45/25 by phase (opening-ish/middlegame/endgame).
Test and val were labelled first.

## Provenance and licence
Positions, lines and evaluations: Lichess open database (CC0). Labels: generated with Claude via
`claude -p` on the user's plan; the user confirmed (2026-09-24, see `reasoning-dataset` page) that
using Claude outputs this way complies with the Anthropic terms they are on.

## Known limitations
- The `bad_bishop` detector counts pawns blocked by any piece, not only by enemy pawns.
- Concept vocabulary v1 lacks: remove the defender, desperado, rook lift, perpetual check,
  cutting off the king (Claude names them in `novel_concept`).
- Labels describe Stockfish's choice; a "computer" difficulty tag marks moves with no human idea.
