"""Deal qualification for outreach — buy_target + urgency, NOT reference price alone."""

from __future__ import annotations

from dataclasses import dataclass

from hk_bazaar.database.models import Listing
from hk_bazaar.outreach.catalog import CatalogMatch, match_listing_to_catalog

URGENCY_SIGNALS: tuple[str, ...] = (
    "urgent",
    "moving",
    "quick sale",
    "price drop",
    "must go",
    "must sell",
    "leaving hk",
    "clearance",
    "today only",
    "asap",
    "急售",
    "搬屋",
    "急清",
    "平賣",
    "清貨",
    "急讓",
    "moving sale",
    "leaving hong kong",
)


@dataclass(frozen=True)
class QualifiedDeal:
    listing: Listing
    match: CatalogMatch
    listing_price: float
    buy_target: float
    price_ratio: float
    has_urgency: bool
    reasons: list[str]


def has_urgency_signals(title: str, description: str | None = None) -> bool:
    blob = f"{title} {description or ''}".lower()
    return any(sig in blob for sig in URGENCY_SIGNALS)


def qualify_listing(
    listing: Listing,
    *,
    strict_price_ratio: float = 1.15,
    urgency_price_ratio: float = 1.25,
) -> QualifiedDeal | None:
    """
    Qualify for outreach only when:
      - Strong catalog match, AND
      - price <= buy_target × 1.15 (+15%), OR
      - price <= buy_target × 1.25 (+25%) with urgency signals.

    Never qualifies based on excellent/good reference price alone.
    """
    if listing.price is None or listing.price <= 0:
        return None

    match = match_listing_to_catalog(listing.title, listing.description)
    if match is None:
        return None

    buy_target = match.item.buy_target
    price = float(listing.price)
    ratio = price / buy_target
    urgent = has_urgency_signals(listing.title, listing.description)

    reasons: list[str] = []
    qualified = False

    if ratio <= strict_price_ratio:
        qualified = True
        reasons.append(
            f"price HKD {price:,.0f} ≤ buy_target HKD {buy_target:,.0f} × {strict_price_ratio:.2f}"
        )
    elif ratio <= urgency_price_ratio and urgent:
        qualified = True
        reasons.append(
            f"price HKD {price:,.0f} ≤ buy_target × {urgency_price_ratio:.2f} with urgency signals"
        )

    if not qualified:
        return None

    reasons.insert(0, f"matched {match.item.display_name} ({match.sku}, confidence {match.confidence:.0f})")
    if urgent:
        reasons.append("urgency keywords detected")

    return QualifiedDeal(
        listing=listing,
        match=match,
        listing_price=price,
        buy_target=buy_target,
        price_ratio=ratio,
        has_urgency=urgent,
        reasons=reasons,
    )