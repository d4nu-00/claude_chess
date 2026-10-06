import json

import chess

from claude_chess.explainer import data as D
from claude_chess.explainer import facts as F
from claude_chess.explainer import teacher as T


def _eval_line(fen, pvs):
    return json.dumps({"fen": fen, "evals": [{"pvs": pvs, "depth": 30}]})


def test_win_prob_is_symmetric_and_saturates():
    assert abs(D.win_prob(0) - 0.5) < 1e-9
    assert abs(D.win_prob(300) + D.win_prob(-300) - 1) < 1e-9
    assert D.win_prob(mate=3) == 1.0 and D.win_prob(mate=-2) == 0.0


def test_king_takes_rook_castling_is_normalized_and_encodable():
    fen = "r1bqk2r/ppp2ppp/2n1pn2/3p4/QbPP4/2N2N2/PP1BPPPP/R3KB1R b KQkq -"
    rec = D.featurize_eval(_eval_line(fen, [{"cp": 10, "line": "e8h8 e2e3"}, {"cp": 40, "line": "c8d7"}]))
    assert rec is not None and rec["best_line"].startswith("e8g8")
    assert rec["pol_idx"][0] in rec["legal"]
    # Black to move: value is the mover's win prob, so a White-positive cp is < 0.5
    assert rec["value"] < 0.5 and rec["value"] > rec["value_alt"]


def test_encode_decode_round_trip_for_both_colours():
    for fen in (chess.STARTING_FEN, "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"):
        b = chess.Board(fen)
        for mv in b.legal_moves:
            assert D.decode_move(b, D.encode_move(b, mv)) == mv
        toks, castle, ep = D.encode_board(b)
        assert toks[chess.E1] == chess.KING  # our king on our first rank in POV coordinates
        assert castle == [1, 1, 1, 1]


def test_structure_split_is_deterministic():
    b = chess.Board()
    assert D.structure_split(b) == D.structure_split(chess.Board())


def test_puzzle_featurized_after_setup_move():
    row = ["00008", "r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24", "f2g3 e6e7 b2b1 b3c1 b1c1 h6c1",
           "1811", "76", "95", "10282", "crushing hangingPiece long middlegame", "url", ""]
    rec = D.featurize_puzzle(row)
    assert rec["best_line"].split()[0] == "e6e7" and rec["src"] == 1
    assert "hangingPiece" in rec["themes"]


def _facts():
    # White wins the black queen with a pawn; the alternative lets it take a pawn instead.
    return F.compute("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1", ["e4d5", "e8d7"], ["e1f1", "d5e4"], 0.99, 0.02)


def test_verifier_accepts_grounded_label():
    label = {"assessment": "White is winning", "idea": "Take the queen with the pawn",
             "why_best": "exd5 wins the queen outright", "why_not_alt": "Kf1 lets Qxe4 take a pawn",
             "concepts": ["win_material"], "novel_concept": "", "plan": "Promote", "difficulty": "obvious"}
    v = T.verify(label, _facts())
    assert v["ok"], v


def test_verifier_flags_phantom_moves_and_false_material_claims():
    label = {"assessment": "", "idea": "Nf6 wins a pawn", "why_best": "Bxh7+ forks", "why_not_alt": "",
             "concepts": ["fork", "nonsense"], "novel_concept": "", "plan": "", "difficulty": "easy"}
    pf = F.compute("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1", ["e1f1", "d5e4"], ["e1e2", "d5e4"], 0.02, 0.01)
    v = T.verify(label, pf)
    assert not v["ok"]
    joined = " ".join(v["flags"])
    assert "bad_ref" in joined and "Bxh7+" in joined and "bad_concepts" in joined
    assert "material_claim" in joined and "bad_difficulty" in joined


def test_verifier_allows_recoveries_and_opponent_threats():
    pf = F.compute("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1", ["e1f1", "d5e4"], ["e1e2", "d5e4"], 0.02, 0.01)
    label = {"assessment": "", "idea": "Lose a pawn but win it back later", "why_best": "White wins a pawn back",
             "why_not_alt": "", "concepts": ["defence"], "novel_concept": "", "plan": "",
             "difficulty": "natural"}
    v = T.verify(label, pf)
    assert "material_claim" not in v["flags"]
    # Qxe4 is Black's threat at the root (White to move): a legitimate reference
    label["why_best"] = "Kf1 steps away, but Qxe4 still follows"
    assert T.verify(label, pf)["ok"]
