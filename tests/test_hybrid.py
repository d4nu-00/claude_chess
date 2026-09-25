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


# ── sacrifices: material is not everything ──────────────────────────────────


def _pool(board, *specs):
    out = []
    for san, sac in specs:
        out.append((Candidate(san=san, sacrifice=sac, compensation="attack" if sac else ""), board.parse_san(san)))
    return out


def test_veto_spares_declared_sacrifice_but_not_into_mate():
    b = chess.Board()
    p = ClaudeEnginePlayer(Fake(cands()), use_context=False, tactical=True, tac_margin=100)
    pool = _pool(b, ("e4", False), ("Nf3", True), ("d4", False))
    m = {c.san: mv for c, mv in pool}
    tscore = {m["e4"]: 0, m["Nf3"]: -320, m["d4"]: -320}
    notes = []
    keep = [c.san for c, _ in p._veto(pool, tscore, notes)]
    assert keep == ["e4", "Nf3"] and any("sacrifice kept Nf3" in n for n in notes)
    tscore[m["Nf3"]] = -tactical.MATE_CP + 3  # a "sacrifice" that walks into mate is still vetoed
    assert [c.san for c, _ in p._veto(pool, tscore, [])] == ["e4"]


def test_compare_awards_compensation_capped_at_material_given():
    b = chess.Board()
    seen = {}

    class CmpLLM:
        model = "fake"

        def complete(self, system, prompt, max_tokens=1024):
            seen["prompt"] = prompt
            return LLMResponse(text=json.dumps({"scores": [
                {"move": "e4", "score": 20}, {"move": "Nf3", "score": 0, "compensation_cp": 500}]}))

    p = ClaudeEnginePlayer(CmpLLM(), use_context=False, tactical=True)
    from claude_chess.engine.players import _Tally
    pool = _pool(b, ("e4", False), ("Nf3", True))
    m = {c.san: mv for c, mv in pool}
    verdicts = {m["e4"]: tactical.MoveVerdict(m["e4"], 0), m["Nf3"]: tactical.MoveVerdict(m["Nf3"], -300)}
    pos = p._compare(_Tally(p.llm), b, pool, verdicts)
    assert "SACRIFICE (gives up 300cp; claimed compensation: attack)" in seen["prompt"]
    assert pos[m["e4"]] == 20 and pos[m["Nf3"]] == 300  # 0 positional + compensation capped at 300
    # final hybrid score = material + positional: -300 + 300 = 0 < 20 → e4 still preferred here


def test_proposer_parses_sacrifice_flag():
    b = chess.Board()
    llm = Fake(json.dumps({"candidates": [{"move": "e4", "prior": 0.5},
                                          {"move": "Nf3", "prior": 0.5, "sacrifice": True, "compensation": "init"}]}))
    p = ClaudeEnginePlayer(llm, use_context=False, tactical=True)
    from claude_chess.engine.players import _Tally
    legal, _, _ = p._propose_once(_Tally(llm), b, 4, "")
    by = {c.san: c for c, _ in legal}
    assert by["Nf3"].sacrifice and by["Nf3"].compensation == "init" and not by["e4"].sacrifice


def test_book_moves_cost_no_calls_and_stop_out_of_book():
    llm = Fake(cands(("a3", 1.0)), naive=json.dumps({"move": "a3"}))
    for p in (ClaudeEnginePlayer(llm, use_context=False, tactical=True, seed=1), NaiveClaudePlayer(llm, seed=1)):
        p.book = True
        d = p.choose_move(chess.Board())
        assert d.note == "book" and d.llm_calls == 0 and d.san in ("e4", "d4")
    off = chess.Board("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")  # K+P ending: never in book → Claude decides
    p = ClaudeEnginePlayer(Fake(cands(("e4", 1.0))), use_context=False, tactical=True)
    p.book = True
    assert p.choose_move(off).note != "book"
    assert not ClaudeEnginePlayer(llm, use_context=False).book  # off by default
