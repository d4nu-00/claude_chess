"""Concept retrieval from knowledge/concepts/*.md and knowledge/openings_plans.md.

Pages have a tiny front matter block (`title:`, `tags: [a, b]`) and a `## Summary`
section of <=4 bullets. The builder emits position tags with weights; pages are scored
by the summed weight of matching tags, but only pages whose primary (first) tag is
present are eligible, so a secondary tag never drags in an unrelated page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .paths import KNOWLEDGE_DIR

CONCEPTS_DIR = KNOWLEDGE_DIR / "concepts"
PLANS_FILE = KNOWLEDGE_DIR / "openings_plans.md"

# Weight per tag emitted by the feature extractors. Named structures dominate.
TAG_WEIGHTS: dict[str, float] = {
    "iqp": 5, "hanging-pawns": 5, "carlsbad": 5, "maroczy": 5, "hedgehog": 6, "sicilian": 3,
    "french-chain": 5, "kid-locked": 5, "benoni": 5, "stonewall": 5,
    "rook-endgame": 5, "pawn-endgame": 6, "opposite-castling": 4, "tactics": 3,
    "passed-pawn": 2.5, "bishop-pair": 2, "opposite-bishops": 2, "exchange": 3,
    "king-safety": 2.5, "development": 2.5, "opening": 1, "endgame": 1.5,
    "outpost": 1.5, "open-file": 1, "seventh-rank": 1.5, "bad-bishop": 2.5,
    "weak-pawns": 1, "pawn-majority": 1, "minority-attack": 1, "closed": 1, "prophylaxis": 0.5,
}


@dataclass(frozen=True)
class ConceptPage:
    slug: str
    title: str
    tags: tuple[str, ...]
    summary: tuple[str, ...]


@lru_cache(maxsize=1)
def load_pages() -> tuple[ConceptPage, ...]:
    pages = []
    for path in sorted(CONCEPTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title_m = re.search(r"^title:\s*(.+)$", text, re.M)
        tags_m = re.search(r"^tags:\s*\[?([^\]\n]*)\]?$", text, re.M)
        tags = tuple(t.strip() for t in (tags_m.group(1) if tags_m else "").split(",") if t.strip())
        summ: list[str] = []
        sec = re.search(r"^## Summary\s*\n(.*?)(?:^## |\Z)", text, re.M | re.S)
        if sec:
            summ = [ln[2:].strip() for ln in sec.group(1).splitlines() if ln.startswith("- ")][:4]
        pages.append(ConceptPage(path.stem, title_m.group(1).strip() if title_m else path.stem, tags, tuple(summ)))
    return tuple(pages)


def retrieve(tags: set[str], k: int = 3) -> list[ConceptPage]:
    scored = []
    for page in load_pages():
        # A page is only eligible if the position has its primary (first) tag: the page
        # must be *about* something present, secondary tags only rank eligible pages.
        if not page.tags or page.tags[0] not in tags:
            continue
        hit = [TAG_WEIGHTS.get(t, 1.0) for t in page.tags if t in tags]
        score = sum(hit) + TAG_WEIGHTS.get(page.tags[0], 1.0)  # primary counts double
        scored.append((score, page.slug, page))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [p for _, _, p in scored[:k]]


@lru_cache(maxsize=1)
def load_opening_plans() -> tuple[tuple[str, tuple[str, ...], str], ...]:
    if not PLANS_FILE.exists():
        return ()
    out = []
    text = PLANS_FILE.read_text(encoding="utf-8")
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        family = lines[0]
        match = next((ln[6:] for ln in lines if ln.startswith("match:")), "")
        prefixes = tuple(p.strip() for p in match.split(",") if p.strip())
        plan = " ".join(ln for ln in lines[1:] if not ln.startswith("match:"))
        out.append((family, prefixes, plan))
    return tuple(out)


def opening_plan(opening_name: str) -> tuple[str, str] | None:
    """Return (family, plan) for an ECO name like 'Ruy Lopez: Berlin Defense'."""
    best: tuple[int, str, str] | None = None
    for family, prefixes, plan in load_opening_plans():
        for p in prefixes:
            if opening_name.startswith(p) and (best is None or len(p) > best[0]):
                best = (len(p), family, plan)
    return (best[1], best[2]) if best else None
