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
    else:
        assert learned.read_manifest(kb)["version"] == 0 and list((kb / "rejected").glob("*.md"))
    assert (rd / "learn_report.json").exists()
