import time

import chess

from claude_chess.context import build_context, render_context
from claude_chess.context.tactics import see


def play(*sans: str) -> chess.Board:
    b = chess.Board()
    for s in sans:
        b.push_san(s)
    return b


def test_berlin_identified():
    ctx = build_context(play("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6"))
    assert ctx.opening is not None and ctx.opening.startswith("C65 Ruy Lopez: Berlin Defense")
    assert "out of book" not in ctx.opening


def test_out_of_book_keeps_deepest_match():
    b = play("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "O-O", "Nxe4", "d4", "Nd6",
             "Bxc6", "dxc6", "dxe5", "Nf5", "Qxd8+", "Kxd8", "a4", "a5")
    ctx = build_context(b)
    assert "Berlin" in ctx.opening and "out of book since move 9" in ctx.opening


def test_transposition_matched_by_position():
    # Reach the Berlin with 2...Nf6 3.Bb5 Nc6 — different order, same position.
    ctx = build_context(play("e4", "e5", "Nf3", "Nf6", "Bb5", "Nc6"))
    assert "Berlin" in (ctx.opening or "")


def test_iqp_detected():
    b = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/8/3P4/2NB1N2/PP3PPP/R1BQ1RK1 w - - 0 10")
    ctx = build_context(b)
    assert any("IQP" in s for s in ctx.pawn_structure)
    assert any("Isolated Queen's Pawn" in c for c in ctx.concepts)


def test_carlsbad_detected():
    b = chess.Board("r1bq1rk1/pp1nbppp/2p2n2/3p2B1/3P4/2NBP3/PPQ2PPP/R3K1NR w KQ - 0 9")
    ctx = build_context(b)
    assert any("Carlsbad" in s for s in ctx.pawn_structure)


def test_passed_pawn_detected():
    b = chess.Board("8/5k2/8/1P6/8/8/5K2/8 w - - 0 1")
    ctx = build_context(b)
    assert any("White passed pawn(s): b5" in s for s in ctx.pawn_structure)
    assert ctx.phase == "endgame"


def test_hanging_piece_flagged():
    # Black knight on e5 undefended, attacked by White's Nf3.
    b = chess.Board("rnbqkb1r/pppp1ppp/8/4n3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 4")
    ctx = build_context(b)
    text = "\n".join(ctx.tactics)
    assert "Black pieces en prise: Ne5" in text
    assert "Nxe5 (SEE +3)" in text


def test_threat_against_side_to_move():
    # White to move; Black's queen on h4 attacks the undefended e4 pawn.
    b = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/4P2q/8/PPPP1PPP/RNBQKBNR w KQkq - 1 3")
    ctx = build_context(b)
    assert any(t.startswith("Black threatens") and "Qxe4+" in t for t in ctx.tactics)


def test_mate_in_one_flagged():
    b = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    ctx = build_context(b)
    assert any("MATE IN 1: Ra8#" in t for t in ctx.tactics)
    b = play("e4", "e5", "Qh5", "Nc6", "Bc4", "a6")  # Scholar's mate: White mates with Qxf7#
    assert any("MATE IN 1: Qxf7#" in t for t in build_context(b).tactics)
    # Same idea with Black to move: the opponent's mate threat must be flagged.
    b = play("e4", "e5", "Qh5", "Nc6", "Bc4")
    assert any(t.startswith("White threatens: MATE IN 1 with Qxf7#") for t in build_context(b).tactics)


def test_see_values():
    b = chess.Board("4k3/8/3p4/4p3/3P4/8/8/4K3 w - - 0 1")
    assert see(b, chess.Move.from_uci("d4e5")) == 0  # pawn takes pawn, pawn recaptures


def test_timing():
    boards = [
        chess.Board(),
        play("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "O-O", "Nxe4"),
        chess.Board("r1bq1rk1/pp2bppp/2n1pn2/8/3P4/2NB1N2/PP3PPP/R1BQ1RK1 w - - 0 10"),
        chess.Board("r2q1rk1/1b2bppp/p2ppn2/1p6/3NP3/1BN1B3/PPPQ1PPP/2KR3R w - - 0 12"),
        chess.Board("8/5k2/8/1P6/8/8/5K2/8 w - - 0 1"),
        chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 5"),
    ]
    build_context(boards[0])  # warm caches (opening index, concept pages)
    t0 = time.perf_counter()
    n = 0
    for _ in range(5):
        for b in boards:
            render_context(build_context(b))
            n += 1
    avg = (time.perf_counter() - t0) / n
    assert avg < 0.05, f"avg {avg * 1000:.1f}ms"


def test_render_sane():
    ctx = build_context(play("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "O-O", "Nxe4"))
    out = render_context(ctx)
    lines = out.splitlines()
    assert 15 <= len(lines) <= 80
    assert ctx.fen in out and "Side to move: **white**" in out
    order = ["## Position", "## Material", "## Tactics", "## Pawn structure", "## King safety",
             "## Piece activity", "## Guidance", "## Legal moves"]
    idx = [out.index(h) for h in order]
    assert idx == sorted(idx)
    assert "- King: Kh1" in out
    no_moves = render_context(ctx, include_legal_moves=False)
    assert "## Legal moves" not in no_moves
    assert build_context(chess.Board(), include_legal_moves=False).legal_moves_san == []


def test_random_games_no_crash():
    import random

    rng = random.Random(7)
    for _ in range(8):
        b = chess.Board()
        while not b.is_game_over() and b.ply() < 120:
            b.push(rng.choice(list(b.legal_moves)))
            if b.ply() % 10 == 0:
                out = render_context(build_context(b))
                assert len(out.splitlines()) <= 80
        render_context(build_context(b))
