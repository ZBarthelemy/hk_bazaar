"""Proposed bid calculation and message rendering."""

from __future__ import annotations

import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hk_bazaar.config import get_settings
from hk_bazaar.outreach.qualification import QualifiedDeal

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _item_name(title: str | None, display_name: str) -> str:
    """Name the seller's listing. Cut the price that Carousell glues onto the title."""
    cleaned = " ".join((title or "").split())
    for marker in ("HK$", "HKD"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip(" -–|")
    cleaned = cleaned.strip()
    if 3 <= len(cleaned) <= 90:
        return cleaned
    return display_name


def _pickup_place(district: str | None) -> str | None:
    """Use a stored district only. Description text must not become the pickup line."""
    place = (district or "").strip()
    if not place or len(place) > 40 or any(mark in place for mark in ("\n", "HK$", "http")):
        return None
    return place


def round_bid(amount: float) -> int:
    """Round to nearest HK$50 (<5k) or HK$100 (≥5k)."""
    step = 50 if amount < 5000 else 100
    return int(round(amount / step) * step)


def calculate_proposed_bid(asking_price: float, discount: float | None = None) -> int:
    """Discount the asking price, then round. The result stays below the ask."""
    settings = get_settings()
    disc = discount if discount is not None else settings.outreach_bid_discount
    bid = round_bid(asking_price * disc)
    ceiling = int(asking_price)
    if bid >= ceiling:
        floored = int(asking_price * disc)
        bid = floored if 0 < floored < ceiling else max(ceiling - 1, 1)
    return bid


def render_offer_message(
    deal: QualifiedDeal,
    proposed_bid: int,
    *,
    template_name: str = "offer_default.txt.j2",
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_name)
    district = _pickup_place(deal.listing.district)
    return template.render(
        display_name=_item_name(deal.listing.title, deal.match.item.display_name),
        proposed_bid=proposed_bid,
        listing_price=int(deal.listing_price),
        buy_target=int(deal.buy_target),
        district=district,
        platform=deal.listing.platform.value,
        url=deal.listing.url,
    ).strip()