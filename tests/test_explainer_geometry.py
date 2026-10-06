import chess

from claude_chess.explainer import geometry as G

FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"  # Italian, Black to move


def test_true_and_false_relations():
    ok = G.check("The bishop on c4 attacks f7.", FEN, [])
    assert ok["claims"] == 1 and ok["ok"]
    bad = G.check("The f3 knight guards d4 and the c4 bishop attacks c5.", FEN, [])
    assert bad["claims"] == 2 and len(bad["bad_claims"]) == 1  # Nf3 covers d4; a bishop never hits c5 from c4


def test_phantom_piece_reference():
    r = G.check("Trade off the c1 bishop and the d4 knight.", FEN, [])
    assert "d4 knight" in r["bad_refs"] and not r["ok"]
    assert "c1 bishop" not in r["bad_refs"]  # it really is on c1


def test_reference_after_the_move_counts():
    # after 3...Nf6 the knight is on f6
    r = G.check("The knight on f6 hits e4.", FEN, [["g8f6"]])
    assert r["ok"], r


def test_moves_are_not_piece_references():
    r = G.check("After 4.Nd5 or plays Nd5, Black is fine.", FEN, [])
    assert r["refs"] == 0


def test_xray_through_one_piece_counts():
    # Bc4 x-rays f7 to g8 through the f7 pawn
    r = G.check("The bishop on c4 eyes g8.", FEN, [])
    assert r["ok"]
