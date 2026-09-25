"""Learning loop: learned-KB retrieval/versioning, context isolation, mistake finding, gate."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import chess
import chess.pgn
import pytest

from claude_chess import learn
from claude_chess.context import build_context, learned, render_context
from claude_chess.types import LLMResponse, MoveDecision

SCHOLAR = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4"]  # Black to move; ...Nf6?? allows Qxf7#


def _lesson(kb: Path, lid: str, tags: list[str], title: str = "Guard f7") -> None:
    (kb / "lessons").mkdir(parents=True, exist_ok=True)
    (kb / "lessons" / f"{lid}.md").write_text(
        f"---\ntitle: {title}\ntags: [{', '.join(tags)}]\nstatus: active\n---\n## Summary\n- Check f7.\n")


@pytest.fixture(autouse=True)
def _kb_off():
    learned.set_active(None)
    yield
    learned.set_active(None)


def _board(uci: list[str]) -> chess.Board:
    b = chess.Board()
    for u in uci:
        b.push_uci(u)
    return b


def test_context_identical_when_kb_off_or_empty(tmp_path):
    b = _board(SCHOLAR)
    off = render_context(build_context(b, version=3))
    learn.ensure_kb(tmp_path / "kb")
    learned.set_active(tmp_path / "kb")
    assert render_context(build_context(b, version=3)) == off
    assert "Lessons from your past games" not in off


def test_lesson_shown_only_when_primary_tag_present(tmp_path):
    kb = tmp_path / "kb"
    learn.ensure_kb(kb)
    b = _board(SCHOLAR)
    tags = build_context(b, version=3).tags
    assert tags, "position should have tags"
    _lesson(kb, "L001-a", [tags[0]])
    _lesson(kb, "L002-b", ["rook-endgame"], title="Rooks behind passers")
    learned.set_active(kb)
    ctx = build_context(b, version=3)
    assert ctx.lessons and ctx.lessons[0].startswith("Guard f7")
    assert "## Lessons from your past games" in render_context(ctx)


def test_versions_replay_and_retire(tmp_path):
    kb = tmp_path / "kb"
    learn.ensure_kb(kb)
    for lid in ("L001-a", "L002-b"):
        _lesson(kb, lid, ["tactics"])
        learn._commit(kb, "add", lid, {})
    learn._commit(kb, "retire", "L001-a", {})
    assert learned.ids_at_version(kb, 1) == ["L001-a"]
    assert learned.ids_at_version(kb, 2) == ["L001-a", "L002-b"]
    assert learned.ids_at_version(kb, 3) == ["L002-b"]
    assert [les.id for les in learned.load(kb)] == ["L002-b"]


def test_validate_rules():
    pos = ["tactics", "king-safety"]
    ok = {"action": "new", "title": "T", "tags": ["tactics", "bogus", "king-safety"], "summary": ["x"]}
    assert learn.validate(ok, pos)["tags"] == ["tactics", "king-safety"]
    assert learn.validate({**ok, "tags": ["rook-endgame"]}, pos) is None  # primary not in position
    assert learn.validate({**ok, "action": "skip"}, pos) is None
    assert learn.validate({**ok, "summary": []}, pos) is None


# ── end to end with a scripted player and real Stockfish ────────────────────


def _write_run(rd: Path) -> None:
    rd.mkdir(parents=True)
    b = _board(SCHOLAR)
    fen = b.fen()
    moves = SCHOLAR + ["g8f6", "h5f7"]
    g = chess.pgn.Game()
    node = g
    for u in moves:
        node = node.add_variation(chess.Move.from_uci(u))
    g.headers["Round"] = "0"
    (rd / "games.pgn").write_text(str(g) + "\n\n")
    (rd / "decisions.jsonl").write_text(json.dumps(
        {"game": 0, "ply": 6, "fen": fen, "player": "hybrid(fake-opus)", "san": "Nf6",
         "candidates": [{"san": "Nf6", "reason": "develop"}]}) + "\n")
    (rd / "move_analysis.jsonl").write_text(json.dumps(
        {"game": "0", "ply": 6, "player": "hybrid(fake-opus)", "san": "Nf6", "cpl": 1000,
         "eval_before": -30}) + "\n")


class FakeLLM:
    model = "fake-opus"

    def complete(self, system, prompt, max_tokens=1024):
        tags = re.search(r"## POSITION TAGS.*?\n(.+)\n", prompt).group(1).split(", ")
        return LLMResponse(text=json.dumps({"action": "new", "title": "Guard f7 against Qh5+Bc4",
                                            "tags": [tags[0]], "summary": ["Before developing, check Qxf7 ideas."],
                                            "diagnosis": "missed mate", "why_general": "common trap"}))


class ScriptedPlayer:
    """Plays ...g6 in the Scholar position iff the active KB has a lesson, else ...Nf6??."""
    name = "fake"

    def __init__(self, helped: bool = True):
        self.helped = helped

    def choose_move(self, board):
        if board.fen() == _board(SCHOLAR).fen():
            good = self.helped and learned.active() is not None and learned.load()
            san = "g6" if good else "Nf6"
        else:
            san = board.san(sorted(board.legal_moves, key=lambda m: m.uci())[0])
        return MoveDecision(move=board.parse_san(san), san=san)


@pytest.mark.skipif(shutil.which("stockfish") is None and not Path("/opt/homebrew/bin/stockfish").exists(),
                    reason="needs stockfish")
@pytest.mark.parametrize("helped,expect", [(True, "accepted"), (False, "rejected")])
def test_learn_from_run_gates_lessons(tmp_path, helped, expect):
    rd = tmp_path / "runs" / "r1"
    _write_run(rd)
    kb = tmp_path / "kb"
    rep = learn.learn_from_run(rd, "fake-opus", lambda: ScriptedPlayer(helped), FakeLLM(), kb=kb,
                               cfg={"gate_repeats": 1, "gate_controls": 1}, log=lambda s: None)
    (res,) = rep["results"]
    assert res["outcome"].startswith(expect)
    if expect == "accepted":
        assert res["gate"]["target_base_cpl"] >= 500 and res["gate"]["target_cand_cpl"] < 100
        assert learned.read_manifest(kb)["version"] == 1 and len(learned.load(kb)) == 1
        text = next((kb / "lessons").glob("*.md")).read_text()
        assert "## Source game" in text and '"db_game_id": "r1:0"' in text and "Qxf7#" in text
        prop = json.loads((kb / "proposals.jsonl").read_text().splitlines()[0])
        assert prop["source_game"]["db_game_id"] == "r1:0" and prop["targets"][0]["src"] == "r1:0:6"
    else:
        assert learned.read_manifest(kb)["version"] == 0 and list((kb / "rejected").glob("*.md"))
    assert (rd / "learn_report.json").exists()


# ── slow drift ──────────────────────────────────────────────────────────────

RUY = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "f8e7",
       "f1e1", "b7b5", "a4b3", "d7d6", "c2c3", "e8g8", "h2h3", "c6a5"]


def _write_drift_run(rd: Path, cpls: dict[int, int], eval_before: dict[int, int] | None = None) -> None:
    rd.mkdir(parents=True)
    g = chess.pgn.Game()
    node, b = g, chess.Board()
    dec, ana = [], []
    for i, u in enumerate(RUY, start=1):
        mv = chess.Move.from_uci(u)
        san = b.san(mv)
        player = "hybrid(fake-opus)" if i % 2 == 1 else "maia3-2700"
        dec.append({"game": 0, "ply": i, "fen": b.fen(), "player": player, "san": san,
                    "candidates": [{"san": san, "reason": "plan"}], "own_eval": 30})
        ana.append({"game": "0", "ply": i, "player": player, "san": san, "cpl": cpls.get(i, 0),
                    "eval_before": (eval_before or {}).get(i, 20), "eval_after": 0, "best_move": "x"})
        b.push(mv)
        node = node.add_variation(mv)
    g.headers["Round"] = "0"
    (rd / "games.pgn").write_text(str(g) + "\n\n")
    (rd / "decisions.jsonl").write_text("".join(json.dumps(d) + "\n" for d in dec))
    (rd / "move_analysis.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ana))


def test_find_drifts_segment_before_blunder(tmp_path):
    rd = tmp_path / "r"
    # White (learner) leaks 30-50cp for five moves, then blunders at ply 11
    _write_drift_run(rd, {1: 30, 3: 40, 5: 50, 7: 40, 9: 45, 11: 300, 13: 10})
    (seg,) = learn.find_drifts(rd, "fake-opus", min_total=150, min_moves=4)
    assert [m["ply"] for m in seg["moves"]] == [1, 3, 5, 7, 9]
    assert seg["total_cpl"] == 205 and seg["ended_by"] == {"ply": 11, "san": "Re1", "cpl": 300}
    # opponent moves never count, and the post-blunder tail (1 move) is too short
    assert all(m["player"] == "hybrid(fake-opus)" for m in seg["moves"])


def test_find_drifts_thresholds_and_lost_positions(tmp_path):
    rd = tmp_path / "a"
    _write_drift_run(rd, {1: 20, 3: 20, 5: 20, 7: 20, 9: 20})  # 100 total: below threshold
    assert learn.find_drifts(rd, "fake-opus", min_total=150) == []
    rd2 = tmp_path / "b"
    # same leaks but the game was already lost from ply 5: segment is cut there
    _write_drift_run(rd2, {1: 60, 3: 60, 5: 60, 7: 60, 9: 60}, eval_before={5: -900, 7: -950, 9: -990})
    assert learn.find_drifts(rd2, "fake-opus", min_total=100, min_moves=2)[0]["total_cpl"] == 120


@pytest.mark.skipif(shutil.which("stockfish") is None and not Path("/opt/homebrew/bin/stockfish").exists(),
                    reason="needs stockfish")
def test_drift_prompt_has_sequence_and_tags(tmp_path):
    from claude_chess.match.baselines import open_stockfish
    rd = tmp_path / "r"
    _write_drift_run(rd, {1: 30, 3: 40, 5: 50, 7: 40, 9: 45, 11: 300})
    (seg,) = learn.find_drifts(rd, "fake-opus")
    eng = open_stockfish()
    try:
        prompt, tags, targets = learn.drift_prompt(seg, eng, 3, tmp_path / "kb", n_targets=3)
    finally:
        eng.quit()
    assert "1. e4 e5 2. Nf3" in prompt and "total lost 205 cp" in prompt
    assert "Right after this stretch you played Re1" in prompt
    assert [t["ply"] for t in targets] == [5, 9, 3] and tags


def test_find_drifts_collapse_review_ranks_first(tmp_path):
    rd = tmp_path / "r"
    # equal until ply 5, then big mistakes take the learner to -350 for good from ply 13
    ev = {1: 20, 3: -10, 5: -40, 7: -120, 9: -200, 11: -280, 13: -350, 15: -420, 17: -500}
    _write_drift_run(rd, {5: 30, 7: 110, 9: 90, 11: 120, 13: 20, 15: 30, 17: 25}, eval_before=ev)
    (seg,) = learn.find_drifts(rd, "fake-opus", min_total=150, min_moves=3)
    assert seg["kind"] == "collapse"
    assert [m["ply"] for m in seg["moves"]] == [5, 7, 9, 11]  # last equal (>= -60) up to the collapse
    assert seg["ended_by"]["ply"] == 13 and seg["total_cpl"] == 350


@pytest.mark.skipif(shutil.which("stockfish") is None and not Path("/opt/homebrew/bin/stockfish").exists(),
                    reason="needs stockfish")
def test_gate_second_run_is_served_from_cache(tmp_path):
    from claude_chess.match.baselines import open_stockfish
    calls = {"n": 0}

    class Counting(ScriptedPlayer):
        def choose_move(self, board):
            calls["n"] += 1
            return super().choose_move(board)

    kb = tmp_path / "kb"
    learn.ensure_kb(kb)
    cand = tmp_path / "cand"
    shutil.copytree(kb, cand)
    _lesson(cand, "L001-x", [build_context(_board(SCHOLAR), version=3).tags[0]])
    target = {"fen": _board(SCHOLAR).fen(), "history_uci": SCHOLAR, "src": "r:0:6", "game": 0}
    eng = open_stockfish()
    try:
        cache = learn.Cache(kb)
        r1 = learn.gate([dict(target)], [], lambda: Counting(), kb, cand, eng, repeats=2, cache=cache)
        first = calls["n"]
        r2 = learn.gate([dict(target)], [], lambda: Counting(), kb, cand, eng, repeats=2, cache=cache)
        cache.close()
    finally:
        eng.quit()
    assert first == 2 * 2  # 2 arms × 2 repeats
    assert calls["n"] == first  # second run: every decision served from the cache
    assert r1["target_base_cpl"] == r2["target_base_cpl"] and r1["accepted"] == r2["accepted"]
