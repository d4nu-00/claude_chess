# Decisions

- **Search runs on a real board, not in Claude's head.** LLMs lose track of piece positions
  over multi-move imagined lines; python-chess applies moves so every searched node is a
  legal, exact position. Claude only does policy (candidates) and value (evaluation).
- **Stockfish never influences a Claude player's move.** Only an opponent and post-hoc judge.
- **Legal-move list in prompt is a separate toggle from strategic context**, default ON for
  every Claude player, so the context experiment isolates *strategic* knowledge rather than
  "knows which moves are legal".
- **Default backend is `claude -p` CLI** (no API key on machine). See [[llm-backend]].
- **Scores are centipawns from White's view** at the evaluator boundary; search converts to
  mover's view. Mate = ±10000.
