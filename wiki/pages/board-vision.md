# Board vision probe (`--board-read`)

Code: `src/claude_chess/engine/boardread.py`; `board_read=True` on `NaiveClaudePlayer` and
`ClaudeEnginePlayer`; logged as `board_read` in `decisions.jsonl` (`MoveDecision.board_read`).

Claude's move-choosing call also returns `board` (every piece + square), `threats` (opponent
moves that would win material/mate if it were their turn) and `hanging` (own pieces that can
be won). Python scores it: `piece_accuracy`, `missing`/`phantom` pieces, `threats_missed`,
`hanging_missed`. Ground truth threats = null-move + material search depth 1 (≥100cp or mate).

Why: separates "doesn't know where things are" from "knows but doesn't see the tactic", and
is a cheap look-before-you-move step. Costs ~150 extra output tokens per call.

First observations (Haiku 4.5, thinking off, 2026-09-24): placement ≈ 94–100% correct even
in a late middlegame; **threat detection is the weak spot** — on the …Kh7?? position the
naive player missed Qxg7# as a threat and hung its queen (Qf1+?? Kxf1).
