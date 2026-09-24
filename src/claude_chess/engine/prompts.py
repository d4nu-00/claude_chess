"""Prompt builders for the proposer, evaluator and naive player.

Every prompt contains FEN + ASCII board + move history. Strategic context
(render_context) only when use_context=True; the legal-move list is a
separate toggle (show_legal_moves) — see wiki/pages/decisions.md.
"""

from __future__ import annotations

import chess

PROPOSER_SYSTEM = """You are the move-proposal module of a chess engine. A separate search \
module will play out your candidates on a real board and evaluate them, so propose a \
DIVERSE set of plausible, strong moves (include forcing moves: checks, captures, threats).
Before proposing, briefly check: which pieces are hanging (both sides)? what does the \
opponent threaten? any checks/captures available?
Reply with ONLY a JSON object, no prose outside it:
{"thinking": "<= 2 short sentences", "candidates": [{"move": "<SAN>", "reason": "<few words>", "prior": <0.0-1.0>}]}
Moves must be legal in Standard Algebraic Notation (e.g. Nf3, exd5, O-O, e8=Q+). \
Priors are your confidence each move is best; they should roughly sum to 1."""

EVALUATOR_SYSTEM = """You are the evaluation module of a chess engine. Judge the given \
position statically as a strong grandmaster would.
FIRST check tactics: pieces that are hanging or can be won by the side to move, checks, \
forks, pins, mate threats. Remember the side to move can act first. THEN weigh material \
(pawn=100, knight/bishop≈300-325, rook=500, queen=900), king safety, activity and structure.
Reply with ONLY a JSON object, no prose outside it:
{"eval_cp": <integer, centipawns from WHITE's point of view: positive = White better>, "reason": "<one short sentence>"}"""

COMPARE_SYSTEM = """You are the positional-evaluation module of a chess engine. The engine's \
tactical search has ALREADY resolved captures, checks and short forcing lines for every option \
below, and has removed moves that lose material or allow mate. Material is counted exactly by \
the engine — do NOT re-count it. Your job is only what the search cannot see: compare the \
options on positional merit (piece activity and coordination, king safety, pawn structure, \
plans, initiative, long-term weaknesses, whether the engine's shown reply is really harmless).
Score every option relative to the others, from the point of view of the side to move: \
-150 (clearly worst) .. +150 (clearly best).
Reply with ONLY a JSON object, no prose outside it:
{"thinking": "<= 2 short sentences", "scores": [{"move": "<SAN exactly as listed>", "score": <int -150..150>, "reason": "<few words>"}]}"""

THREAT_SYSTEM = """You are the tactical watchdog of a chess engine: the OPPONENT's advocate. \
For each candidate move, find the opponent's MOST DANGEROUS reply in the position after it. \
The engine's shallow material search has already checked plain captures, so hunt for what it \
misses: quiet killer moves, mating nets, forks, pins and skewers, discovered attacks, \
deflection/decoy, trapped pieces, pawn promotions, 2-3 move combinations.
The reply must be a LEGAL move for the opponent in the position AFTER the candidate (use \
the board shown for that candidate). If a candidate is genuinely safe, give the opponent's \
best reply anyway.
Reply with ONLY a JSON object, no prose outside it:
{"replies": [{"move": "<candidate SAN exactly as listed>", "reply": "<opponent SAN>", "idea": "<few words>"}]}"""

NAIVE_SYSTEM = """You are a strong chess player. Choose the best move for the side to move.
Reply with ONLY a JSON object, no prose outside it:
{"thinking": "<= 2 short sentences", "move": "<SAN>"}
The move must be legal, in Standard Algebraic Notation (e.g. Nf3, exd5, O-O, e8=Q+)."""


def move_history_san(board: chess.Board) -> str:
    """Moves played so far as numbered SAN (from the board's move stack)."""
    if not board.move_stack:
        return "(none — starting position)" if board.fen() == chess.STARTING_FEN else "(none given)"
    root = board.root()
    return root.variation_san(board.move_stack)


