"""Locate the repo-level knowledge/ directory."""

from __future__ import annotations

from pathlib import Path

# src/claude_chess/context/paths.py -> repo root is three parents above the package dir.
KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"
