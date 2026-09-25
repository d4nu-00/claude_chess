"""Shared contracts between modules. Every module codes against these types.

Pipeline for one move (see wiki/architecture.md):

    Board ──► ContextBuilder ──► PositionContext ──► Player.choose_move ──► MoveDecision
                                                        │
                                  Proposer (Claude) ──► candidates ──► Validator (python-chess)
                                                        │
                                  Search: apply each candidate on a real board,
                                  ask Claude for the opponent's reply, ask Claude
                                  Evaluator for a score, minimax back up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import chess


# ── Context layer ───────────────────────────────────────────────────────────


@dataclass
class PositionContext:
    """Everything the context builder knows about a position.

    `claude_chess.context.render_context(ctx)` turns this into the markdown
    block pasted into the prompt. The structured fields exist so tests and
    reports can inspect them.
    """

    fen: str
    side_to_move: str  # "white" | "black"
    phase: str  # "opening" | "middlegame" | "endgame"
    opening: str | None = None  # e.g. "C65 Ruy Lopez: Berlin Defence"
    material: str = ""  # e.g. "White: Q R R B N P×6 (+1)"
    pawn_structure: list[str] = field(default_factory=list)  # human sentences
    king_safety: list[str] = field(default_factory=list)
    piece_activity: list[str] = field(default_factory=list)
    tactics: list[str] = field(default_factory=list)  # hanging pieces, checks, pins
    concepts: list[str] = field(default_factory=list)  # retrieved KB guidance
    character: list[str] = field(default_factory=list)  # middlegame type, pawn breaks, imbalances
    endgame: list[str] = field(default_factory=list)  # ending type, K+P rules, tablebase
    # v3 (context-research): relations, what the last move changed, tactical temperature
    relations: list[str] = field(default_factory=list)
    last_move: list[str] = field(default_factory=list)
    temperature: int | None = None
    legal_moves_san: list[str] = field(default_factory=list)


# ── Decision layer ──────────────────────────────────────────────────────────


@dataclass
class Candidate:
    san: str
    reason: str = ""
    prior: float = 0.0  # proposer's confidence 0..1
    score_cp: float | None = None  # backed-up search score, from mover's view
    line: list[str] = field(default_factory=list)  # principal variation in SAN


@dataclass
class MoveDecision:
    move: chess.Move | None  # None => resigned / forfeited
    san: str | None
    candidates: list[Candidate] = field(default_factory=list)
    illegal_attempts: list[str] = field(default_factory=list)
    llm_calls: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    forfeit_reason: str | None = None
    note: str = ""
    forced_random: bool = False  # all retries failed -> uniform-random legal move played
    # Claude's own report of the position (piece placement, threats, hanging pieces) scored
    # against the real board — see engine/boardread.py. None unless board_read is enabled.
    board_read: dict | None = None
    # Structured search facts per candidate (tactical score, verified refutations, positional
    # score, vetoes, alpha-beta stats) — the engine-verified half of the dataset.
    search_info: dict = field(default_factory=dict)
    # Every LLM call made for this decision: {role, prompt, response, cost_usd, seconds, fen}.
    # Written to traces.jsonl (not decisions.jsonl) by the match runner.
    traces: list[dict] = field(default_factory=list)


class Player(Protocol):
    name: str

    def choose_move(self, board: chess.Board) -> MoveDecision: ...


# ── LLM layer ───────────────────────────────────────────────────────────────


@dataclass
class LLMResponse:
    text: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


class LLM(Protocol):
    model: str

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> LLMResponse: ...
