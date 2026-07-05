"""CRUD helpers for listings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from hk_bazaar.database.models import Listing, Platform, PriceHistory
from hk_bazaar.scrapers.base import RawListing


def upsert_listing(session: Session, raw: RawListing) -> tuple[Listing, bool]:
    """Insert or update a listing. Returns (listing, created)."""
    stmt = select(Listing).where(
        Listing.platform == raw.platform,
        Listing.external_id == raw.external_id,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(UTC)

    if existing is None:
        listing = Listing(
            platform=raw.platform,
            external_id=raw.external_id,
            title=raw.title,
            description=raw.description,
            price=raw.price,
            price_display=raw.price_display,
            location_raw=raw.location_raw,
            district=raw.district,
            region=raw.region,
            category_raw=raw.category_raw,
            category=raw.category,
            condition=raw.condition,
            posted_at=raw.posted_at,
            posted_at_raw=raw.posted_at_raw,
            scraped_at=now,
            url=raw.url,
            seller_name=raw.seller_name,
            seller_external_id=raw.seller_external_id,
            image_urls=raw.image_urls,
            views=raw.views,
            favorites=raw.favorites,
            is_active=raw.is_active,
            extra=raw.extra,
        )
        session.add(listing)
        session.flush()
        return listing, True

    price_changed = existing.price != raw.price
    if price_changed:
        session.add(
            PriceHistory(
                listing_id=existing.id,
                price=existing.price,
                price_display=existing.price_display,
            )
        )

    existing.title = raw.title
    existing.description = raw.description
    existing.price = raw.price
    existing.price_display = raw.price_display
    existing.location_raw = raw.location_raw
    existing.district = raw.district
    existing.region = raw.region
    existing.category_raw = raw.category_raw
    existing.category = raw.category
    existing.condition = raw.condition
    existing.posted_at = raw.posted_at or existing.posted_at
    existing.posted_at_raw = raw.posted_at_raw or existing.posted_at_raw
    existing.scraped_at = now
    existing.url = raw.url
    existing.seller_name = raw.seller_name
    existing.seller_external_id = raw.seller_external_id
    existing.image_urls = raw.image_urls
    existing.views = raw.views
    existing.favorites = raw.favorites
    existing.is_active = raw.is_active
    existing.extra = {**existing.extra, **raw.extra}
    existing.updated_at = now
    session.flush()
    return existing, False


def query_listings(
    session: Session,
    *,
    platform: Platform | None = None,
    category: str | None = None,
    district: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    search: str | None = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[Listing]:
    stmt: Select[tuple[Listing]] = select(Listing).order_by(Listing.scraped_at.desc())

    if platform is not None:
        stmt = stmt.where(Listing.platform == platform)
    if category is not None:
        stmt = stmt.where(Listing.category.ilike(f"%{category}%"))
    if district is not None:
        stmt = stmt.where(Listing.district.ilike(f"%{district}%"))
    if max_price is not None:
        stmt = stmt.where(Listing.price <= max_price)
    if min_price is not None:
        stmt = stmt.where(Listing.price >= min_price)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Listing.title.ilike(pattern) | Listing.description.ilike(pattern)
        )
    if active_only:
        stmt = stmt.where(Listing.is_active.is_(True))

    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def get_stats(session: Session) -> dict[str, Any]:
    total = session.execute(select(func.count()).select_from(Listing)).scalar_one()
    by_platform = dict(
        session.execute(
            select(Listing.platform, func.count()).group_by(Listing.platform)
        ).all()
    )
    with_price = session.execute(
        select(func.count()).select_from(Listing).where(Listing.price.is_not(None))
    ).scalar_one()
    avg_price = session.execute(select(func.avg(Listing.price))).scalar_one()
    categories = dict(
        session.execute(
            select(Listing.category, func.count())
            .where(Listing.category.is_not(None))
            .group_by(Listing.category)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
    )
    return {
        "total_listings": total,
        "by_platform": {k.value: v for k, v in by_platform.items()},
        "with_price": with_price,
        "avg_price_hkd": round(avg_price, 2) if avg_price else None,
        "top_categories": categories,
    }