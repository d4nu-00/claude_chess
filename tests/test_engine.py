import json
import re
import threading

import chess
import pytest

from claude_chess.engine import MATE_CP, ClaudeEnginePlayer, NaiveClaudePlayer, parse_move, terminal_score
from claude_chess.engine import prompts
from claude_chess.types import LLMResponse


class FakeLLM:
    """Scripted LLM: `responder(kind, fen, prompt)` -> reply text. Thread-safe call log."""

    model = "fake"

    def __init__(self, responder):
        self.responder = responder
        self.calls = []
        self._lock = threading.Lock()

    def complete(self, system, prompt, max_tokens=1024):
        kind = ("proposer" if system == prompts.PROPOSER_SYSTEM else
                "evaluator" if system == prompts.EVALUATOR_SYSTEM else "naive")
        fen = re.search(r"^FEN: (.+)$", prompt, re.M).group(1)
        with self._lock:
            self.calls.append((kind, fen, prompt))
        return LLMResponse(text=self.responder(kind, fen, prompt), cost_usd=0.01)

    def count(self, kind):
        return sum(1 for k, _, _ in self.calls if k == kind)


def cands(*moves):
    return json.dumps({"thinking": "t", "candidates": [
        {"move": m, "reason": "r", "prior": p} for m, p in moves]})


def fen_after(board, *sans):
    b = board.copy()
    for s in sans:
        b.push_san(s)
    return b.fen()


def test_parse_move():
    b = chess.Board()
    assert parse_move(b, "e4")[0] == chess.Move.from_uci("e2e4")
    assert parse_move(b, "g1f3")[0] == chess.Move.from_uci("g1f3")
    assert parse_move(b, "e5")[0] is None
    assert parse_move(b, "banana")[0] is None


def test_terminal_score():
    assert terminal_score(chess.Board("k7/8/1K6/8/8/8/8/7R b - - 0 1")) is None
    assert terminal_score(chess.Board("R1k5/8/2K5/8/8/8/8/8 b - - 0 1")) == MATE_CP
    assert terminal_score(chess.Board("k7/8/1Q6/8/8/8/8/7K b - - 0 1")) == 0  # stalemate
    b = chess.Board("k7/8/8/8/8/8/8/7K w - - 0 1")  # insufficient material
    assert terminal_score(b) == 0


def test_naive_illegal_then_legal():
    answers = iter(['{"move": "e5"}', 'not json at all', '{"move": "Nf3"}'])
    llm = FakeLLM(lambda k, f, p: next(answers))
    d = NaiveClaudePlayer(llm).choose_move(chess.Board())
    assert d.san == "Nf3" and d.llm_calls == 3
    assert d.illegal_attempts[0].startswith("e5") and "unparseable" in d.illegal_attempts[1]
    assert "complete list of legal moves" in llm.calls[1][2] and "e5" in llm.calls[1][2]


@pytest.mark.parametrize("policy", ["random", "forfeit"])
def test_exhaustion_policies(policy):
    llm = FakeLLM(lambda k, f, p: cands(("Ke2", 0.9)) if k == "proposer" else '{"move": "Qxh7"}')
    for player in (ClaudeEnginePlayer(llm, use_context=False, depth=1, illegal_policy=policy, max_retries=3, seed=1),
                   NaiveClaudePlayer(llm, illegal_policy=policy, max_retries=3, seed=1)):
        d = player.choose_move(chess.Board())
        assert len(d.illegal_attempts) == 4 and d.llm_calls == 4
        assert d.forced_random == (policy == "random")
        if policy == "random":
            assert d.move in chess.Board().legal_moves and "random" in d.note
        else:
            assert d.move is None and d.forfeit_reason


def test_engine_retry_then_success():
    answers = iter([cands(("Ke2", 0.9), ("e5", 0.1)), cands(("d4", 0.5))])
    llm = FakeLLM(lambda k, f, p: next(answers))
    d = ClaudeEnginePlayer(llm, use_context=False, depth=0).choose_move(chess.Board())
    assert d.san == "d4" and d.illegal_attempts == ["Ke2: illegal in this position", "e5: illegal in this position"]
    assert "Ke2: illegal" in llm.calls[1][2]


def test_depth0_highest_prior_and_drops_illegal():
    llm = FakeLLM(lambda k, f, p: cands(("e4", 0.3), ("Qh5", 0.9), ("Nf3", 0.6)))
    d = ClaudeEnginePlayer(llm, use_context=False, depth=0).choose_move(chess.Board())
    assert d.san == "Nf3" and d.illegal_attempts == ["Qh5: illegal in this position"]
    assert d.llm_calls == 1 and llm.count("evaluator") == 0


