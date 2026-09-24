"""Claude players: NaiveClaudePlayer (one call) and ClaudeEnginePlayer (propose -> validate -> search).

Score conventions (wiki/pages/engine.md): the evaluator returns centipawns from WHITE's
view; search converts to the mover's view; Candidate.score_cp is from the mover's view.
Terminal positions are scored exactly (mate = ±MATE_CP, draw = 0) without calling Claude.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import chess

from claude_chess.engine import prompts
from claude_chess.llm import extract_json
from claude_chess.types import LLM, Candidate, MoveDecision

MATE_CP = 10000
EVAL_CLAMP = 9999  # keep Claude's evals strictly inside the mate band
MAX_WORKERS = 8
ILLEGAL_POLICIES = ("random", "forfeit")


# ── helpers ────────────────────────────────────────────────────────────────


def parse_move(board: chess.Board, text: str) -> tuple[chess.Move | None, str]:
    """Parse SAN, then UCI. Returns (move, "") or (None, reason)."""
    s = (text or "").strip().rstrip(".!?")
    if not s:
        return None, "empty move"
    s = s.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    try:
        return board.parse_san(s), ""
    except chess.IllegalMoveError:
        san_err = "illegal in this position"
    except chess.AmbiguousMoveError:
        san_err = "ambiguous SAN"
    except (chess.InvalidMoveError, ValueError):
        san_err = "not valid SAN"
    try:
        mv = chess.Move.from_uci(s.lower())
        if mv in board.legal_moves:
            return mv, ""
        return None, "illegal in this position"
    except (chess.InvalidMoveError, ValueError):
        return None, san_err


def terminal_score(board: chess.Board) -> int | None:
    """Exact score from WHITE's view if the game is over, else None."""
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return None
    if outcome.winner is None:
        return 0
    return MATE_CP if outcome.winner == chess.WHITE else -MATE_CP


def _sign(color: chess.Color) -> int:
    return 1 if color == chess.WHITE else -1


