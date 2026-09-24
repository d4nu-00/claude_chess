"""Hybrid (tactical) search + board-vision probe. FakeLLM only — no Claude calls."""

import json

import chess

from claude_chess.engine import ClaudeEnginePlayer, NaiveClaudePlayer, boardread, prompts, tactical
from claude_chess.types import LLMResponse


class Fake:
    model = "fake"

    def __init__(self, proposer, compare=None, naive=None):
        self.proposer, self.compare, self.naive = proposer, compare, naive
        self.systems = []

    def complete(self, system, prompt, max_tokens=1024):
        self.systems.append(system)
        if system == prompts.PROPOSER_SYSTEM:
            text = self.proposer
        elif system == prompts.COMPARE_SYSTEM:
            text = self.compare
        else:
            text = self.naive
        return LLMResponse(text=text, cost_usd=0.001)


def cands(*moves, **extra):
    return json.dumps({"candidates": [{"move": m, "prior": p} for m, p in moves], **extra})


def test_material_and_hanging_queen():
    b = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")  # white rook takes undefended queen
    assert tactical.material(b) == 500 - 900
    v = {b.san(x.move): x for x in tactical.score_moves(b, list(b.legal_moves), depth=2)}
    assert v["Rxd5"].score >= 800
    assert v["Rd3"].score <= -400  # rook left en prise to the queen (Qxd3)


def test_finds_mate_in_one_and_detects_allowed_mate():
    b = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    v = {b.san(x.move): x for x in tactical.score_moves(b, list(b.legal_moves), depth=2)}
    assert v["Ra8#"].mate == 1
    # Black to move after a quiet white move: back-rank mate threat must be seen.
    b2 = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 b - - 0 1")
    v2 = {b2.san(x.move): x for x in tactical.score_moves(b2, list(b2.legal_moves), depth=2)}
    assert v2["Kf8"].mate == 0 and v2["h6"].mate == 0  # luft / king walk avoid mate
    assert v2["f6"].mate == 0
    assert v2["Kh8"].mate < 0  # Ra8# follows


def test_hybrid_vetoes_blunder_and_injects_tactic():
    # Claude proposes only quiet moves; Rxd5 wins the queen and must be played without a compare call.
    b = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")
    llm = Fake(cands(("Rd3", 0.6), ("Ke2", 0.4)))
    p = ClaudeEnginePlayer(llm, use_context=False, tactical=True)
    d = p.choose_move(b)
    assert d.san == "Rxd5"
    assert "injected Rxd5" in d.note
    assert prompts.COMPARE_SYSTEM not in llm.systems


def test_hybrid_mate_in_one_played():
    b = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    d = ClaudeEnginePlayer(Fake(cands(("Kf2", 1.0))), use_context=False, tactical=True).choose_move(b)
    assert d.san == "Ra8#"


def test_hybrid_compare_picks_positional_best():
    b = chess.Board()
    llm = Fake(cands(("e4", 0.5), ("d4", 0.3), ("a3", 0.2)),
               compare=json.dumps({"scores": [{"move": "e4", "score": 20}, {"move": "d4", "score": 90},
                                              {"move": "a3", "score": -100}]}))
    d = ClaudeEnginePlayer(llm, use_context=False, tactical=True).choose_move(b)
    assert d.san == "d4"
    assert d.llm_calls == 2  # proposer + one batched compare


def test_hybrid_only_legal_move_costs_nothing():
    b = chess.Board("k7/8/8/8/8/8/1q6/K7 w - - 0 1")  # Kxb2 is the only legal move
    llm = Fake("unused")
    d = ClaudeEnginePlayer(llm, use_context=False, tactical=True).choose_move(b)
    assert d.san == "Kxb2" and d.llm_calls == 0 and not llm.systems


def test_board_read_scoring():
    b = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 b - - 0 1")  # black to move; queen attacked? no: rook on d2 hits d5
    data = {"board": {"white": ["Ke1", "Rd2"], "black": ["Ke8", "Qd4"]},
            "threats": ["Rxd5"], "hanging": ["d5"]}
    r = boardread.score(b, data)
    assert r["pieces_total"] == 4 and r["pieces_correct"] == 3
    assert r["missing"] == ["Qd5"] and r["phantom"] == ["Qd4"]
    assert "Rxd5" in r["threats_real"] and r["threats_missed"] == []
    assert r["hanging_real"] == ["d5"] and r["hanging_missed"] == []


def test_board_read_attached_to_decisions():
    b = chess.Board()
    white = ["Ra1", "Nb1", "Bc1", "Qd1", "Ke1", "Bf1", "Ng1", "Rh1"] + [f"P{f}2" for f in "abcdefgh"]
    black = ["Ra8", "Nb8", "Bc8", "Qd8", "Ke8", "Bf8", "Ng8", "Rh8"] + [f"{f}7" for f in "abcdefgh"]
    extra = {"board": {"white": white, "black": black}, "threats": [], "hanging": []}
    d = ClaudeEnginePlayer(Fake(cands(("e4", 1.0), **extra)), use_context=False, depth=0,
                           board_read=True).choose_move(b)
    assert d.board_read["piece_accuracy"] == 1.0
    naive = NaiveClaudePlayer(Fake("", naive=json.dumps({"move": "e4", **extra})), board_read=True)
    assert naive.choose_move(b).board_read["pieces_correct"] == 32
