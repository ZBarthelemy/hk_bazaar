"""Normalize raw scraped listings."""

from __future__ import annotations

from hk_bazaar.scrapers.base import RawListing
from hk_bazaar.scrapers.parsers import parse_price
from hk_bazaar.utils.categories import map_category
from hk_bazaar.utils.hk_locations import extract_location_from_text


def clean_listing(raw: RawListing) -> RawListing:
    """Apply price, location, and category normalization in-place."""
    if raw.price_display and raw.price is None:
        price, display = parse_price(raw.price_display)
        raw.price = price
        raw.price_display = display or raw.price_display

    if not raw.district:
        loc_raw, district, region = extract_location_from_text(
            raw.location_raw,
            raw.title,
            raw.description,
        )
        if loc_raw and not raw.location_raw:
            raw.location_raw = loc_raw
        raw.district = district
        raw.region = region

    category_raw, canonical = map_category(
        raw.category_raw,
        platform=raw.platform.value,
        title=raw.title,
    )
    raw.category_raw = category_raw
    raw.category = canonical

    if raw.title:
        raw.title = raw.title.strip()
    if raw.description:
        raw.description = raw.description.strip()

    return raw