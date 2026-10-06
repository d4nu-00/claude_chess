import json
import shutil
import stat

import chess
import pytest

from claude_chess.engine.raw import RawPlayer, build_prompt, parse_reply, render_board_png
from claude_chess.llm import ClaudeCLIStream
from claude_chess.types import LLMResponse


class FakeLLM:
    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, prompt, max_tokens=1024, images=None):
        self.calls.append((prompt, images))
        return LLMResponse(text=self.replies.pop(0), cost_usd=0.1, thinking_tokens=7)


def test_prompt_text_vs_image_differ_only_in_board():
    b = chess.Board()
    text, img = build_prompt(b, "unicode"), build_prompt(b, "image")
    assert "♖" in text and "♖" not in img and "attached image" in img
    for p in (text, img):
        assert "FEN: " + b.fen() in p and "e2e4" in p and "make_move <UCI>" in p
        assert p.startswith("You are playing chess as white.")
    assert text.split("Board:")[1].split("FEN:")[1] == img.split("Board:")[1].split("FEN:")[1]


def test_prompt_black_orientation():
    b = chess.Board()
    b.push_san("e4")
    assert build_prompt(b, "unicode").startswith("You are playing chess as black.")


def test_parse_reply_takes_last_make_move_and_keeps_reasoning():
    b = chess.Board()
    mv, why, reasoning = parse_reply(b, "I considered make_move e7e5 but no.\nBecause centre.\nmake_move e2e4")
    assert mv == chess.Move.from_uci("e2e4") and why == ""
    assert "Because centre." in reasoning and "make_move e2e4" not in reasoning


@pytest.mark.parametrize("text,frag", [("no move here", "no `make_move"), ("make_move e2e5", "illegal"),
                                       ("make_move e7e5", "illegal")])
def test_parse_reply_rejects(text, frag):
    mv, why, _ = parse_reply(chess.Board(), text)
    assert mv is None and frag in why


def test_player_retries_on_illegal_then_plays_and_records_reasoning():
    llm = FakeLLM(["nope\nmake_move e2e5", "Centre pawn.\nmake_move e2e4"])
    d = RawPlayer(llm, illegal_policy="forfeit").choose_move(chess.Board())
    assert d.san == "e4" and d.llm_calls == 2 and len(d.illegal_attempts) == 1
    assert d.search_info["reasoning"] == "Centre pawn." and d.search_info["thinking_tokens"] == 7
    assert "rejected" in llm.calls[1][0] and len(d.traces) == 2 and d.traces[0]["role"] == "raw"


def test_player_forfeit_after_retries():
    d = RawPlayer(FakeLLM(["x"] * 3), illegal_policy="forfeit", max_retries=2).choose_move(chess.Board())
    assert d.move is None and d.forfeit_reason and d.llm_calls == 3


@pytest.mark.skipif(shutil.which("magick") is None, reason="ImageMagick not installed")
def test_render_png_and_image_is_passed_to_llm():
    assert render_board_png(chess.Board(), size=200)[:8] == b"\x89PNG\r\n\x1a\n"
    llm = FakeLLM(["ok\nmake_move e2e4"])
    RawPlayer(llm, style="image").choose_move(chess.Board())
    assert llm.calls[0][1] and llm.calls[0][1][0][:4] == b"\x89PNG"


def test_stream_backend_parses_events_and_sends_image(tmp_path):
    events = [
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "result", "result": "why\nmake_move e2e4", "is_error": False, "total_cost_usd": 0.5,
         "usage": {"input_tokens": 4, "output_tokens": 9, "output_tokens_details": {"thinking_tokens": 6}}},
    ]
    script = tmp_path / "fake_claude"
    script.write_text(f"#!/bin/sh\ncat > {tmp_path}/stdin.json\ncat <<'EOF'\n"
                      + "\n".join(json.dumps(e) for e in events) + "\nEOF\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    r = ClaudeCLIStream(executable=str(script), retries=0).complete("sys", "prompt", images=[b"\x89PNGdata"])
    assert r.text.endswith("make_move e2e4") and r.thinking == "hmm" and r.thinking_tokens == 6
    sent = json.loads((tmp_path / "stdin.json").read_text())["message"]["content"]
    assert sent[0]["type"] == "image" and sent[0]["source"]["media_type"] == "image/png"
    assert sent[1] == {"type": "text", "text": "prompt"}


def test_ascii_board_orientation_and_matches_fen():
    w = build_prompt(chess.Board(), "ascii")
    assert "8 r n b q k b n r" in w and "1 R N B Q K B N R" in w and "  a b c d e f g h" in w
    assert w.index("8 r") < w.index("1 R")
    b = chess.Board()
    b.push_san("e4")
    bl = build_prompt(b, "ascii")
    assert bl.index("1 R") < bl.index("8 r") and "  h g f e d c b a" in bl and "1 R N B K Q B N R" in bl
