"""Learned knowledge base: lessons distilled from the best model's own game mistakes.

Separate from the hand-written `knowledge/` so it can be switched on/off, versioned and
revisited at any point (see wiki/pages/learning-loop.md):

    knowledge_learned/
      manifest.json        version counter + append-only history of add/retire events
      config.json          which models trigger auto-learning after a match
      lessons/<id>.md      accepted lessons (immutable once written; retire, don't edit)
      rejected/<id>.md     proposals the gate rejected, kept for audit

Lesson pages use the concept-page format (`title:`, `tags: [...]`, `## Summary` bullets)
plus provenance, and are retrieved the same way: eligible only if the position has the
lesson's primary (first) tag, ranked by summed tag weight.

The KB is OFF unless activated (`set_active(path)`, `--learned-kb`, or the
CLAUDE_CHESS_LEARNED_KB env var), so frozen experiments are unaffected.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .paths import REPO_ROOT

DEFAULT_DIR = REPO_ROOT / "knowledge_learned"

_lock = threading.Lock()
_active: Path | None = None
if os.environ.get("CLAUDE_CHESS_LEARNED_KB"):
    _env = os.environ["CLAUDE_CHESS_LEARNED_KB"]
    _active = DEFAULT_DIR if _env in ("1", "default", "latest") else Path(_env)


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    tags: tuple[str, ...]
    summary: tuple[str, ...]
    status: str = "active"


def resolve(path: str | Path | None) -> Path | None:
    if path in (None, "", "off", "none"):
        return None
    return DEFAULT_DIR if str(path) in ("1", "default", "latest") else Path(path)


def set_active(path: str | Path | None) -> None:
    """Turn the learned KB on (a directory) or off (None) for this process."""
    global _active
    with _lock:
        _active = resolve(path)
        _cache.clear()


def active() -> Path | None:
    return _active


def parse_lesson(text: str, lesson_id: str) -> Lesson:
    title = re.search(r"^title:\s*(.+)$", text, re.M)
    tags = re.search(r"^tags:\s*\[?([^\]\n]*)\]?$", text, re.M)
    status = re.search(r"^status:\s*(\w+)$", text, re.M)
    sec = re.search(r"^## Summary\s*\n(.*?)(?:^## |\Z)", text, re.M | re.S)
    summary = [ln[2:].strip() for ln in sec.group(1).splitlines() if ln.startswith("- ")][:3] if sec else []
    return Lesson(lesson_id, title.group(1).strip() if title else lesson_id,
                  tuple(t.strip() for t in (tags.group(1) if tags else "").split(",") if t.strip()),
                  tuple(summary), status.group(1) if status else "active")


_cache: dict[tuple[str, float], tuple[Lesson, ...]] = {}


def load(kb: Path | None = None) -> tuple[Lesson, ...]:
    """Active lessons in `kb` (default: the active KB). Cached per manifest mtime."""
    kb = kb or _active
    if kb is None or not (kb / "lessons").is_dir():
        return ()
    man = kb / "manifest.json"
    key = (str(kb), man.stat().st_mtime if man.exists() else 0.0)
    if key not in _cache:
        retired = retired_ids(kb)
        out = []
        for p in sorted((kb / "lessons").glob("*.md")):
            les = parse_lesson(p.read_text(encoding="utf-8"), p.stem)
            if les.status == "active" and les.id not in retired:
                out.append(les)
        _cache[key] = tuple(out)
    return _cache[key]


def retrieve(tags: set[str], k: int = 1, kb: Path | None = None) -> list[Lesson]:
    from .concepts import TAG_WEIGHTS
    scored = []
    for les in load(kb):
        if not les.tags or les.tags[0] not in tags:
            continue
        score = sum(TAG_WEIGHTS.get(t, 1.0) for t in les.tags if t in tags) + TAG_WEIGHTS.get(les.tags[0], 1.0)
        scored.append((score, les.id, les))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [les for _, _, les in scored[:k]]


# ── manifest / versions ─────────────────────────────────────────────────────


def read_manifest(kb: Path = DEFAULT_DIR) -> dict:
    p = kb / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"version": 0, "history": []}


def write_manifest(kb: Path, man: dict) -> None:
    (kb / "manifest.json").write_text(json.dumps(man, indent=2) + "\n")


def retired_ids(kb: Path) -> set[str]:
    return {h["lesson"] for h in read_manifest(kb)["history"] if h["action"] == "retire"}


def ids_at_version(kb: Path, version: int) -> list[str]:
    """Active lesson ids after replaying the history up to `version`."""
    active_ids: list[str] = []
    for h in read_manifest(kb)["history"]:
        if h["version"] > version:
            break
        if h["action"] == "add":
            active_ids.append(h["lesson"])
        elif h["action"] == "retire" and h["lesson"] in active_ids:
            active_ids.remove(h["lesson"])
    return active_ids


def version(kb: Path | None = None) -> int | None:
    kb = kb or _active
    return read_manifest(kb)["version"] if kb else None
