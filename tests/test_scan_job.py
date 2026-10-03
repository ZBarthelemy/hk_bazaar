"""Scan job counts: new rows, and new iPhone SKUs under the bluebook reference."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from hk_bazaar.database.models import Platform
from hk_bazaar.jobs.scan import format_report, run_scan
from hk_bazaar.scrapers.base import RawListing
from hk_bazaar.scrapers.paging import PageWalk


class _Scraper:
    def __init__(self, rows: list[RawListing]) -> None:
        self.rows = rows

    def scrape(self, **_: object) -> list[RawListing]:
        return self.rows


def _listing(external_id: str, title: str, price: float) -> RawListing:
    return RawListing(
        platform=Platform.CAROUSELL,
        external_id=external_id,
        title=title,
        url=f"https://www.carousell.com.hk/p/{external_id}",
        price=price,
    )


def test_scan_counts_new_rows_and_cheap_iphone_skus(db_session: Session) -> None:
    rows = [
        _listing("cheap", "iPhone 13 128GB", 1800),
        _listing("fair-price", "iPhone 13 128GB", 3000),
        _listing("case", "iPhone 13 128GB silicone case", 50),
        _listing("sofa", "IKEA sofa", 400),
    ]
    report = run_scan(
        db_session,
        scrapers=[("Carousell", lambda: _Scraper(rows), {})],
        write=False,
        now=datetime(2026, 10, 1, 12, 0, 0),
    )
    source = report.sources[0]
    assert source.scraped == 4
    assert source.new == 4
    assert source.updated == 0
    assert source.cheap_iphones == 1
    assert source.hits[0].sku == "iphone_13_128gb"
    assert source.hits[0].price == 1800

    again = run_scan(
        db_session,
        scrapers=[("Carousell", lambda: _Scraper(rows), {})],
        write=False,
        now=datetime(2026, 10, 1, 12, 5, 0),
    )
    repeat = again.sources[0]
    assert repeat.new == 0
    assert repeat.updated == 4
    assert repeat.cheap_iphones == 0

    text = format_report(report)
    assert "cheap_iphones" in text
    assert "caught_up" in text
    assert "Carousell" in text
    assert "HKD 1,800" in text
    assert "iphone_13_128gb" in text


def test_price_drop_below_reference_is_counted(db_session: Session) -> None:
    first = [_listing("drop", "iPhone 13 128GB", 3200)]
    opened = run_scan(
        db_session,
        scrapers=[("Carousell", lambda: _Scraper(first), {})],
        write=False,
        now=datetime(2026, 10, 1, 12, 0, 0),
    )
    assert opened.sources[0].cheap_iphones == 0

    dropped = [_listing("drop", "iPhone 13 128GB", 1800)]
    again = run_scan(
        db_session,
        scrapers=[("Carousell", lambda: _Scraper(dropped), {})],
        write=False,
        now=datetime(2026, 10, 1, 13, 0, 0),
    )
    assert again.sources[0].new == 0
    assert again.sources[0].updated == 1
    assert again.sources[0].cheap_iphones == 1


def test_page_walk_stops_when_the_page_is_already_stored() -> None:
    known = PageWalk({"old"})
    assert known.add([_listing("old", "iPhone 13 128GB", 1000)]) is True
    assert known.caught_up is True

    fresh = PageWalk({"old"})
    assert fresh.add([_listing("new", "iPhone 13 128GB", 1000)]) is False
    assert fresh.caught_up is False

    done = PageWalk(set())
    assert done.add([]) is True
    assert done.caught_up is True

    stuck = PageWalk(None)
    assert stuck.add([_listing("same", "iPhone 13 128GB", 1000)]) is False
    assert stuck.add([_listing("same", "iPhone 13 128GB", 1000)]) is True
    assert stuck.caught_up is False
