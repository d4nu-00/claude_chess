# Research: getting MORE RELEVANT context, more cheaply (2026-09-24)

Question from the user: how can a classical-engine-style harness give Claude more relevant
context, and decide efficiently what context matters?

## What our own data says (free analysis, alpha-beta run, 377 Haiku decisions, SF depth 12)
| | ok moves (331) | blunders ≥200cp (46) |
|---|---|---|
| Stockfish best move among Claude's proposed candidates | 55% | **39%** |
| Stockfish best move mentioned anywhere in the context | 31% | 20% |
| Refutation of the played move mentioned in the context | – | **9%** |

Context volume per prompt (avg chars): Guidance 1059 (generic!), Position 207, Pawn structure
202, Tactics 169, Character 169, King safety 140, Endgame 127, Activity 105, Material 92.

Conclusions:
1. **Coverage, not salience, is the bottleneck.** In 61% of blunders the right move was never
   proposed, so no search/evaluation could pick it. Improving the proposer's recall matters
   more than evaluating better.
2. **The context describes the position *before* the move; blunders happen *after* it.**
   Refutations were in the context only 9% of the time. Context must become
   *move-conditioned* (what each candidate changes) — see A below.
3. The biggest block of context (generic Guidance, ~45%) is the least position-specific.
4. Board-vision probe ([[board-vision]]): Claude knows WHERE pieces are (~97%) but not WHAT
   THEY ATTACK (threat detection 38–15%). Relations, not placement, are missing.

## Literature (short)
- **Concept-guided chess commentary (CCC, NAACL 2025)**: extract concept vectors from an expert
  model, *rank concepts by relevance to the specific move* (dot product of position
  representation with concept vectors), feed only the top ones to the LLM. The key idea for
  us: relevance is **move-specific**, and ranking concepts before prompting beats dumping all.
- **DeepMind MAV (Mastering Board Games by External and Internal Planning, 2024)**: one
  transformer acts as world model + policy + value on a compact textual format, used with
  MCTS (external) or generating a linearized search tree in context (internal) → GM level.
  Lesson: a *structured, compact* state/action/value text format and search do the heavy
  lifting; also the target format for the distillation dataset ([[reasoning-dataset]]).
- **Schut et al., PNAS 2025 (AlphaZero concept discovery)**: machine concepts can be found as
  vectors in a net's representation and taught to GMs via prototype positions — i.e.
  *example positions* are an effective carrier of a concept (→ retrieval of similar positions).
- **LLM chess prompting studies (2025)**: FEN + SAN is enough — PGN/UCI histories add nothing
  measurable; explicitly providing legal moves is critical. (Supports trimming history.)
- **Position retrieval**: position-embedding models (e.g. ChessLM) and FAISS-style retrieval of
  similar positions/rationales from annotated databases are being used for RAG.
- **Stockfish classical eval terms** (material, imbalance, pawns, pieces, mobility, king safety
  with attack units, threats, passed pawns) — a proven, decomposable feature set. A Python
  re-implementation gives an *eval trace* per term without using Stockfish in the decision.
- LLM-as-judge: listwise/pairwise comparison is more reliable than pointwise scores — matches
  our v2 (listwise compare) vs v3 (pointwise leaves) result ([[results]]).

## Ranked plan (value ÷ cost)
**0. Method first — an offline position test suite (engine-dev practice: WAC/STS + SPRT).**
Games are noisy and costly ($3–30 per arm). Build a fixed suite (~200 positions from our own
games' blunders + STS-style strategic positions, labels from SF), and A/B each context change
on *decision quality* (cp loss, best-move hit rate, proposer recall@4) for ≈$1/arm with Haiku.
Only promote winners to game matches.

**A. Move-conditioned context ("what does this move change?").** For each candidate (after
the proposer, before compare), compute deltas on a real board: pieces left undefended or newly
attacked, opponent's forcing replies and their SEE, lines opened to either king, pawn-structure
changes (new isolani/passer), and the material-search refutation line. Feed these per option
into the compare/threat calls. Targets finding 2 directly; costs Python only.

**B. "What changed?" context for the opponent's last move.** New attacks it created, pieces it
left en prise, lines it opened, what it now threatens (null-move). Humans ask "why did they
play that?" first; it is the cheapest high-precision threat detector.

**C. Relations, not placement: attack/defence maps.** Per piece: what it attacks and what
defends it ("Nf3 → e5 (P, defended by Nc6), g5; defended by Qd1, g2"), plus loose pieces and
overloaded defenders. Targets the board-vision gap (threats seen 15–38%).

**D. Decide relevance automatically.**
- *Decision relevance = variance across candidates*: compute every feature for each child
  position; lines identical for all candidates cannot affect the choice → drop them; lines that
  differ most go first (primacy) — a CCC-style ranking without a neural net.
- *Adaptive budget by "tactical temperature"* (static material vs quiescence score gap, number
  of SEE≠0 captures/checks/hanging pieces): hot positions get expanded tactics + per-move
  deltas; quiet ones get structure/plans. Classic engines use the same instability signal for
  time management.
- *Guidance → proposer only, top-1 page, and only when its tags fire strongly* (saves ~45% of
  context tokens for zero information loss elsewhere; partly done via `compact`).

**E. Raise proposer recall (the #1 bottleneck).** Give the proposer a Python-ranked shortlist
using classical move ordering: forcing moves by SEE, moves that parry the null-move threat,
moves that improve the worst-placed piece (mobility delta), pawn breaks; ask Claude to choose
among / add to them. Measure recall@4 vs SF best on the suite. Also widen fail-low to "every
candidate loses material" (threshold 0, see [[results]]).

**F. Case-based strategic context (retrieval).** Index a master-game PGN database by pawn-
structure hash + material signature (+ position embedding later); retrieve the 3 most similar
positions and what masters played / the plan. Prototype positions carry concepts well (Schut).
On the Mac the Lichess masters explorer API works; the sandbox blocks it.

**G. Let Claude ask for context (on-demand).** A cheap first call where Claude asks ≤3
questions ("what happens after Nxe5?", "is f7 defended?"), Python answers exactly, then it
proposes. Pay only for context it needs; the questions themselves are a salience signal to log.

**H. Learn relevance from the dataset.** With [[reasoning-dataset]] labels, fit which context
sections/lines predict good vs bad decisions (logistic / feature ablation on the test suite);
prune sections with no effect; this turns "what is important" into a measured answer.

## Recommendation
Build 0 (suite), then A+B+C (all Python, move-/change-conditioned relations), then D's
variance ranking and Guidance trimming, then E. F–H after. Expected effect: fewer blunders from
unseen refutations and unproposed moves, and *shorter* prompts (cheaper per call).

Sources: arxiv.org/abs/2410.20811 (CCC); arxiv.org/abs/2412.12119 (MAV); pnas.org/doi/10.1073/pnas.2406675122
(Schut); arxiv.org/abs/2507.00726 (LLM chess post-training: FEN+SAN, legal moves); huggingface.co/odestorm1/chesslm
(position embeddings); arxiv.org/abs/2607.21993 (retrieval of move rationales); hxim.github.io/Stockfish-Evaluation-Guide
(classical eval terms); chessprogramming.org/King_Safety.
