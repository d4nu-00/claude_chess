import json
import os
import stat

import pytest

from claude_chess.llm import LIMIT_BACKOFF_S, AnthropicLLM, ClaudeCLI, LLMError, LLMUnavailable, extract_json, make_llm


@pytest.mark.parametrize("text", [
    '{"move": "e4"}',
    '```json\n{"move": "e4"}\n```',
    'Sure! Here you go:\n```\n{"move": "e4"}\n```\nGood luck.',
    'I think {"move": "e4"} is best. {"other": 1}',
    'prose with {braces} first, then {"move": "e4", "nested": {"a": [1, 2]}} trailing',
])
def test_extract_json(text):
    assert extract_json(text)["move"] == "e4"


def test_extract_json_fails():
    with pytest.raises(ValueError):
        extract_json("no json here")


def _fake_claude(tmp_path, body: str):
    script = tmp_path / "fake_claude"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_cli_parses_json_and_reads_stdin(tmp_path):
    payload = {"result": "ok", "total_cost_usd": 0.002, "is_error": False,
               "usage": {"input_tokens": 10, "output_tokens": 3}}
    # echo stdin length into a side file to prove the prompt arrives via stdin
    exe = _fake_claude(tmp_path, f"cat > {tmp_path}/stdin.txt\necho '{json.dumps(payload)}'\n")
    llm = ClaudeCLI(model="haiku", executable=exe, retries=0)
    r = llm.complete("sys", "hello prompt")
    assert r.text == "ok" and r.cost_usd == 0.002 and r.input_tokens == 10
    assert (tmp_path / "stdin.txt").read_text() == "hello prompt"
    assert llm.counters.snapshot()["calls"] == 1


def test_cli_retries_then_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    exe = _fake_claude(tmp_path, f"echo x >> {tmp_path}/count\necho '{{\"is_error\": true, \"result\": \"boom\"}}'\n")
    llm = ClaudeCLI(executable=exe, retries=2)
    with pytest.raises(LLMUnavailable):  # backend failure, never an "illegal move"
        llm.complete("s", "p")
    assert len((tmp_path / "count").read_text().split()) == 3


def test_cli_backs_off_longer_on_limit_errors(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr("time.sleep", waits.append)
    exe = _fake_claude(tmp_path, f"echo x >> {tmp_path}/count\n"
                                 "echo '{\"is_error\": true, \"result\": \"You have hit your session limit\"}'\n")
    with pytest.raises(LLMUnavailable):
        ClaudeCLI(executable=exe, retries=2).complete("s", "p")
    assert len((tmp_path / "count").read_text().split()) == 3 + len(LIMIT_BACKOFF_S)
    assert max(waits) == max(LIMIT_BACKOFF_S)


def test_make_llm_backend(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(make_llm("sonnet"), ClaudeCLI)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = make_llm("opus")
    assert isinstance(llm, AnthropicLLM) and llm.model == "claude-opus-5-5"
    with pytest.raises(ValueError):
        make_llm("sonnet", backend="nope")
