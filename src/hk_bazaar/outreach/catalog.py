"""Catalog loader and fuzzy listing matcher for outreach."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from hk_bazaar.config import PROJECT_ROOT, get_settings

CONDITION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "excellent": ("brand new", "like new", "全新", "99% new", "99新", "極新"),
    "good": ("very good", "lightly used", "95新", "9成新", "良好"),
    "fair": ("well used", "heavily used", "8成新", "7成新", "一般用"),
}

STRONG_MATCH_THRESHOLD = 75.0


class CatalogReferences(BaseModel):
    excellent: float | None = None
    good: float | None = None
    fair: float | None = None


class CatalogItem(BaseModel):
    sku: str
    family: str
    brand: str | None = None
    display_name: str
    references: CatalogReferences = Field(default_factory=CatalogReferences)
    buy_target: float
    sell_target: float | None = None
    source: str | None = None
    notes: str | None = None
    updated_at: str | None = None
    search_keywords: list[str] = Field(default_factory=list)


class CatalogMatch(BaseModel):
    sku: str
    item: CatalogItem
    confidence: float
    fuzzy_score: float
    matched_keyword: str
    inferred_condition: str


def _catalog_path() -> Path:
    settings = get_settings()
    return Path(settings.bluebook_catalog_path)


def _patterns_path() -> Path:
    return _catalog_path().parent / "patterns.yaml"


def _keyword_variations(item: CatalogItem) -> list[str]:
    keywords: list[str] = [item.display_name]
    if item.brand:
        keywords.append(item.brand)
        keywords.append(f"{item.brand} {item.display_name}")
    keywords.append(item.sku.replace("_", " "))

    # Derive compact forms: "iPhone 13 128GB" → "iPhone 13", "13 128gb"
    parts = item.display_name.split()
    if len(parts) >= 2:
        keywords.append(" ".join(parts[:2]))
    if len(parts) >= 3:
        keywords.append(" ".join(parts[-2:]))

    for kw in item.search_keywords:
        if kw not in keywords:
            keywords.append(kw)
    return list(dict.fromkeys(k for k in keywords if k.strip()))


@lru_cache(maxsize=1)
def load_outreach_catalog(path: str | None = None) -> dict[str, CatalogItem]:
    yaml_path = Path(path) if path else _catalog_path()
    raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    catalog: dict[str, CatalogItem] = {}

    pattern_map: dict[str, list[str]] = {}
    if _patterns_path().exists():
        patterns_raw = yaml.safe_load(_patterns_path().read_text(encoding="utf-8")) or {}
        for sku, pats in (patterns_raw.get("patterns") or {}).items():
            pattern_map[sku] = [re.sub(r"\\s\*", " ", p) for p in pats]

    for sku, data in (raw.get("items") or {}).items():
        refs = data.get("references") or {}
        item = CatalogItem(
            sku=sku,
            family=str(data.get("family", "other")),
            brand=data.get("brand"),
            display_name=str(data.get("display_name", sku)),
            references=CatalogReferences(
                excellent=refs.get("excellent"),
                good=refs.get("good"),
                fair=refs.get("fair"),
            ),
            buy_target=float(data["buy_target"]),
            sell_target=float(data["sell_target"]) if data.get("sell_target") is not None else None,
            source=data.get("source"),
            notes=data.get("notes"),
            updated_at=data.get("updated_at"),
            search_keywords=pattern_map.get(sku, []),
        )
        item.search_keywords = _keyword_variations(item) + item.search_keywords
        catalog[sku] = item
    return catalog


def infer_condition(text: str) -> str:
    lower = text.lower()
    for condition, keywords in CONDITION_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return condition
    return "good"


def condition_bonus(item: CatalogItem, condition: str) -> float:
    """Small confidence boost when listing text hints at a priced condition tier."""
    if condition == "excellent" and item.references.excellent:
        return 3.0
    if condition == "good" and item.references.good:
        return 2.0
    if condition == "fair" and item.references.fair:
        return 1.0
    return 0.0


def match_listing_to_catalog(
    title: str,
    description: str | None = None,
    *,
    catalog: dict[str, CatalogItem] | None = None,
) -> CatalogMatch | None:
    """
    Fuzzy-match listing text against catalog search profiles.
    Returns a match only when confidence is high (>= STRONG_MATCH_THRESHOLD).
    """
    blob = f"{title} {description or ''}".strip()
    if not blob:
        return None

    catalog = catalog or load_outreach_catalog()
    best: CatalogMatch | None = None

    for sku, item in catalog.items():
        choices = item.search_keywords
        result = process.extractOne(blob, choices, scorer=fuzz.partial_ratio)
        if result is None:
            continue
        _choice, fuzzy_score, _ = result
        condition = infer_condition(blob)
        score = float(fuzzy_score) + condition_bonus(item, condition)

        # Regex patterns from patterns.yaml as a hard gate for weak fuzzy hits.
        patterns_path = _patterns_path()
        if patterns_path.exists():
            patterns_raw = yaml.safe_load(patterns_path.read_text(encoding="utf-8")) or {}
            pats = patterns_raw.get("patterns", {}).get(sku, [])
            if pats and not any(re.search(p, blob, re.I) for p in pats):
                if fuzzy_score < 85:
                    continue

        if best is None or score > best.confidence:
            best = CatalogMatch(
                sku=sku,
                item=item,
                confidence=score,
                fuzzy_score=float(fuzzy_score),
                matched_keyword=_choice,
                inferred_condition=condition,
            )

    if best is None or best.confidence < STRONG_MATCH_THRESHOLD:
        return None
    return best