import chess

from claude_chess.explainer import concepts as C
from claude_chess.explainer import vocab


def test_start_position_is_symmetric_and_quiet():
    d = C.static(chess.Board())
    for k in C.SIDE_KEYS:
        assert d[f"us.{k}"] == d[f"them.{k}"], k
    assert d["us.back_rank_weak"] == 0  # minors still on the back rank
    assert d["us.passed_pawns"] == 0 and d["us.hanging"] == 0
    assert d["g.phase"] == 1.0
    assert len(C.vector(d)) == len(C.KEYS)


def test_pawn_attacks_do_not_wrap_around_the_board():
    assert C._pawn_attacks(chess.BB_H2, chess.WHITE) == chess.BB_G3
    assert C._pawn_attacks(chess.BB_A2, chess.WHITE) == chess.BB_B3
    assert C._pawn_attacks(chess.BB_H7, chess.BLACK) == chess.BB_G6
    assert C._pawn_attacks(chess.BB_A7, chess.BLACK) == chess.BB_B6


def test_passed_pawn_and_majority():
    d = C.static(chess.Board("8/5pk1/8/1P6/8/8/5PPK/8 w - - 0 1"))
    assert d["us.passed_pawns"] == 1 and d["us.passer_rank"] == 4
    assert d["them.passed_pawns"] == 0
    assert d["us.majority_qs"] == 1


def test_pov_swaps_sides():
    b = chess.Board("8/5pk1/8/1P6/8/8/5PPK/8 w - - 0 1")
    assert C.static(b, chess.BLACK)["them.passed_pawns"] == 1


def test_fork_and_back_rank_mate_threat():
    d = C.static(chess.Board("r3k2r/ppp2ppp/8/3N4/8/8/PPP2PPP/R3K2R w KQkq - 0 1"))
    assert d["us.forks"] >= 1  # Nxc7+ hits king and rook
    d = C.static(chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"))
    assert d["us.mate_threat"] == 1 and d["them.back_rank_weak"] == 1


def test_iqp_detected():
    d = C.static(chess.Board("r1bq1rk1/pp2bppp/2n1pn2/8/3P4/2NB1N2/PP3PPP/R1BQ1RK1 w - - 0 10"))
    assert d["us.iqp"] == 1 and d["us.isolated_pawns"] == 1 and d["them.iqp"] == 0


def test_line_end_resolves_a_pending_capture():
    # White to move; Black's queen on d5 is attacked by the e4 pawn. A 0-ply line still
    # credits White with the capture available at the end.
    b = chess.Board("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    end = C.line_end_concepts(b, [], chess.WHITE)
    root = C.static(b)
    assert end["us.material"] - root["us.material"] == 9


def test_salience_ranks_the_material_win_first():
    b = chess.Board("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    root = C.static(b)
    best = C.delta(root, C.line_end_concepts(b, ["e4d5"], chess.WHITE))
    alt = C.delta(root, C.line_end_concepts(b, ["e1f1", "d5e4"], chess.WHITE))
    top = C.salience(best, alt, top=3)
    key, z, good = top[0]
    assert key == "g.material_balance"  # per-side material is excluded: trades move both sides
    assert good > 0


def test_checkmate_flag_from_movers_view():
    b = chess.Board("6k1/4Rppp/8/8/8/8/5PPP/6K1 w - - 0 1")
    end = C.line_end_concepts(b, ["e7e8"], chess.WHITE)
    assert end["g.checkmate"] == 1.0
    assert C.goodness_sign("g.checkmate") == 1 and C.goodness_sign("g.phase") == 0


def test_move_facts():
    b = chess.Board()
    f = C.move_facts(b, chess.Move.from_uci("g1f3"))
    assert f["development"] == 1 and f["capture"] == 0
    # Nxe5 Nxe5 is an even trade? No: 1.e4 e5 2.Nf3 Nc6 3.Nxe5 Nxe5 loses the knight for a pawn
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    f = C.move_facts(b, chess.Move.from_uci("f3e5"))
    assert f["capture"] == 1 and f["see"] < 0


def test_parries_threat():
    # Black threatens ...Qxh2 mate-ish capture? Simpler: White's queen on d4 is attacked by
    # the c5 pawn; moving it away parries the threat.
    b = chess.Board("4k3/8/8/2p5/3Q4/8/8/4K3 w - - 0 1")
    f = C.move_facts(b, chess.Move.from_uci("d4d1"))
    assert f["parries_threat"] >= 8


def test_goodness_sign_and_vocab():
    assert C.goodness_sign("us.passed_pawns") == 1
    assert C.goodness_sign("them.passed_pawns") == -1
    assert C.goodness_sign("us.isolated_pawns") == -1
    assert C.goodness_sign("g.phase") == 0
    known = set(C.SIDE_KEYS) | {s.key for s in C.GLOBAL}
    for h in vocab.VOCAB:
        for k in h.detectors:
            assert k in known, (h.id, k)
    assert len(set(vocab.IDS)) == len(vocab.IDS)
