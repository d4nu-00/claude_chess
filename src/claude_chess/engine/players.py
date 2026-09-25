"""Claude players: NaiveClaudePlayer (one call) and ClaudeEnginePlayer (propose -> validate -> search).

Score conventions (wiki/pages/engine.md): the evaluator returns centipawns from WHITE's
view; search converts to the mover's view; Candidate.score_cp is from the mover's view.
Terminal positions are scored exactly (mate = ±MATE_CP, draw = 0) without calling Claude.
"""

from __future__ import annotations

import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import chess

from claude_chess.engine import boardread, prompts, tactical
from claude_chess.llm import LLMUnavailable, extract_json
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


def board_san(board: chess.Board, mv: chess.Move) -> str:
    return board.san(mv)


def _sign(color: chess.Color) -> int:
    return 1 if color == chess.WHITE else -1


class _Tally:
    """Per-decision, thread-safe accounting of LLM calls/cost."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.calls = 0
        self.cost = 0.0
        self.traces: list[dict] = []  # every call, for the reasoning dataset (dataset.py)
        self._lock = threading.Lock()

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        resp = self.llm.complete(system, prompt, max_tokens=max_tokens)
        m = _FEN_RE.search(prompt)
        with self._lock:
            self.calls += 1
            self.cost += resp.cost_usd
            self.traces.append({
                "role": prompts.ROLES.get(system, "other"), "model": getattr(self.llm, "model", "?"),
                "fen": m.group(1) if m else None, "prompt": prompt, "response": resp.text,
                "cost_usd": resp.cost_usd, "seconds": round(resp.seconds, 3),
                "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            })
        return resp.text


_FEN_RE = re.compile(r"^FEN: (.+)$", re.M)


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
                 max_retries: int = 2, seed: int | None = None, name: str | None = None,
                 board_read: bool = False) -> None:
        assert illegal_policy in ILLEGAL_POLICIES
        self.llm = llm
        self.board_read = board_read
        self.show_legal_moves = show_legal_moves
        self.illegal_policy = illegal_policy
        self.max_retries = max_retries
        self.rng = random.Random(seed)
        self.book = False  # opening book (set by the CLI's --book)
        self.name = name or f"naive[{getattr(llm, 'model', '?')},legal={int(show_legal_moves)}]"

    def _book(self, board: chess.Board, t0: float) -> MoveDecision | None:
        """Opening book (ECO main lines): known theory costs no Claude calls. Off by default."""
        if not self.book:
            return None
        from claude_chess.context.book import book_move
        mv = book_move(board, self.rng)
        if mv is None:
            return None
        return MoveDecision(move=mv, san=board.san(mv), llm_calls=0, seconds=time.monotonic() - t0, note="book")


    def choose_move(self, board: chess.Board) -> MoveDecision:
        tally = _Tally(self.llm)
        dec = self._choose(board, tally)
        dec.traces = tally.traces
        return dec

    def _choose(self, board: chess.Board, tally: _Tally) -> MoveDecision:
        t0 = time.monotonic()
        if (bk := self._book(board, t0)) is not None:
            return bk
        illegal: list[str] = []
        feedback = ""
        for _ in range(self.max_retries + 1):
            try:
                prompt = prompts.naive_prompt(board, self.show_legal_moves, feedback)
                if self.board_read:
                    prompt += "\n" + boardread.INSTRUCTION
                data = extract_json(tally.complete(prompts.NAIVE_SYSTEM, prompt))
                raw = str(data.get("move", ""))
            except LLMUnavailable:
                raise  # infrastructure failure, not an illegal move: runner aborts the game
            except Exception as e:  # unparseable reply
                err = f"unparseable reply ({type(e).__name__})"
                illegal.append(err)
                feedback = prompts.illegal_feedback(board, [err + ": reply with the JSON object only"])
                continue
            mv, why = parse_move(board, raw)
            if mv is not None:
                return MoveDecision(move=mv, san=board.san(mv), illegal_attempts=illegal,
                                    llm_calls=tally.calls, cost_usd=tally.cost,
                                    seconds=time.monotonic() - t0,
                                    board_read=boardread.score(board, data) if self.board_read else None)
            illegal.append(f"{raw}: {why}")
            feedback = prompts.illegal_feedback(board, [f"{raw}: {why}"])
        return _exhausted(board, self.illegal_policy, self.rng, "naive", tally, t0, illegal)


# ── engine ──────────────────────────────────────────────────────────────────


class ClaudeEnginePlayer:
    """Claude as policy + value, Python as search on a real board.

    `tactical=True` switches to the hybrid pipeline (wiki/pages/computer-chess-principles.md):
    Claude proposes, a material-only alpha-beta + quiescence search (engine/tactical.py)
    vetoes tactically losing candidates and injects winning forcing moves, and ONE batched
    Claude call ranks the survivors on positional merit. `depth` is ignored in that mode.
    """

    def __init__(self, llm: LLM, use_context: bool = True, depth: int = 1, n_candidates: int = 4,
                 n_replies: int = 2, show_legal_moves: bool = True, illegal_policy: str = "random",
                 max_retries: int = 2, max_workers: int = MAX_WORKERS, seed: int | None = None,
                 name: str | None = None, tactical: bool = False, tac_depth: int = 2,
                 tac_margin: int = 100, pos_cap: int = 150, board_read: bool = False,
                 threat_agent: bool = False, tablebase: bool = True,
                 search: str = "compare", ctx_version: int = 2) -> None:
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
        self.book = False  # opening book (set by the CLI's --book)
        self.tactical = tactical
        self.board_read = board_read
        self.threat_agent = threat_agent  # hybrid only: extra Claude call hunting refutations
        self.tablebase = tablebase  # hybrid only: play tablebase moves when a probe answers
        assert search in ("compare", "alphabeta")
        self.search = search  # hybrid only: 1-ply batched compare, or depth-2 alpha-beta
        # 2 = original context; 3 = relations, last-move changes, per-candidate deltas,
        # adaptive ordering, legal-move material check, wider fail-low (context-research).
        self.ctx_version = ctx_version
        self.tac_depth = tac_depth
        self.tac_margin = tac_margin
        self.pos_cap = pos_cap
        # Transposition table for Claude's static evals (position -> (cp, reason)): the same
        # position recurs across sibling lines and across moves of one game.
        self._tt: dict = {}
        self._tt_lock = threading.Lock()
        kind = "hybrid" if tactical else f"d={depth}"
        self.name = name or (f"engine[{getattr(llm, 'model', '?')},ctx={int(use_context)},"
                             f"{kind},legal={int(show_legal_moves)}]")

    # policy ---------------------------------------------------------------

    def _propose_once(self, tally: _Tally, board: chess.Board, n: int, feedback: str,
                      read: bool = False
                      ) -> tuple[list[tuple[Candidate, chess.Move]], list[str], dict]:
        """One proposer call -> (legal candidates sorted by prior desc, illegal/err strings, raw JSON)."""
        prompt = prompts.proposer_prompt(board, n, self.use_context, self.show_legal_moves, feedback,
                                         v=self.ctx_version)
        if read:
            prompt += "\n" + boardread.INSTRUCTION
        data: dict = {}
        try:
            data = extract_json(tally.complete(prompts.PROPOSER_SYSTEM, prompt))
            items = data.get("candidates") or []
            if not isinstance(items, list):
                raise ValueError("candidates is not a list")
        except LLMUnavailable:
            raise
        except Exception as e:
            return [], [f"unparseable reply ({type(e).__name__})"], data
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
            sac = it.get("sacrifice") in (True, "true", "yes", 1)
            legal.append((Candidate(san=board.san(mv), reason=str(it.get("reason", "")), prior=prior,
                                    sacrifice=sac, compensation=str(it.get("compensation", "")) if sac else ""),
                          mv))
        legal.sort(key=lambda cm: -cm[0].prior)  # stable: ties keep proposer order
        return legal[:n], bad, data

    def _propose(self, tally: _Tally, board: chess.Board, n: int, retries: int, read: bool = False
                 ) -> tuple[list[tuple[Candidate, chess.Move]], list[str]]:
        illegal: list[str] = []
        feedback = ""
        self._last_read = None
        for _ in range(retries + 1):
            legal, bad, data = self._propose_once(tally, board, n, feedback, read)
            illegal.extend(bad)
            if legal:
                if read:
                    self._last_read = boardread.score(board, data)
                return legal, illegal
            feedback = prompts.illegal_feedback(board, bad or ["no candidates given"])
        return [], illegal

    # value ----------------------------------------------------------------

    def _evaluate(self, tally: _Tally, board: chess.Board) -> tuple[int, str]:
        """Score from WHITE's view. Terminal positions never reach Claude."""
        exact = terminal_score(board)
        if exact is not None:
            return exact, "terminal"
        key = board._transposition_key()
        with self._tt_lock:
            hit = self._tt.get(key)
        if hit is not None:
            return hit
        prompt = prompts.evaluator_prompt(board, self.use_context, v=self.ctx_version)
        for _ in range(2):
            try:
                data = extract_json(tally.complete(prompts.EVALUATOR_SYSTEM, prompt, max_tokens=400))
                cp = int(round(float(data["eval_cp"])))
                res = max(-EVAL_CLAMP, min(EVAL_CLAMP, cp)), str(data.get("reason", ""))
                with self._tt_lock:
                    self._tt[key] = res
                return res
            except LLMUnavailable:
                raise
            except Exception:
                continue
        return 0, "evaluator failed; scored 0"

    # search ---------------------------------------------------------------

    def _book(self, board: chess.Board, t0: float) -> MoveDecision | None:
        """Opening book (ECO main lines): known theory costs no Claude calls. Off by default."""
        if not self.book:
            return None
        from claude_chess.context.book import book_move
        mv = book_move(board, self.rng)
        if mv is None:
            return None
        return MoveDecision(move=mv, san=board.san(mv), llm_calls=0, seconds=time.monotonic() - t0, note="book")

    def choose_move(self, board: chess.Board) -> MoveDecision:
        tally = _Tally(self.llm)
        dec = self._choose(board.copy(), tally)
        dec.traces = tally.traces
        return dec

    def _choose(self, board: chess.Board, tally: _Tally) -> MoveDecision:
        t0 = time.monotonic()
        if (bk := self._book(board, t0)) is not None:
            return bk
        if self.tactical:
            legal = list(board.legal_moves)
            if len(legal) == 1:  # forced move: no need to think
                return MoveDecision(move=legal[0], san=board.san(legal[0]), llm_calls=0,
                                    seconds=time.monotonic() - t0, note="only legal move")
        cands, illegal = self._propose(tally, board, self.n_candidates, self.max_retries,
                                       read=self.board_read)
        read = self._last_read
        if not cands:
            return _exhausted(board, self.illegal_policy, self.rng, "proposer", tally, t0, illegal)
        if self.tactical:
            dec = self._choose_hybrid(tally, board, cands, illegal, t0)
            dec.board_read = read
            return dec

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
                            seconds=time.monotonic() - t0, note=note, board_read=read)

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

    # hybrid: Claude policy + tactical verification + batched positional value ----------

    def _choose_hybrid(self, tally: _Tally, board: chess.Board,
                       cands: list[tuple[Candidate, chess.Move]], illegal: list[str],
                       t0: float) -> MoveDecision:
        notes: list[str] = []
        pool = list(cands)
        info: dict = {"mode": self.search, "candidates": {}}

        def decide(c: Candidate, m: chess.Move, why: str) -> MoveDecision:
            info["decided_by"] = why
            return MoveDecision(move=m, san=c.san, candidates=[pc for pc, _ in pool],
                                illegal_attempts=illegal, llm_calls=tally.calls, cost_usd=tally.cost,
                                seconds=time.monotonic() - t0, note="; ".join(notes + [why]),
                                search_info=info)

        # Endgame tablebase: the result is known exactly — look it up, don't calculate.
        if self.tablebase:
            from claude_chess.context.tablebase import probe
            tb = probe(board)
            best = tb.best_moves() if tb else []
            if best:
                claude_best = [(c, m) for c, m in cands if c.san in best]
                if claude_best:
                    c, m = claude_best[0]
                else:
                    m = board.parse_san(best[0])
                    c = Candidate(san=best[0], reason=f"tablebase {tb.verdict}", prior=0.0)
                    pool.append((c, m))
                return decide(c, m, f"tablebase ({tb.source}): {tb.verdict}")

        # Deeper tactical search when few pieces remain (branching factor is small).
        depth = self.tac_depth
        if chess.popcount(board.occupied & ~board.pawns & ~board.kings) <= 4:
            depth += 1

        claude_moves = {mv for _, mv in cands}
        extra = [m for m in tactical.forcing_moves(board) if m not in claude_moves]
        verdicts = {v.move: v for v in tactical.score_moves(board, [mv for _, mv in cands] + extra,
                                                              depth=depth)}
        best_claude = max(verdicts[mv].score for _, mv in cands)
        fail_low = 0 if self.ctx_version >= 3 else -self.tac_margin
        if best_claude < fail_low:
            # Fail low: every Claude idea loses material -> widen to all legal moves.
            rest = [m for m in board.legal_moves if m not in verdicts]
            verdicts.update({v.move: v for v in tactical.score_moves(board, rest, depth=depth)})
            extra += rest
            notes.append("fail-low: searched all moves")

        # Moves Claude missed enter only if materially clearly better than all its proposals.
        for m in extra:
            v = verdicts[m]
            if v.score >= best_claude + self.tac_margin:
                what = f"mates in {v.mate}" if v.mate > 0 else f"wins {v.score - best_claude:+d}cp"
                pool.append((Candidate(san=board.san(m), reason=f"engine: {what}", prior=0.0), m))
                notes.append(f"injected {board.san(m)}")

        tscore = {m: verdicts[m].score for _, m in pool}
        claude_set = {m for _, m in cands}
        for c, m in pool:
            v = verdicts[m]
            c.score_cp = v.score
            c.line = [c.san] + ([v.refutation] if v.refutation else [])
            info["candidates"][c.san] = {
                "source": "claude" if m in claude_set else "engine", "prior": c.prior,
                "reason": c.reason, "tactical_cp": v.score, "mate": v.mate,
                "engine_reply": v.refutation or None, "vetoed": False}

        # Forced mate found by the search: play the fastest one.
        mates = [(verdicts[m].mate, c, m) for c, m in pool if verdicts[m].mate > 0]
        if mates:
            _, c, m = min(mates, key=lambda t: t[0])
            return decide(c, m, f"mate in {verdicts[m].mate} plies")

        # Tactical veto: drop moves materially worse than the best by more than the margin.
        survivors = self._veto(pool, tscore, notes, info)
        if len(survivors) == 1:
            c, m = survivors[0]
            return decide(c, m, "only tactically sound candidate")

        if self.search == "alphabeta":
            threats = self._threats(tally, board.copy(), survivors, verdicts, depth)
            self._apply_threats(survivors, threats, tscore, notes, info)
            survivors = self._veto(survivors, tscore, notes, info)
            if len(survivors) == 1:
                c, m = survivors[0]
                return decide(c, m, "only sound candidate after threat check")
            c, m = self._alphabeta(tally, board, survivors, verdicts, tscore, threats, depth, notes, info)
            return decide(c, m, "alpha-beta")

        # Positional value (one batched call) and the threat agent run in parallel.
        # Each thread gets its own board copy: the context builder push/pops on the board it
        # is given, so sharing one board across threads corrupts it (seen as a forfeit).
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_pos = ex.submit(self._compare, tally, board.copy(), survivors, verdicts)
            f_thr = ex.submit(self._threats, tally, board.copy(), survivors, verdicts, depth) \
                if self.threat_agent else None
            pos = f_pos.result()
            threats = f_thr.result() if f_thr else {}
        self._apply_threats(survivors, threats, tscore, notes, info)
        if threats:
            survivors = self._veto(survivors, tscore, notes, info)
        if pos is None:
            notes.append("compare failed; used tactics+prior")
            pos = {m: 0 for _, m in survivors}
        for c, m in survivors:
            c.score_cp = tscore[m] + pos.get(m, 0)
            info["candidates"][c.san].update(positional_cp=pos.get(m, 0), final_cp=c.score_cp)
        c, m = max(survivors, key=lambda cm: (cm[0].score_cp, cm[0].prior))
        return decide(c, m, "hybrid")

    def _apply_threats(self, survivors, threats, tscore, notes, info) -> None:
        for m, t in threats.items():
            c = next(c for c, mm in survivors if mm == m)
            info["candidates"][c.san].update(threat_reply=t["reply"], threat_idea=t["idea"],
                                             threat_cp=t["score"], threat_verified=False)
            if t["score"] < tscore[m] - 50:  # verified: the agent's reply really costs material
                notes.append(f"threat {c.san}?{t['reply']} ({tscore[m]:+d}->{t['score']:+d})")
                tscore[m] = t["score"]
                c.line = [c.san, t["reply"]]
                info["candidates"][c.san]["threat_verified"] = True

    # alpha-beta over Claude-evaluated leaves --------------------------------------

    def _reply_score(self, after: chess.Board, reply: chess.Move, depth: int, base: int) -> int:
        """Material swing (mover's view) after `reply`, resolved by full-width search."""
        b = after.copy(stack=True)
        b.push(reply)
        if b.is_checkmate():
            return -tactical.MATE_CP
        v = tactical.TacticalSearch(node_limit=60_000).search(b, depth)
        return v if abs(v) > tactical.MATE_BAND else v - base

    def _positional(self, tally: _Tally, board: chess.Board) -> tuple[int, str]:
        """Claude's positional-only score of a leaf, WHITE's view, clamped to ±pos_cap. TT-cached."""
        exact = terminal_score(board)
        if exact is not None:
            return 0, "terminal"
        key = ("pos", board._transposition_key())
        with self._tt_lock:
            hit = self._tt.get(key)
        if hit is not None:
            return hit
        prompt = prompts.positional_prompt(board, self.use_context, v=self.ctx_version)
        for _ in range(2):
            try:
                data = extract_json(tally.complete(prompts.POSITIONAL_SYSTEM, prompt, max_tokens=300))
                cp = int(round(float(data["positional_cp"])))
                res = max(-self.pos_cap, min(self.pos_cap, cp)), str(data.get("reason", ""))
                with self._tt_lock:
                    self._tt[key] = res
                return res
            except LLMUnavailable:
                raise
            except Exception:
                continue
        return 0, "positional eval failed"

    def _alphabeta(self, tally, board, survivors, verdicts, tscore, threats, depth, notes, info):
        """Depth-2 alpha-beta: max over our candidates of min over opponent replies.

        Leaves = exact material swing (Python search) + Claude positional score (±pos_cap).
        Reply set per candidate: engine refutation, threat agent's dangerous + natural reply.
        Pruning (each saves a Claude call):
          - move ordering: candidates by tactical score then prior; replies most-damaging first
          - futility: a leaf whose material + pos_cap <= alpha refutes without a Claude call
          - beta cutoff: once a reply drops a candidate to <= alpha, its other replies are skipped
          - root futility: a candidate whose best-case bound <= alpha is skipped entirely
        The first ("eldest brother") candidate's leaves are evaluated in parallel (YBWC);
        later ones sequentially so cutoffs can fire.
        """
        us = board.turn
        sign = _sign(us)
        base = tactical.material(board) * sign
        replies: dict = {}
        for c, m in survivors:
            after = board.copy(stack=True)
            after.push(m)
            rs: dict = {}
            names = [verdicts[m].refutation]
            t = threats.get(m)
            if t:
                names += [t["reply"], t.get("alt") or ""]
            for name in names:
                mv, _ = parse_move(after, name or "")
                if mv is not None and mv not in rs:
                    rs[mv] = self._reply_score(after, mv, depth, base)
            if not rs:  # opponent has no proposed reply (e.g. stalemate/mate handled above)
                rs = {None: tscore[m]}
            replies[m] = (after, sorted(rs.items(), key=lambda kv: kv[1]))  # most damaging first

        order = sorted(survivors, key=lambda cm: (-tscore[cm[1]], -cm[0].prior))
        cap = self.pos_cap
        alpha = -10 ** 9
        best = order[0]
        total = sum(len(r[1]) for r in replies.values())
        evaluated = pruned = 0

        def leaf(after: chess.Board, r: chess.Move | None, mat: int) -> int:
            if r is None or abs(mat) >= tactical.MATE_BAND:
                return mat
            b = after.copy(stack=True)
            b.push(r)
            if terminal_score(b) is not None:
                return mat
            pos, _why = self._positional(tally, b.copy())
            return mat + sign * pos

        for k, (c, m) in enumerate(order):
            after, rs = replies[m]
            cinfo = info["candidates"][c.san]
            if min(mat for _, mat in rs) + cap <= alpha:  # root futility
                pruned += len(rs)
                cinfo.update(ab_value=None, ab_pruned="futile")
                continue
            if k == 0:
                todo = [(r, mat) for r, mat in rs]
                with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                    vals = list(ex.map(lambda rm: leaf(after, rm[0], rm[1]), todo))
                evaluated += sum(1 for r, mat in todo if r is not None and abs(mat) < tactical.MATE_BAND)
                value = min(vals)
                line = [c.san] + ([board_san(after, todo[vals.index(value)][0])] if todo[vals.index(value)][0] else [])
            else:
                value, line = 10 ** 9, [c.san]
                for i, (r, mat) in enumerate(rs):
                    if mat + cap <= alpha:  # futility: refuted whatever Claude says
                        value, line = mat, [c.san] + ([board_san(after, r)] if r else [])
                        pruned += len(rs) - i
                        break
                    v = leaf(after, r, mat)
                    evaluated += 1
                    if v < value:
                        value, line = v, [c.san] + ([board_san(after, r)] if r else [])
                    if value <= alpha:  # beta cutoff
                        pruned += len(rs) - i - 1
                        break
            c.score_cp = value
            c.line = line
            cinfo.update(ab_value=value, ab_line=line)
            if value > alpha or (value == alpha and c.prior > best[0].prior):
                alpha, best = value, (c, m)
        notes.append(f"ab: {evaluated} leaf evals, {pruned}/{total} pruned")
        info["alphabeta"] = {"leaves": total, "evaluated": evaluated, "pruned": pruned}
        return best

    def _veto(self, pool, tscore, notes, info=None):
        """Drop candidates materially worse than the best by more than tac_margin — except
        declared sacrifices (material is not everything; Claude judges the compensation in
        _compare), which only a forced mate against the mover can veto."""
        best_t = max(tscore[m] for _, m in pool)

        def ok(c, m) -> bool:
            if tscore[m] >= best_t - self.tac_margin:
                return True
            return c.sacrifice and tscore[m] > -tactical.MATE_BAND

        keep = [(c, m) for c, m in pool if ok(c, m)]
        vetoed = [c.san for c, m in pool if not ok(c, m)]
        spared = [c.san for c, m in keep if tscore[m] < best_t - self.tac_margin]
        if spared:
            notes.append("sacrifice kept " + ",".join(spared))
        if vetoed:
            notes.append("vetoed " + ",".join(vetoed))
            for san in vetoed:
                if info is not None:
                    info["candidates"][san]["vetoed"] = True
        return keep

    def _threats(self, tally: _Tally, board: chess.Board,
                 survivors: list[tuple[Candidate, chess.Move]], verdicts: dict, depth: int
                 ) -> dict:
        """Threat agent: Claude names the opponent's most dangerous reply to each candidate;
        Python VERIFIES it (plays it, then searches full width) — an LLM-guided selective
        extension. Returns {move: {reply, idea, score (verified material swing), alt}}."""
        options = []
        afters = {}
        for c, m in survivors:
            b = board.copy(stack=True)
            b.push(m)
            afters[m] = b
            options.append((c.san, verdicts[m].refutation, b))
        prompt = prompts.threat_prompt(board, options, self.use_context, v=self.ctx_version)
        try:
            data = extract_json(tally.complete(prompts.THREAT_SYSTEM, prompt, max_tokens=600))
        except LLMUnavailable:
            raise
        except Exception:
            return {}
        by_san = {c.san: m for c, m in survivors}
        base = tactical.material(board) * _sign(board.turn)
        out: dict = {}
        for it in data.get("replies") or []:
            if not isinstance(it, dict):
                continue
            m = by_san.get(str(it.get("move", "")).strip())
            if m is None:
                mv, _ = parse_move(board, str(it.get("move", "")))
                m = mv if mv in afters else None
            if m is None:
                continue
            b = afters[m].copy(stack=True)
            reply, _why = parse_move(b, str(it.get("reply", "")))
            if reply is None:
                continue
            alt, _ = parse_move(b, str(it.get("alt", "")))
            out[m] = {"reply": b.san(reply), "idea": str(it.get("idea", "")),
                      "score": self._reply_score(b, reply, depth, base),  # our move again: full width
                      "alt": b.san(alt) if alt is not None else None}
        return out

    def _compare(self, tally: _Tally, board: chess.Board,
                 survivors: list[tuple[Candidate, chess.Move]],
                 verdicts: dict) -> dict | None:
        options = []
        for c, m in survivors:
            b = board.copy(stack=False)
            b.push(m)
            v = verdicts[m]
            options.append((c.san, v.score, v.refutation, b.fen()))
        sacs = {c.san: (c.compensation or "not stated") for c, m in survivors
                if c.sacrifice and verdicts[m].score < 0}
        prompt = prompts.compare_prompt(board, options, self.use_context, v=self.ctx_version, sacrifices=sacs)
        by_san = {c.san: m for c, m in survivors}
        for _ in range(2):
            try:
                data = extract_json(tally.complete(prompts.COMPARE_SYSTEM, prompt, max_tokens=600))
                out: dict = {}
                for it in data.get("scores") or []:
                    mv, _why = parse_move(board, str(it.get("move", "")))
                    if mv is None or mv not in by_san.values():
                        continue
                    sc = max(-self.pos_cap, min(self.pos_cap, int(round(float(it.get("score", 0))))))
                    san = next(c.san for c, m in survivors if m == mv)
                    if san in sacs:  # compensation can pay back at most the material given up
                        comp = int(round(float(it.get("compensation_cp", 0) or 0)))
                        sc += max(0, min(-verdicts[mv].score, comp))
                    out[mv] = sc
                if not out:
                    raise ValueError("no usable scores")
                return {m: out.get(m, 0) for _, m in survivors}
            except LLMUnavailable:
                raise
            except Exception:
                continue
        return None
