# Prior art: input format & prompt design for LLM chess

Research pass (2026-09-24), companion to [[illegal-moves]].

## FEN vs PGN vs ASCII board

- **PGN move history is the format chat/instruct-style harnesses report success with.**
  Carlini's GPT-3.5-turbo-instruct harness passes the full PGN so far (plus fake
  player-rating headers), getting strong (~1750 Elo), rarely-illegal play. Dynomight
  also used PGN-style move lists (`1. e4 e6 2. d3 c5 ...`), matching how games appear
  in pretraining data.
  [carlini: chess-llm](https://nicholas.carlini.com/writing/2023/chess-llm.html),
  [dynomight.net/more-chess](https://dynomight.net/more-chess/)
- **FEN (+ extras) is what the more "engine-like" harnesses use.** Game Arena defaults
  to FEN; ChessArena gives FEN *and* an ASCII board *and* move history *and* the
  opponent's last move *and* the model's own prior chain-of-thought — it over-provides
  rather than picking one representation.
  [game_arena repo](https://github.com/google-deepmind/game_arena),
  [ChessArena paper](https://arxiv.org/html/2509.24239v4)
- **Takeaway for us:** our context builder derives features from the real board, not
  from an LLM reading FEN, so legality is never the LLM's job. Still worth giving
  proposer/evaluator prompts both current FEN (cheap ground truth) and a short
  recent-move-history snippet (PGN-style) — history seems to help models orient on
  "what just happened" even when not needed for legality.

## Tokenizer / formatting gotchas

- Dynomight found a **trailing-space bug**: prompts ending `"...2. "` tokenized worse
  than `"...2."` for some open models (tokenizer fuses the space into the next token).
  Worth checking our templates don't end mid-token in a way that confuses SAN output.
  [dynomight.net/more-chess](https://dynomight.net/more-chess/)
- Carlini hit an analogous issue: `O-O` vs `O-O-O` share a prefix, so the model
  sometimes emitted a bare `-O` continuation; fixed with a trailing space after the
  move token. [carlini: chess-llm](https://nicholas.carlini.com/writing/2023/chess-llm.html)

## Model differences

- GPT-3.5-turbo-instruct (base-completion-style, PGN next-token prediction) plays more
  legally than chat/instruct-tuned GPT-4-class models given the same prompt — several
  sources note chat-tuned models are worse at raw legality. Reasoning models (o1-class)
  in Game Arena's tool-calling setup preferentially called `get_current_board` before
  moving rather than requesting the legal-move list.
  [dynomight.net/chess](https://dynomight.net/chess/),
  [llm_chess notes](https://github.com/maxim-saplin/llm_chess/blob/main/docs/notes.md)
- Open-weight models in Dynomight's tests needed **grammar-constrained decoding**
  against the legal-move set to avoid illegal moves — not applicable to us since we
  call Claude via API/CLI with no logit-level grammar control, which reinforces that
  our retry+fallback policy (see [[illegal-moves]]) is the right lever here.
