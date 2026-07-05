"""Bluebook reference pricing for common HK flip SKUs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hk_bazaar.analyzers.product_matcher import ProductMatch, match_product
from hk_bazaar.config import PROJECT_ROOT, get_settings
from hk_bazaar.database.models import Listing

VALID_CONDITIONS = ("excellent", "good", "fair")


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    display_name: str
    family: str
    brand: str | None
    references: dict[str, float]
    buy_target: float | None
    sell_target: float | None
    source: str
    notes: str | None


@dataclass(frozen=True)
class BluebookValuation:
    sku: str
    display_name: str
    condition: str
    reference_price: float
    buy_target: float | None
    sell_target: float | None
    listing_price: float
    delta_hkd: float
    delta_pct: float
    confidence: float
    verdict: str
    source: str


def _catalog_path() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "bluebook_catalog_path", PROJECT_ROOT / "data" / "bluebook" / "catalog.yaml"))


@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> dict[str, CatalogItem]:
    yaml_path = Path(path) if path else _catalog_path()
    raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    catalog: dict[str, CatalogItem] = {}
    for sku, item in (raw.get("items") or {}).items():
        catalog[sku] = CatalogItem(
            sku=sku,
            display_name=str(item.get("display_name", sku)),
            family=str(item.get("family", "other")),
            brand=item.get("brand"),
            references={k: float(v) for k, v in (item.get("references") or {}).items()},
            buy_target=float(item["buy_target"]) if item.get("buy_target") is not None else None,
            sell_target=float(item["sell_target"]) if item.get("sell_target") is not None else None,
            source=str(item.get("source", "manual")),
            notes=item.get("notes"),
        )
    return catalog


def get_catalog_item(sku: str) -> CatalogItem | None:
    return load_catalog().get(sku)


def get_reference_price(sku: str, condition: str = "good") -> float | None:
    item = get_catalog_item(sku)
    if item is None:
        return None
    cond = condition if condition in VALID_CONDITIONS else "good"
    return item.references.get(cond) or item.references.get("good")


def _verdict(delta_pct: float) -> str:
    """delta_pct = (reference - listing) / reference; positive means below reference."""
    if delta_pct >= 20:
        return "strong_buy"
    if delta_pct >= 10:
        return "good_buy"
    if delta_pct >= -5:
        return "fair"
    if delta_pct >= -15:
        return "overpriced"
    return "well_overpriced"


def value_listing(
    listing: Listing,
    *,
    condition: str | None = None,
) -> BluebookValuation | None:
    if listing.price is None or listing.price <= 0:
        return None

    match = match_product(listing.title, listing.description)
    if match is None:
        return None

    return value_from_match(
        match,
        listing_price=float(listing.price),
        condition=condition or match.condition,
    )


def value_from_match(
    match: ProductMatch,
    *,
    listing_price: float,
    condition: str | None = None,
) -> BluebookValuation | None:
    item = get_catalog_item(match.sku)
    if item is None:
        return None

    cond = condition or match.condition
    reference = get_reference_price(match.sku, cond)
    if reference is None:
        return None

    delta = reference - listing_price
    delta_pct = (delta / reference) * 100.0

    return BluebookValuation(
        sku=match.sku,
        display_name=item.display_name,
        condition=cond,
        reference_price=reference,
        buy_target=item.buy_target,
        sell_target=item.sell_target,
        listing_price=listing_price,
        delta_hkd=delta,
        delta_pct=delta_pct,
        confidence=match.confidence,
        verdict=_verdict(delta_pct),
        source=item.source,
    )