class _Tally:
    """Per-decision, thread-safe accounting of LLM calls/cost."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.calls = 0
        self.cost = 0.0
        self._lock = threading.Lock()

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        resp = self.llm.complete(system, prompt, max_tokens=max_tokens)
        with self._lock:
            self.calls += 1
            self.cost += resp.cost_usd
        return resp.text


def _exhausted(board: chess.Board, policy: str, rng: random.Random, why: str,
               tally: _Tally, t0: float, illegal: list[str],
               candidates: list[Candidate] | None = None) -> MoveDecision:
    dec = MoveDecision(move=None, san=None, candidates=candidates or [], illegal_attempts=illegal,
                       llm_calls=tally.calls, cost_usd=tally.cost)
    if policy == "random":
        mv = rng.choice(list(board.legal_moves))
        dec.move, dec.san, dec.forced_random = mv, board.san(mv), True
        dec.note = f"random legal move after exhausting retries ({why})"
    else:
        dec.forfeit_reason = f"no legal move after retries ({why})"
    dec.seconds = time.monotonic() - t0
    return dec


# ── naive baseline ──────────────────────────────────────────────────────────


class NaiveClaudePlayer:
    """Plain Claude: one call (FEN + board + history [+ legal moves]) -> move."""

    def __init__(self, llm: LLM, show_legal_moves: bool = True, illegal_policy: str = "random",
                 max_retries: int = 2, seed: int | None = None, name: str | None = None) -> None:
        assert illegal_policy in ILLEGAL_POLICIES
        self.llm = llm
        self.show_legal_moves = show_legal_moves
        self.illegal_policy = illegal_policy
        self.max_retries = max_retries
        self.rng = random.Random(seed)
        self.name = name or f"naive[{getattr(llm, 'model', '?')},legal={int(show_legal_moves)}]"

    def choose_move(self, board: chess.Board) -> MoveDecision:
        t0 = time.monotonic()
        tally = _Tally(self.llm)
        illegal: list[str] = []
        feedback = ""
        for _ in range(self.max_retries + 1):
            try:
                text = tally.complete(prompts.NAIVE_SYSTEM,
                                      prompts.naive_prompt(board, self.show_legal_moves, feedback))
                raw = str(extract_json(text).get("move", ""))
            except Exception as e:  # LLM failure or unparseable reply
                err = f"unparseable reply ({type(e).__name__})"
                illegal.append(err)
                feedback = prompts.illegal_feedback(board, [err + ": reply with the JSON object only"])
                continue
            mv, why = parse_move(board, raw)
            if mv is not None:
                return MoveDecision(move=mv, san=board.san(mv), illegal_attempts=illegal,
                                    llm_calls=tally.calls, cost_usd=tally.cost,
                                    seconds=time.monotonic() - t0)
            illegal.append(f"{raw}: {why}")
            feedback = prompts.illegal_feedback(board, [f"{raw}: {why}"])
        return _exhausted(board, self.illegal_policy, self.rng, "naive", tally, t0, illegal)


# ── engine ──────────────────────────────────────────────────────────────────


class ClaudeEnginePlayer:
    """Claude as policy + value, Python as search on a real board."""

    def __init__(self, llm: LLM, use_context: bool = True, depth: int = 1, n_candidates: int = 4,
                 n_replies: int = 2, show_legal_moves: bool = True, illegal_policy: str = "random",
                 max_retries: int = 2, max_workers: int = MAX_WORKERS, seed: int | None = None,
                 name: str | None = None) -> None:
        assert depth in (0, 1, 2), "depth must be 0, 1 or 2"
        assert illegal_policy in ILLEGAL_POLICIES
        self.llm = llm
        self.use_context = use_context
        self.depth = depth
        self.n_candidates = n_candidates
        self.n_replies = n_replies
        self.show_legal_moves = show_legal_moves
        self.illegal_policy = illegal_policy
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.rng = random.Random(seed)
        self.name = name or (f"engine[{getattr(llm, 'model', '?')},ctx={int(use_context)},"
                             f"d={depth},legal={int(show_legal_moves)}]")

    # policy ---------------------------------------------------------------

    def _propose_once(self, tally: _Tally, board: chess.Board, n: int, feedback: str
                      ) -> tuple[list[tuple[Candidate, chess.Move]], list[str]]:
        """One proposer call -> (legal candidates sorted by prior desc, illegal/err strings)."""
        prompt = prompts.proposer_prompt(board, n, self.use_context, self.show_legal_moves, feedback)
        try:
            data = extract_json(tally.complete(prompts.PROPOSER_SYSTEM, prompt))
            items = data.get("candidates") or []
            if not isinstance(items, list):
                raise ValueError("candidates is not a list")
        except Exception as e:
            return [], [f"unparseable reply ({type(e).__name__})"]
        legal: list[tuple[Candidate, chess.Move]] = []
        bad: list[str] = []
        seen: set[chess.Move] = set()
        for it in items:
            if isinstance(it, str):
                it = {"move": it}
            if not isinstance(it, dict):
                continue
            raw = str(it.get("move", ""))
            mv, why = parse_move(board, raw)
            if mv is None:
                bad.append(f"{raw}: {why}")
                continue
            if mv in seen:
                continue
            seen.add(mv)
            try:
                prior = min(1.0, max(0.0, float(it.get("prior", 0.0))))
            except (TypeError, ValueError):
                prior = 0.0
            legal.append((Candidate(san=board.san(mv), reason=str(it.get("reason", "")), prior=prior), mv))
        legal.sort(key=lambda cm: -cm[0].prior)  # stable: ties keep proposer order
        return legal[:n], bad

    def _propose(self, tally: _Tally, board: chess.Board, n: int, retries: int
                 ) -> tuple[list[tuple[Candidate, chess.Move]], list[str]]:
        illegal: list[str] = []
        feedback = ""
        for _ in range(retries + 1):
            legal, bad = self._propose_once(tally, board, n, feedback)
            illegal.extend(bad)
            if legal:
                return legal, illegal
            feedback = prompts.illegal_feedback(board, bad or ["no candidates given"])
        return [], illegal

    # value ----------------------------------------------------------------

    def _evaluate(self, tally: _Tally, board: chess.Board) -> tuple[int, str]:
        """Score from WHITE's view. Terminal positions never reach Claude."""
        exact = terminal_score(board)
        if exact is not None:
            return exact, "terminal"
        prompt = prompts.evaluator_prompt(board, self.use_context)
        for _ in range(2):
            try:
                data = extract_json(tally.complete(prompts.EVALUATOR_SYSTEM, prompt, max_tokens=400))
                cp = int(round(float(data["eval_cp"])))
                return max(-EVAL_CLAMP, min(EVAL_CLAMP, cp)), str(data.get("reason", ""))
            except Exception:
                continue
        return 0, "evaluator failed; scored 0"

    # search ---------------------------------------------------------------

    def choose_move(self, board: chess.Board) -> MoveDecision:
        t0 = time.monotonic()
        board = board.copy()
        tally = _Tally(self.llm)
        cands, illegal = self._propose(tally, board, self.n_candidates, self.max_retries)
        if not cands:
            return _exhausted(board, self.illegal_policy, self.rng, "proposer", tally, t0, illegal)

        note = ""
        if self.depth == 1:
            self._search_d1(tally, board, cands)
        elif self.depth == 2:
            note = self._search_d2(tally, board, cands)

        if self.depth == 0:
            best_c, best_m = cands[0]
        else:
            best_c, best_m = max(cands, key=lambda cm: (cm[0].score_cp, cm[0].prior))
        return MoveDecision(move=best_m, san=best_c.san, candidates=[c for c, _ in cands],
                            illegal_attempts=illegal, llm_calls=tally.calls, cost_usd=tally.cost,
                            seconds=time.monotonic() - t0, note=note)

    def _search_d1(self, tally: _Tally, board: chess.Board,
                   cands: list[tuple[Candidate, chess.Move]]) -> None:
        sign = _sign(board.turn)

        def child(cm):
            b = board.copy(stack=True)
            b.push(cm[1])
            return self._evaluate(tally, b)

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            results = list(ex.map(child, cands))
        for (c, _), (cp, _why) in zip(cands, results):
            c.score_cp = sign * cp
            c.line = [c.san]

    def _search_d2(self, tally: _Tally, board: chess.Board,
                   cands: list[tuple[Candidate, chess.Move]]) -> str:
        sign = _sign(board.turn)
        children = []
        for _c, mv in cands:
            b = board.copy(stack=True)
            b.push(mv)
            children.append(b)

        # Phase 1: opponent proposer for every non-terminal child (parallel).
        def replies(b: chess.Board):
            if terminal_score(b) is not None:
                return [], []
            return self._propose(tally, b, self.n_replies, retries=1)

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            reply_sets = list(ex.map(replies, children))

        # Phase 2: evaluate every leaf (parallel). No legal reply proposed -> evaluate the child.
        leaves: list[tuple[int, list[str], chess.Board]] = []
        opp_illegal = 0
        for i, (b, (reps, bad)) in enumerate(zip(children, reply_sets)):
            opp_illegal += len(bad)
            if not reps:
                leaves.append((i, [], b))
                continue
            for rc, rm in reps:
                leaf = b.copy(stack=True)
                leaf.push(rm)
                leaves.append((i, [rc.san], leaf))

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            scores = list(ex.map(lambda t: self._evaluate(tally, t[2])[0], leaves))

        # Minimax: mover assumes the opponent picks the reply worst for the mover.
        for i, (c, _) in enumerate(cands):
            best: tuple[int, list[str]] | None = None
            for (j, line, _b), cp in zip(leaves, scores):
                if j != i:
                    continue
                mover_cp = sign * cp
                if best is None or mover_cp < best[0]:
                    best = (mover_cp, line)
            assert best is not None
            c.score_cp = best[0]
            c.line = [c.san] + best[1]
        return f"opponent-proposer illegal replies: {opp_illegal}" if opp_illegal else ""
