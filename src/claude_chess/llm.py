"""LLM backends: `claude -p` headless CLI (default) and the Anthropic SDK.

See wiki/pages/llm-backend.md. Both implement the `LLM` protocol in types.py.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time

from claude_chess.types import LLMResponse

MODEL_ALIASES = {
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5-5",
    "haiku": "claude-haiku-4-5-20251001",
}


class LLMUnavailable(RuntimeError):
    """The backend itself failed (rate/session limit, outage, timeouts) after backoff.

    Deliberately NOT a subclass of LLMError: players must never count this as an
    illegal/unparseable move. The match runner aborts the game instead.
    """


_LIMIT_MARKERS = ("limit", "429", "overloaded", "rate", "529", "quota")


def _is_limit_error(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in _LIMIT_MARKERS)


class LLMError(RuntimeError):
    pass


class _Counters:
    """Thread-safe call/cost/token counters shared by every backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.cost_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0

    def record(self, resp: LLMResponse) -> None:
        with self._lock:
            self.calls += 1
            self.cost_usd += resp.cost_usd
            self.input_tokens += resp.input_tokens
            self.output_tokens += resp.output_tokens

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "calls": self.calls,
                "cost_usd": self.cost_usd,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            }


class ClaudeCLI:
    """Runs `claude -p` headless; prompt on stdin, system prompt via --system-prompt."""

    def __init__(
        self,
        model: str = "sonnet",
        timeout: float = 180.0,
        retries: int = 2,
        executable: str = "claude",
        thinking_tokens: int | None = None,
    ) -> None:
        self.model = model
        # Extended-thinking budget per call (env MAX_THINKING_TOKENS). None = CLI default,
        # which lets Haiku think for ~10k+ tokens on a chess prompt (~$0.09, minutes/call).
        # 0 disables thinking. See wiki/pages/llm-backend.md.
        self.thinking_tokens = thinking_tokens
        self._env = None
        if thinking_tokens is not None:
            self._env = {**os.environ, "MAX_THINKING_TOKENS": str(int(thinking_tokens))}
        self.timeout = timeout
        self.retries = retries
        self.executable = executable
        self.counters = _Counters()
        # Neutral cwd so project CLAUDE.md / hooks never leak into prompts.
        self._cwd = tempfile.mkdtemp(prefix="claude_chess_llm_")

    def _cmd(self, system: str) -> list[str]:
        return [
            self.executable, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--tools", "",
            "--system-prompt", system,
            "--no-session-persistence",
            "--setting-sources", "",
            "--strict-mcp-config",
        ]

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> LLMResponse:
        # max_tokens is not controllable via the CLI; prompts ask for brevity instead.
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            t0 = time.monotonic()
            try:
                proc = subprocess.run(
                    self._cmd(system),
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=self._cwd,
                    env=self._env,
                )
                data = json.loads(proc.stdout)
                if data.get("is_error") or proc.returncode != 0:
                    raise LLMError(f"claude -p error rc={proc.returncode}: {str(data.get('result'))[:300]}")
                usage = data.get("usage") or {}
                resp = LLMResponse(
                    text=data.get("result") or "",
                    cost_usd=float(data.get("total_cost_usd") or 0.0),
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    seconds=time.monotonic() - t0,
                )
                self.counters.record(resp)
                return resp
            except (subprocess.TimeoutExpired, json.JSONDecodeError, LLMError, OSError) as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        if last_err is not None and _is_limit_error(str(last_err)):
            # Rate/session limit: back off for a few minutes before giving up.
            for wait in LIMIT_BACKOFF_S:
                time.sleep(wait)
                try:
                    return self._once(system, prompt)
                except (subprocess.TimeoutExpired, json.JSONDecodeError, LLMError, OSError) as e:
                    last_err = e
        raise LLMUnavailable(f"claude -p failed after retries: {last_err}")

    def _once(self, system: str, prompt: str) -> LLMResponse:
        t0 = time.monotonic()
        proc = subprocess.run(self._cmd(system), input=prompt, capture_output=True, text=True,
                              timeout=self.timeout, cwd=self._cwd, env=self._env)
        data = json.loads(proc.stdout)
        if data.get("is_error") or proc.returncode != 0:
            raise LLMError(f"claude -p error rc={proc.returncode}: {str(data.get('result'))[:300]}")
        usage = data.get("usage") or {}
        resp = LLMResponse(text=data.get("result") or "",
                           cost_usd=float(data.get("total_cost_usd") or 0.0),
                           input_tokens=int(usage.get("input_tokens") or 0),
                           output_tokens=int(usage.get("output_tokens") or 0),
                           seconds=time.monotonic() - t0)
        self.counters.record(resp)
        return resp


LIMIT_BACKOFF_S = (30, 60, 120)


class AnthropicLLM:
    """Direct Anthropic SDK backend (needs ANTHROPIC_API_KEY)."""

    def __init__(self, model: str = "sonnet", retries: int = 2) -> None:
        import anthropic

        self.model = MODEL_ALIASES.get(model, model)
        self.client = anthropic.Anthropic(max_retries=retries)
        self.counters = _Counters()

    # $/Mtok (input, output); rough, for cost accounting only.
    _PRICES = {"opus": (5.0, 25.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}

    def _price(self, inp: int, out: int) -> float:
        for key, (pi, po) in self._PRICES.items():
            if key in self.model:
                return (inp * pi + out * po) / 1e6
        return 0.0

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> LLMResponse:
        t0 = time.monotonic()
        import anthropic

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:  # SDK already retried transient errors
            raise LLMUnavailable(f"anthropic SDK: {e}") from e
        text = "".join(getattr(b, "text", "") for b in msg.content)
        inp, out = msg.usage.input_tokens, msg.usage.output_tokens
        resp = LLMResponse(text=text, cost_usd=self._price(inp, out), input_tokens=inp,
                           output_tokens=out, seconds=time.monotonic() - t0)
        self.counters.record(resp)
        return resp


def make_llm(model: str = "sonnet", backend: str = "auto", thinking_tokens: int | None = None):
    """backend: "auto" (SDK if ANTHROPIC_API_KEY set, else CLI), "cli", or "sdk".
    thinking_tokens applies to the CLI backend only (the SDK path never enables thinking)."""
    if backend == "auto":
        backend = "sdk" if os.environ.get("ANTHROPIC_API_KEY") else "cli"
    if backend == "sdk":
        return AnthropicLLM(model)
    if backend == "cli":
        return ClaudeCLI(model, thinking_tokens=thinking_tokens)
    raise ValueError(f"unknown backend {backend!r}")


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM reply (code fences, prose, trailing junk)."""
    attempts: list[str] = [m.strip() for m in _FENCE_RE.findall(text)]
    attempts.append(text.strip())
    decoder = json.JSONDecoder()
    for chunk in attempts:
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        for i, ch in enumerate(chunk):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(chunk, i)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    raise ValueError(f"no JSON object found in: {text[:200]!r}")
