"""Middlegame character, imbalances, endgame classification, K+P rules, tablebase parsing."""

import chess

from claude_chess.cli import parse_position
from claude_chess.context import build_context, render_context
from claude_chess.context import tablebase
from claude_chess.context.character import center_type, chain_direction, pawn_breaks
from claude_chess.context.endgame import classify, key_squares, pawn_ending_facts


def test_french_advance_is_closed_with_chains():
    b = parse_position("1.e4 e6 2.d4 d5 3.e5 c5 4.c3 Nc6 5.Nf3 Qb6 6.a3 c4")
    assert center_type(b)[0] == "closed"
    assert chain_direction(b, chess.WHITE) == "kingside"
    assert chain_direction(b, chess.BLACK) == "queenside"
    assert any(x.startswith("f6") for x in pawn_breaks(b, chess.BLACK))
    ctx = build_context(b)
    assert "Middlegame character" in render_context(ctx)


def test_open_and_dynamic_centres():
    assert center_type(chess.Board("4k3/pp3ppp/8/8/8/8/PP3PPP/4K3 w - - 0 1"))[0] == "open"
    assert center_type(parse_position("1.e4 e5 2.d4"))[0] == "dynamic"


def test_endgame_classification():
    assert classify(chess.Board("8/8/4k3/8/2K5/4P3/8/8 w - - 0 1")) == "pawn"
    assert classify(chess.Board("8/8/8/2b5/4k3/8/3PB3/4K3 w - - 0 1")) == "opposite-bishops"
    assert classify(chess.Board("4k3/8/8/8/8/8/r7/R3K3 w - - 0 1")) == "rook"


def test_rule_of_the_square_and_key_squares():
    # a-pawn on a5, black king on d5: inside the square only if black is to move.
    white_to_move = chess.Board("8/8/8/P2k4/8/8/8/K7 w - - 0 1")
    black_to_move = chess.Board("8/8/8/P2k4/8/8/8/K7 b - - 0 1")
    assert any("OUTSIDE the square" in f for f in pawn_ending_facts(white_to_move))
    assert any("inside its square" in f for f in pawn_ending_facts(black_to_move))
    assert {chess.square_name(s) for s in key_squares(chess.WHITE, chess.E4)} == {"d6", "e6", "f6"}
    assert {chess.square_name(s) for s in key_squares(chess.WHITE, chess.E5)} == {"d6", "e6", "f6", "d7", "e7", "f7"}
    assert {chess.square_name(s) for s in key_squares(chess.WHITE, chess.A4)} == {"b7", "b8"}


def test_opposition():
    facts = pawn_ending_facts(chess.Board("8/8/4k3/8/4K3/4P3/8/8 w - - 0 1"))
    assert any("direct opposition — Black has the opposition" in f for f in facts)
    facts = pawn_ending_facts(chess.Board("8/8/4k3/8/2K5/4P3/8/8 w - - 0 1"))
    assert any("diagonal opposition" in f for f in facts)


def test_parse_lichess_tablebase():
    data = {"category": "win", "dtz": 1, "moves": [
        {"san": "Kd6", "category": "loss", "dtz": -19},
        {"san": "Kf6", "category": "loss", "dtz": -7},
        {"san": "Kd4", "category": "draw", "dtz": 0},
    ]}
    tb = tablebase.parse_lichess(data)
    assert tb.wdl == 2 and tb.verdict == "WIN"
    assert tb.best_moves() == ["Kf6", "Kd6"]  # fastest win first
