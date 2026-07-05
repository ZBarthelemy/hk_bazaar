"""CRUD and upsert tests."""

from hk_bazaar.database.crud import upsert_listing
from hk_bazaar.database.models import Platform
from hk_bazaar.scrapers.base import RawListing


def test_upsert_creates_and_updates(db_session) -> None:
    raw = RawListing(
        platform=Platform.ASIA_XPAT,
        external_id="test-1",
        title="Chair",
        url="https://example.com/1",
        price=100.0,
        price_display="HKD 100",
    )
    listing, created = upsert_listing(db_session, raw)
    assert created is True
    assert listing.id is not None

    raw.price = 80.0
    raw.price_display = "HKD 80"
    listing2, created2 = upsert_listing(db_session, raw)
    assert created2 is False
    assert listing2.id == listing.id
    assert listing2.price == 80.0