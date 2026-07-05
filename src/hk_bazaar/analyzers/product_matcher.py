"""Match listing titles to bluebook SKU keys."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hk_bazaar.config import PROJECT_ROOT, get_settings

CONDITION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "excellent": ("brand new", "like new", "全新", "99% new", "99新", "極新"),
    "good": ("very good", "lightly used", "95新", "9成新", "良好"),
    "fair": ("well used", "heavily used", "8成新", "7成新", "一般用"),
}


@dataclass(frozen=True)
class ProductMatch:
    sku: str
    confidence: float
    condition: str


def _patterns_path() -> Path:
    settings = get_settings()
    catalog = getattr(settings, "bluebook_catalog_path", PROJECT_ROOT / "data" / "bluebook" / "catalog.yaml")
    return catalog.parent / "patterns.yaml"


@lru_cache(maxsize=1)
def load_patterns(path: str | None = None) -> dict[str, list[re.Pattern[str]]]:
    yaml_path = Path(path) if path else _patterns_path()
    raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    compiled: dict[str, list[re.Pattern[str]]] = {}
    for sku, patterns in (raw.get("patterns") or {}).items():
        compiled[sku] = [re.compile(p, re.I) for p in patterns]
    return compiled


def infer_condition(text: str) -> str:
    lower = text.lower()
    for condition, keywords in CONDITION_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return condition
    return "good"


def match_product(title: str, description: str | None = None) -> ProductMatch | None:
    """Return best SKU match for a listing title, or None."""
    blob = f"{title} {description or ''}".strip()
    if not blob:
        return None

    patterns = load_patterns()
    best_sku: str | None = None
    best_score = 0.0

    for sku, regexes in patterns.items():
        for rx in regexes:
            if rx.search(blob):
                # Longer/more specific patterns score higher when multiple match.
                score = len(rx.pattern) / 100.0 + 0.5
                if score > best_score:
                    best_score = score
                    best_sku = sku

    if best_sku is None:
        return None

    confidence = min(1.0, best_score)
    return ProductMatch(sku=best_sku, confidence=confidence, condition=infer_condition(blob))