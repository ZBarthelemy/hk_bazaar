"""Deal finder tests."""

from hk_bazaar.analyzers.deal_finder import find_deals
from hk_bazaar.database.crud import upsert_listing
from hk_bazaar.database.models import Platform
from hk_bazaar.scrapers.base import RawListing


def test_find_deals_urgency_and_free(db_session) -> None:
    samples = [
        RawListing(
            platform=Platform.ASIA_XPAT,
            external_id="d1",
            title="IKEA desk urgent moving sale",
            description="Must go Wong Tai Sin",
            price=150.0,
            price_display="HKD 150",
            category="Furniture",
            url="https://example.com/d1",
        ),
        RawListing(
            platform=Platform.ASIA_XPAT,
            external_id="d2",
            title="Office chair",
            price=800.0,
            category="Furniture",
            url="https://example.com/d2",
        ),
        RawListing(
            platform=Platform.ASIA_XPAT,
            external_id="d3",
            title="Fan 免費",
            price=0.0,
            category="Home & Living",
            url="https://example.com/d3",
        ),
    ]
    for s in samples:
        upsert_listing(db_session, s)
    db_session.commit()

    deals = find_deals(db_session, limit=10)
    assert len(deals) >= 2
    titles = {d.listing.title for d in deals}
    assert "Fan 免費" in titles or any("urgent" in t.lower() for t in titles)