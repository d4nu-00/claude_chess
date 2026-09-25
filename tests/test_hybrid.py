"""Hybrid (tactical) search + board-vision probe. FakeLLM only — no Claude calls."""

import json

import chess

from claude_chess.engine import ClaudeEnginePlayer, NaiveClaudePlayer, boardread, prompts, tactical
from claude_chess.types import Candidate, LLMResponse


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


def test_threat_agent_reply_is_verified_by_search():
    # Rb7?? allows ...Ra1+ Rb1 Rxb1# (back rank); Rb8+ is fine. The agent names Ra1+,
    # Python plays it and searches -> Rb7 is scored as mated.
    b = chess.Board("r5k1/5ppp/8/2P5/8/8/5PPP/1R4K1 w - - 0 1")
    llm = Fake(cands(("Rb7", 0.6), ("Rb8+", 0.4)))
    llm.threat = json.dumps({"replies": [{"move": "Rb7", "reply": "Ra1+", "idea": "back rank"},
                                         {"move": "Rb8+", "reply": "Rxb8", "idea": "trade"}]})
    p = ClaudeEnginePlayer(llm, use_context=False, tactical=True, threat_agent=True)
    survivors = [(Candidate(san="Rb7"), b.parse_san("Rb7")), (Candidate(san="Rb8+"), b.parse_san("Rb8+"))]
    verdicts = {v.move: v for v in tactical.score_moves(b, [m for _, m in survivors], depth=0)}

    class T:
        def complete(self, system, prompt, max_tokens=1024):
            assert system == prompts.THREAT_SYSTEM and "Rb7" in prompt
            return llm.threat

    out = p._threats(T(), b, survivors, verdicts, depth=1)
    assert out[b.parse_san("Rb7")]["reply"] == "Ra1+"
    assert out[b.parse_san("Rb7")]["score"] <= -tactical.MATE_BAND
    assert out[b.parse_san("Rb8+")]["score"] > -tactical.MATE_BAND


def test_hybrid_plays_tablebase_move(monkeypatch):
    from claude_chess.context import tablebase as tbmod
    b = chess.Board("8/8/4k3/8/4K3/4P3/8/8 w - - 0 1")
    monkeypatch.setattr(tbmod, "probe", lambda board: tbmod.TBResult(0, 0, [("Kd4", 0, 0), ("Kf4", 0, 0),
                                                                            ("Kd3", -2, 5)], "fake"))
    llm = Fake(cands(("Kd3", 0.7), ("Kf4", 0.3)))
    d = ClaudeEnginePlayer(llm, use_context=False, tactical=True).choose_move(b)
    assert d.san == "Kf4" and "tablebase" in d.note


def test_alphabeta_cutoff_skips_claude_calls():
    """e4 (searched first) is worth +50 whatever Black replies; the first reply to d4 already
    scores -100 <= alpha, so d4's remaining replies are pruned (no Claude calls for them)."""
    b = chess.Board()
    seen = []

    class L:
        model = "fake"

        def complete(self, system, prompt, max_tokens=1024):
            if system == prompts.PROPOSER_SYSTEM:
                text = cands(("e4", 0.6), ("d4", 0.4))
            elif system == prompts.THREAT_SYSTEM:
                text = json.dumps({"replies": [{"move": "e4", "reply": "e5", "alt": "c5"},
                                               {"move": "d4", "reply": "d5", "alt": "Nf6"}]})
            elif system == prompts.POSITIONAL_SYSTEM:
                fen = prompt.split("FEN: ", 1)[1].split("\n", 1)[0]
                seen.append(fen)
                white_pawn_e4 = chess.Board(fen).piece_at(chess.E4) == chess.Piece(chess.PAWN, chess.WHITE)
                text = json.dumps({"positional_cp": 50 if white_pawn_e4 else -100})
            else:
                raise AssertionError(system)
            return LLMResponse(text=text, cost_usd=0.001)

    p = ClaudeEnginePlayer(L(), use_context=False, tactical=True, search="alphabeta")
    d = p.choose_move(b)
    assert d.san == "e4"
    ab = d.search_info["alphabeta"]
    assert ab["pruned"] >= 1 and ab["evaluated"] < ab["leaves"]
    assert sum(1 for f in seen if chess.Board(f).piece_at(chess.D4)) == 1  # one d4 leaf, then cutoff
    assert d.search_info["candidates"]["d4"]["ab_value"] <= -100
    roles = [t["role"] for t in d.traces]
    assert roles[0] == "proposer" and "threat" in roles and "positional" in roles
