import chess

from claude_chess.explainer import joint as J

FEN = "rnbqkb1r/pp2pppp/3p4/2p5/4n3/2P2NP1/PP1P1P1P/RNBQKB1R w KQkq - 0 1"


def _cands(board, sans):
    return [J.Cand(board.parse_san(s), s, 0.1) for s in sans]


def test_target_orders():
    label = {"idea": "Fork king and knight", "plan": "Win the knight", "concepts": ["fork", "win_material"]}
    a = J.target("reason_first", "Qa4+", label).splitlines()
    b = J.target("move_first", "Qa4+", label).splitlines()
    assert a[0].startswith("Idea:") and a[1] == "Move: Qa4+"
    assert b[0] == "Move: Qa4+" and b[1].startswith("Idea:")
    assert J.target("reason_first", "Qa4+", None) == "Move: Qa4+"


def test_parse_picks_candidate_and_falls_back():
    b = chess.Board(FEN)
    cands = _cands(b, ["Qa4+", "d4", "Bg2"])
    out = J.parse("Idea: Fork the king and the knight\nMove: Qa4\nPlan: take e4\nConcepts: fork, win_material", b, cands)
    assert out["san"] == "Qa4+" and out["concepts"] == ["fork", "win_material"] and not out.get("fallback")
    bad = J.parse("Idea: something\nMove: Zz9", b, cands)
    assert bad["fallback"] and bad["san"] == "Qa4+"  # the instinct
    off = J.parse("Move: h4", b, cands)
    assert off["san"] == "h4" and off.get("off_list")


def test_with_best_injects_missing_move():
    import random
    b = chess.Board(FEN)
    cands = _cands(b, ["Qa4+", "d4", "Bg2"])
    out = J._with_best(cands, b, "h2h4", random.Random(0))
    assert len(out) == 3 and any(c.move.uci() == "h2h4" for c in out)
    assert J._with_best(cands, b, "d2d4", random.Random(0)) == cands
