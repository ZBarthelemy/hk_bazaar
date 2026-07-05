"""SQLAlchemy ORM models."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Platform(enum.StrEnum):
    ASIA_XPAT = "asia_xpat"
    CAROUSELL = "carousell"
    FACEBOOK_MARKETPLACE = "facebook_marketplace"


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_listing_platform_external_id"),
        Index("ix_listings_category", "category"),
        Index("ix_listings_district", "district"),
        Index("ix_listings_price", "price"),
        Index("ix_listings_posted_at", "posted_at"),
        Index("ix_listings_scraped_at", "scraped_at"),
        Index("ix_listings_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_display: Mapped[str | None] = mapped_column(String(128), nullable=True)

    location_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    category_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(256), nullable=True)

    condition: Mapped[str | None] = mapped_column(String(128), nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    seller_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    image_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    favorites: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PriceHistory(Base):
    """Track price changes when listings are re-scraped."""

    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_history_listing_id", "listing_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_display: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )