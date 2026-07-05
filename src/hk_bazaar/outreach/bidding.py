"""Proposed bid calculation and message rendering."""

from __future__ import annotations

import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hk_bazaar.config import get_settings
from hk_bazaar.outreach.qualification import QualifiedDeal

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def round_bid(amount: float) -> int:
    """Round to nearest HK$50 (<5k) or HK$100 (≥5k)."""
    step = 50 if amount < 5000 else 100
    return int(round(amount / step) * step)


def calculate_proposed_bid(buy_target: float, discount: float | None = None) -> int:
    settings = get_settings()
    disc = discount if discount is not None else settings.outreach_bid_discount
    raw = buy_target * disc
    return round_bid(raw)


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
    district = deal.listing.district or deal.listing.location_raw or "Hong Kong"
    return template.render(
        display_name=deal.match.item.display_name,
        proposed_bid=proposed_bid,
        listing_price=int(deal.listing_price),
        buy_target=int(deal.buy_target),
        district=district,
        platform=deal.listing.platform.value,
        url=deal.listing.url,
    ).strip()