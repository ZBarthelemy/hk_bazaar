"""
v1 deal flagging — expand with ML, embeddings, or rule engines later.

Signals:
  - Urgency keywords (EN + zh-hk)
  - Price below category median / percentile
  - Recently posted items
  - Free or near-free listings
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hk_bazaar.analyzers.bluebook import value_listing
from hk_bazaar.config import Settings, get_settings
from hk_bazaar.database.models import Listing


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


URGENCY_KEYWORDS = (
    "urgent", "moving", "must go", "must sell", "leaving hk", "clearance",
    "bargain", "cheap", "reduced", "ono", "obo",
    "急售", "平賣", "搬屋", "清貨", "平讓", "急讓", "割愛", "抵讓",
)

FREE_KEYWORDS = ("free", "免費", "送", "0 hkd", "hk$0")


@dataclass
class DealCandidate:
    listing: Listing
    score: float
    reasons: list[str]


def _has_urgency(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in URGENCY_KEYWORDS)


def _is_free_listing(listing: Listing) -> bool:
    if listing.price == 0:
        return True
    blob = f"{listing.title} {listing.description or ''} {listing.price_display or ''}".lower()
    return any(kw in blob for kw in FREE_KEYWORDS)


def _category_price_stats(session: Session) -> dict[str, dict[str, float]]:
    rows = session.execute(
        select(Listing.category, Listing.price).where(
            Listing.price.is_not(None),
            Listing.price > 0,
            Listing.is_active.is_(True),
        )
    ).all()

    by_cat: dict[str, list[float]] = {}
    for cat, price in rows:
        if cat and price is not None:
            by_cat.setdefault(cat, []).append(float(price))

    stats: dict[str, dict[str, float]] = {}
    for cat, prices in by_cat.items():
        if len(prices) < 3:
            continue
        prices_sorted = sorted(prices)
        stats[cat] = {
            "median": statistics.median(prices),
            "mean": statistics.mean(prices),
            "p25": prices_sorted[max(0, int(len(prices_sorted) * 0.25) - 1)],
            "count": float(len(prices)),
        }
    return stats


def find_deals(
    session: Session,
    *,
    settings: Settings | None = None,
    limit: int = 30,
    use_bluebook: bool = False,
) -> list[DealCandidate]:
    settings = settings or get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.deal_recent_days)
    cat_stats = _category_price_stats(session)

    listings = session.execute(
        select(Listing)
        .where(Listing.is_active.is_(True))
        .order_by(Listing.scraped_at.desc())
        .limit(500)
    ).scalars().all()

    candidates: list[DealCandidate] = []

    for listing in listings:
        score = 0.0
        reasons: list[str] = []
        blob = f"{listing.title} {listing.description or ''}"

        posted = _as_utc(listing.posted_at)
        scraped = _as_utc(listing.scraped_at)

        if posted and posted >= cutoff:
            score += 1.0
            reasons.append(f"posted within {settings.deal_recent_days}d")

        if scraped and scraped >= cutoff:
            score += 0.5
            reasons.append("recently scraped")

        if _has_urgency(blob):
            score += 2.0
            reasons.append("urgency keywords")

        if _is_free_listing(listing):
            score += 3.0
            reasons.append("free / giveaway")

        bluebook_scored = False
        if use_bluebook and listing.price:
            valuation = value_listing(listing)
            if valuation is not None:
                bluebook_scored = True
                if valuation.verdict == "strong_buy":
                    score += 4.0
                    reasons.append(
                        f"bluebook {valuation.display_name}: HKD {listing.price:,.0f} "
                        f"vs ref HKD {valuation.reference_price:,.0f} ({valuation.delta_pct:+.0f}%)"
                    )
                elif valuation.verdict == "good_buy":
                    score += 3.0
                    reasons.append(
                        f"bluebook {valuation.display_name}: {valuation.delta_pct:+.0f}% vs reference"
                    )
                elif valuation.verdict == "fair":
                    score += 1.0
                    reasons.append(f"bluebook fair vs {valuation.display_name}")

        if not bluebook_scored and listing.price and listing.category and listing.category in cat_stats:
            st = cat_stats[listing.category]
            threshold = st["p25"]
            if listing.price <= threshold:
                score += 2.5
                reasons.append(
                    f"price HKD {listing.price:,.0f} ≤ category p25 "
                    f"(median HKD {st['median']:,.0f}, n={int(st['count'])})"
                )
            elif listing.price <= st["median"] * 0.7:
                score += 1.5
                reasons.append("price ~30% below category median")

        if score >= 2.0 and reasons:
            candidates.append(DealCandidate(listing=listing, score=score, reasons=reasons))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]