"""Named tactical motifs (context v4): each detector on a position where the answer is clear."""

import time

import chess

from claude_chess.context import motifs as mt


def B(fen):
    return chess.Board(fen)


def test_absolute_pin_nimzo():
    b = chess.Board()
    for m in ["d4", "Nf6", "c4", "e6", "Nc3", "Bb4"]:
        b.push_san(m)
    lines = mt.pins_and_skewers(b, chess.BLACK)
    assert any("White Nc3 is pinned to the king by Bb4" in x for x in lines)


def test_relative_pin_to_queen():
    b = chess.Board()
    for m in ["e4", "e5", "Nf3", "d6", "Nc3", "Bg4"]:
        b.push_san(m)
    assert any("Nf3 is pinned to Qd1 by Bg4" in x for x in mt.pins_and_skewers(b, chess.BLACK))


def test_knight_fork_king_and_rook():
    lines = mt.forks(B("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"))
    assert any(x.startswith("Nc7+ forks") and "ke8" in x.lower() and "ra8" in x.lower() for x in lines)


def test_skewer_king_and_queen():
    b = B("4k2q/8/8/8/8/8/8/R3K3 w - - 0 1")
    b.push_san("Ra8+")
    assert any("skewers Black Ke8 with Qh8 behind" in x for x in mt.pins_and_skewers(b, chess.WHITE))


def test_discovered_check_available():
    lines = mt.discovered(B("4k3/8/8/8/4N3/8/8/4R1K1 w - - 0 1"))
    assert lines == ["moving Ne4 unmasks Re1: discovered check"]


def test_back_rank_weakness():
    assert mt.back_rank(B("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"), chess.BLACK)
    assert not mt.back_rank(B("6k1/5pp1/7p/8/8/8/8/R5K1 w - - 0 1"), chess.BLACK)  # luft on h7


def test_overloaded_defender():
    # Rc2 hits Nc7, Re2 hits Ne7; Qd6 is the only defender of both (king far away on h8)
    b = B("7k/2n1n3/3q4/8/8/8/2R1R3/4K3 w - - 0 1")
    assert any("Black Qd6 is overloaded: sole defender of Nc7, Ne7" in x for x in mt.overloaded(b, chess.BLACK))
    # with the king on e8 also guarding e7, the queen is no longer the sole defender of two
    assert not mt.overloaded(B("4k3/2n1n3/3q4/8/8/8/2R1R3/4K3 w - - 0 1"), chess.BLACK)


def test_trapped_bishop_on_a2():
    # Ba2 is attacked by Ra1; Bb1 is met by Rxb1 and Bxb3 by cxb3
    b = B("4k3/8/8/8/8/1P6/b1P5/R3K3 b - - 0 1")
    assert b.is_valid()
    assert any("Black Ba2 is attacked and has no safe square (trapped)" == x for x in mt.trapped(b, chess.BLACK))


def test_motifs_both_sides_and_fast():
    b = B("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    lines = mt.motifs(b)
    assert any(x.startswith("White to move: Nc7+ forks") for x in lines)
    boards = [chess.Board()]
    for m in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5", "Bb3", "d6"]:
        boards.append(boards[-1].copy())
        boards[-1].push_san(m)
    t = time.perf_counter()
    for bb in boards:
        mt.motifs(bb)
    assert (time.perf_counter() - t) / len(boards) < 0.05


def test_no_noise_pins_or_capturable_forks():
    b = chess.Board()
    for m in ["e4", "e5", "Nf3", "d6", "Nc3", "Bg4", "Bc4", "Nc6", "h3", "Bh5"]:
        b.push_san(m)
    lines = mt.motifs(b)
    assert not any("f7 is pinned to Ng8" in x for x in lines)  # defended minor behind a pawn: not a pin worth naming
    assert not any("Bxf3 forks" in x for x in lines)  # Qxf3 just recaptures the forking piece
    assert any("Nf3 is pinned to Qd1 by Bh5" in x for x in lines)
