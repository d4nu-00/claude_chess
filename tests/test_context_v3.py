"""Context v3: relations, last-move changes, per-move deltas, material check, suite stats."""

import json

import chess

from claude_chess.cli import parse_position
from claude_chess.context import build_context, render_context
from claude_chess.context.relations import last_move, move_delta, relations, temperature
from claude_chess.engine import prompts
from claude_chess.suite import compare, summarize

# 13...Nb4 attacks the white queen on d3 (Italian, Greco line).
POS = ("1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.c3 Nf6 5.d4 exd4 6.cxd4 Bb4+ 7.Bd2 Bxd2+ 8.Nbxd2 O-O "
       "9.O-O d6 10.Re1 Bg4 11.h3 Bxf3 12.Nxf3 Re8 13.Qd3 Nb4")


def test_last_move_reports_new_attack_on_queen():
    facts = last_move(parse_position(POS))
    assert facts[0] == "Black just played Nb4"
    assert any("Nb4 attacks" in f and "Qd3" in f for f in facts)
    assert any("now threatens: Nxd3" in f for f in facts)


def test_relations_list_attacked_queen_first():
    rel = relations(parse_position(POS))
    assert rel[0].startswith("White Qd3: attacked by Nb4")


def test_move_delta_rescue_and_ignore():
    b = parse_position(POS)
    assert any("rescues Qb3" in f for f in move_delta(b, b.parse_san("Qb3")))
    assert any("IGNORES the threat to Qd3" in f for f in move_delta(b, b.parse_san("a3")))


def test_material_check_lists_the_few_safe_moves():
    text = prompts.material_check(parse_position(POS))
    safe = [m.strip() for m in text.split("don't:")[1].split(",")]
    assert "Qb3" in safe and "a3" not in safe


def test_v3_context_is_adaptive_and_v2_unchanged():
    b = parse_position(POS)
    assert temperature(b) >= 4
    v3 = render_context(build_context(b, False, version=3), False)
    assert "SHARP" in v3 and v3.index("Opponent's last move") < v3.index("Piece relations")
    v2 = render_context(build_context(b, False), False)
    assert "Piece relations" not in v2 and "SHARP" not in v2


def test_suite_compare_paired(tmp_path):
    rows_a = [{"src": str(i), "san": "e4", "sf_best": "e4", "claude_candidates": ["e4"], "cost": 0.01,
               "seconds": 1, "cp_loss": 0} for i in range(20)]
    rows_b = [dict(r, san="a3", claude_candidates=["a3"], cp_loss=150) for r in rows_a]
    (tmp_path / "a.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_a))
    (tmp_path / "b.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_b))
    res = compare(tmp_path / "a.jsonl", tmp_path / "b.jsonl", n=2000)
    assert res["mean_cp_loss_diff"] == -150 and res["p_value"] < 0.01
    assert summarize(rows_a)["proposer_recall"] == 1.0
