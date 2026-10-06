from claude_chess.explainer import lm


def test_format_parse_round_trip():
    label = {"assessment": "White is winning", "idea": "Mate on the back rank",
             "why_best": "Re8# — the king has no luft", "why_not_alt": "Kf1 lets Black make luft",
             "concepts": ["back_rank", "mating_attack"], "novel_concept": "", "plan": "Mate",
             "difficulty": "obvious"}
    text = lm.format_target(label, "Re8#", "Kf1")
    assert text.splitlines()[0] == "Idea: Mate on the back rank"  # condensation first
    assert "New concept" not in text
    back = lm.parse_output("<think>\n\n</think>\n\n" + text, "Re8#", "Kf1")
    for k in ("idea", "assessment", "why_best", "why_not_alt", "plan", "difficulty"):
        assert back[k] == label[k]
    assert back["concepts"] == label["concepts"]


def test_parse_tolerates_wrong_move_in_headers():
    back = lm.parse_output("Idea: x\nWhy Nf3: because\nWhy not e4: weak", "Re8#", "Kf1")
    assert back["why_best"] == "because" and back["why_not_alt"] == "weak"