def legal_moves_san(board: chess.Board) -> list[str]:
    return [board.san(m) for m in board.legal_moves]


def _context_block(board: chess.Board, include_legal_moves: bool) -> str:
    from claude_chess.context import build_context, render_context  # lazy: owned by another module

    ctx = build_context(board, include_legal_moves=include_legal_moves)
    return render_context(ctx, include_legal_moves=include_legal_moves)


def position_block(board: chess.Board, use_context: bool, show_legal_moves: bool) -> str:
    side = "White" if board.turn == chess.WHITE else "Black"
    parts = [
        f"FEN: {board.fen()}",
        f"Side to move: {side}",
        "Board (uppercase = White, lowercase = Black, rank 8 at top):",
        str(board),
        f"Moves so far: {move_history_san(board)}",
    ]
    if use_context:
        # Legal moves are appended by us below, so the context never carries them itself.
        parts.append("## Position analysis\n" + _context_block(board, include_legal_moves=False))
    if show_legal_moves:
        parts.append("Legal moves: " + " ".join(legal_moves_san(board)))
    return "\n".join(parts)


def proposer_prompt(board: chess.Board, n: int, use_context: bool, show_legal_moves: bool,
                    feedback: str = "") -> str:
    side = "White" if board.turn == chess.WHITE else "Black"
    p = position_block(board, use_context, show_legal_moves)
    p += f"\n\nPropose the {n} best candidate moves for {side}."
    if feedback:
        p += "\n\n" + feedback
    return p


def evaluator_prompt(board: chess.Board, use_context: bool) -> str:
    # Evaluator never needs the legal-move list: it judges, it doesn't move.
    p = position_block(board, use_context, show_legal_moves=False)
    return p + "\n\nEvaluate this position (eval_cp from WHITE's point of view)."


def compare_prompt(board: chess.Board, options: list[tuple[str, int, str, str]],
                   use_context: bool) -> str:
    """options: (san, material swing for the mover in cp, engine's best reply SAN, FEN after move)."""
    side = "White" if board.turn == chess.WHITE else "Black"
    p = position_block(board, use_context, show_legal_moves=False)
    lines = []
    for i, (san, swing, reply, fen) in enumerate(options, 1):
        mat = f"{swing:+d}cp" if swing else "level"
        rep = f"; engine's best reply {reply}" if reply else ""
        lines.append(f"{i}. {san} — material after forcing play: {mat}{rep}; FEN after {san}: {fen}")
    return (p + f"\n\nCandidate moves for {side} (all tactically checked by the engine):\n"
            + "\n".join(lines) + f"\n\nScore each option for {side}.")


def threat_prompt(board: chess.Board, options: list[tuple[str, str, chess.Board]],
                  use_context: bool) -> str:
    """options: (candidate SAN, engine's shallow best reply SAN or "", board after candidate)."""
    side = "White" if board.turn == chess.WHITE else "Black"
    opp = "Black" if board.turn == chess.WHITE else "White"
    p = position_block(board, use_context, show_legal_moves=False)
    parts = [p, f"\n{side} is considering these moves. For each, find {opp}'s most dangerous reply."]
    for i, (san, eng, after) in enumerate(options, 1):
        hint = f" (engine's shallow search expects {eng})" if eng else ""
        parts.append(f"\n### {i}. {side} plays {san}{hint}\nFEN: {after.fen()}\n{after}")
    return "\n".join(parts)


def naive_prompt(board: chess.Board, show_legal_moves: bool, feedback: str = "") -> str:
    side = "White" if board.turn == chess.WHITE else "Black"
    p = position_block(board, use_context=False, show_legal_moves=show_legal_moves)
    p += f"\n\nYou play {side}. Choose your move."
    if feedback:
        p += "\n\n" + feedback
    return p


def illegal_feedback(board: chess.Board, errors: list[str]) -> str:
    return (
        "Your previous answer contained no legal move:\n- " + "\n- ".join(errors)
        + "\nThe complete list of legal moves is: " + " ".join(legal_moves_san(board))
        + "\nPick only from that list."
    )