def test_depth1_picks_best_evaluated():
    b = chess.Board()
    evals = {fen_after(b, "e4"): 30, fen_after(b, "d4"): 80, fen_after(b, "Nf3"): 20}
    llm = FakeLLM(lambda k, f, p: cands(("e4", 0.6), ("d4", 0.3), ("Nf3", 0.1)) if k == "proposer"
                  else json.dumps({"eval_cp": evals[f], "reason": "x"}))
    d = ClaudeEnginePlayer(llm, use_context=False, depth=1).choose_move(b)
    assert d.san == "d4" and d.llm_calls == 4 and abs(d.cost_usd - 0.04) < 1e-9
    assert {c.san: c.score_cp for c in d.candidates} == {"e4": 30, "d4": 80, "Nf3": 20}


def test_depth1_black_perspective():
    b = chess.Board()
    b.push_san("e4")
    evals = {fen_after(b, "e5"): 40, fen_after(b, "c5"): -200, fen_after(b, "a6"): 300}
    llm = FakeLLM(lambda k, f, p: cands(("e5", 0.5), ("c5", 0.3), ("a6", 0.2)) if k == "proposer"
                  else json.dumps({"eval_cp": evals[f]}))
    d = ClaudeEnginePlayer(llm, use_context=False, depth=1).choose_move(b)
    assert d.san == "c5"
    assert {c.san: c.score_cp for c in d.candidates} == {"e5": -40, "c5": 200, "a6": -300}


def test_depth2_minimax_worst_reply():
    b = chess.Board()
    evals = {
        fen_after(b, "e4", "e5"): 50, fen_after(b, "e4", "c5"): -100,  # e4 worst = -100
        fen_after(b, "d4", "d5"): 10, fen_after(b, "d4", "Nf6"): 20,   # d4 worst = +10
    }
    replies = {fen_after(b, "e4"): cands(("e5", 0.5), ("c5", 0.5)),
               fen_after(b, "d4"): cands(("d5", 0.5), ("Nf6", 0.5))}

    def resp(k, f, p):
        if k == "proposer":
            return cands(("e4", 0.8), ("d4", 0.2)) if f == b.fen() else replies[f]
        return json.dumps({"eval_cp": evals[f]})

    llm = FakeLLM(resp)
    d = ClaudeEnginePlayer(llm, use_context=False, depth=2, n_candidates=2, n_replies=2).choose_move(b)
    assert d.san == "d4"
    by = {c.san: c for c in d.candidates}
    assert by["e4"].score_cp == -100 and by["e4"].line == ["e4", "c5"]
    assert by["d4"].score_cp == 10 and by["d4"].line == ["d4", "d5"]
    assert d.llm_calls == 1 + 2 + 4  # proposer + opponent proposers + leaves


@pytest.mark.parametrize("depth", [1, 2])
def test_terminal_mate_scored_without_evaluator(depth):
    b = chess.Board("k7/8/1K6/8/8/8/8/7R w - - 0 1")

    def resp(k, f, p):
        if k == "proposer":
            return cands(("Rh7", 0.7), ("Rh8#", 0.3)) if f == b.fen() else cands(("Kb8", 1.0))
        assert f != fen_after(b, "Rh8#"), "terminal node sent to evaluator"
        return json.dumps({"eval_cp": 900})

    llm = FakeLLM(resp)
    d = ClaudeEnginePlayer(llm, use_context=False, depth=depth).choose_move(b)
    assert d.san == "Rh8#"
    assert {c.san: c.score_cp for c in d.candidates}["Rh8#"] == MATE_CP
    assert llm.count("evaluator") == 1
    assert all(f != fen_after(b, "Rh8#") for k, f, _ in llm.calls if k == "proposer")


def test_context_toggle(monkeypatch):
    import claude_chess.context as ctxmod
    monkeypatch.setattr(ctxmod, "build_context", lambda board, include_legal_moves=True: "CTX",
                        raising=False)
    monkeypatch.setattr(ctxmod, "render_context",
                        lambda ctx, include_legal_moves=True: "RENDERED-CONTEXT", raising=False)
    b = chess.Board()
    on = prompts.proposer_prompt(b, 3, use_context=True, show_legal_moves=False)
    off = prompts.proposer_prompt(b, 3, use_context=False, show_legal_moves=True)
    assert "RENDERED-CONTEXT" in on and "Legal moves:" not in on
    assert "RENDERED-CONTEXT" not in off and "Legal moves:" in off and "Nf3" in off
    ev = prompts.evaluator_prompt(b, use_context=True)
    assert "RENDERED-CONTEXT" in ev and "Legal moves:" not in ev
