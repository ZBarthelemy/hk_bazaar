"""Scan all three sources and report new rows plus cheap iPhone SKUs.

A cheap iPhone is a listing inserted on this run that matches an ``iphone_*``
bluebook SKU and is priced under that SKU's reference for its condition.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from hk_bazaar.analyzers.bluebook import value_listing
from hk_bazaar.config import PROJECT_ROOT, get_settings
from hk_bazaar.database.crud import upsert_listing
from hk_bazaar.database.models import Listing, Platform
from hk_bazaar.pipelines.cleaning import clean_listing
from hk_bazaar.scrapers.asiaxpat import AsiaXpatScraper
from hk_bazaar.scrapers.base import RawListing
from hk_bazaar.scrapers.carousell import CarousellScraper
from hk_bazaar.scrapers.facebook import FacebookMarketplaceScraper

_ACCESSORY = re.compile(
    r"\b(?:case|cover|charger|cable|adaptor|adapter|protector|tempered glass)\b|保護殼|手機殼|鋼化|螢幕貼|屏幕貼",
    re.IGNORECASE,
)

SCAN_MAX_PAGES = 10

_SOURCES: tuple[tuple[str, Platform, Callable[[], Any], dict[str, Any]], ...] = (
    ("asiaXPAT", Platform.ASIA_XPAT, AsiaXpatScraper, {"fetch_details": False}),
    ("Carousell", Platform.CAROUSELL, CarousellScraper, {}),
    ("Facebook", Platform.FACEBOOK_MARKETPLACE, FacebookMarketplaceScraper, {}),
)


@dataclass
class CheapIphone:
    source: str
    sku: str
    title: str
    price: float
    reference: float
    url: str


@dataclass
class SourceResult:
    source: str
    scraped: int = 0
    new: int = 0
    updated: int = 0
    cheap_iphones: int = 0
    pages: int | None = None
    caught_up: bool | None = None
    oldest: datetime | None = None
    status: str = "ok"
    note: str = ""
    hits: list[CheapIphone] = field(default_factory=list)


@dataclass
class ScanReport:
    query: str
    max_pages: int
    ran_at: str
    sources: list[SourceResult]

    @property
    def all_failed(self) -> bool:
        return bool(self.sources) and all(source.status == "error" for source in self.sources)


def is_cheap_iphone(listing: Listing) -> CheapIphone | None:
    """New-row check: iPhone SKU priced under its bluebook reference."""
    if listing.price is None or listing.price <= 0:
        return None
    if _ACCESSORY.search(listing.title or ""):
        return None
    valuation = value_listing(listing)
    if valuation is None or not valuation.sku.startswith("iphone_"):
        return None
    if valuation.listing_price >= valuation.reference_price:
        return None
    return CheapIphone(
        source=listing.platform.value,
        sku=valuation.sku,
        title=listing.title,
        price=valuation.listing_price,
        reference=valuation.reference_price,
        url=listing.url,
    )


def _existing_price(session: Session, raw: RawListing) -> tuple[bool, float | None]:
    existing = session.execute(
        select(Listing).where(Listing.platform == raw.platform, Listing.external_id == raw.external_id)
    ).scalar_one_or_none()
    if existing is None:
        return False, None
    return True, existing.price


def ingest_source(session: Session, source: str, raw_listings: list[RawListing]) -> SourceResult:
    result = SourceResult(source=source, scraped=len(raw_listings))
    posted = [raw.posted_at for raw in raw_listings if raw.posted_at is not None]
    if posted:
        result.oldest = min(posted)
    for raw in raw_listings:
        existed, old_price = _existing_price(session, raw)
        listing, is_new = upsert_listing(session, clean_listing(raw))
        price_moved = existed and old_price != listing.price
        if is_new:
            result.new += 1
        else:
            result.updated += 1
        if not is_new and not price_moved:
            continue
        hit = is_cheap_iphone(listing)
        if hit is None:
            continue
        hit.source = source
        result.hits.append(hit)
        result.cheap_iphones += 1
    session.commit()
    return result


def format_report(report: ScanReport) -> str:
    lines = [
        f"hk-bazaar scan {report.ran_at}",
        f"query: {report.query}",
        f"cap: {report.max_pages} pages",
        "order: newest first. Stops when a whole page is already stored, or at the cap.",
        "cheap_iphone: new row or a price change, iphone_* SKU, price under that SKU's bluebook reference",
        "",
        f"{'source':<16} {'scraped':>7} {'new':>5} {'updated':>7} {'cheap_iphones':>13} "
        f"{'pages':>5}  caught_up  oldest",
    ]
    for source in report.sources:
        pages = "-" if source.pages is None else str(source.pages)
        caught = "-" if source.caught_up is None else "yes" if source.caught_up else "no"
        oldest = source.oldest.date().isoformat() if source.oldest else "-"
        lines.append(
            f"{source.source:<16} {source.scraped:>7} {source.new:>5} {source.updated:>7} "
            f"{source.cheap_iphones:>13} {pages:>5}  {caught:<9}  {oldest}"
        )
        if source.note:
            lines.append(f"  {source.note}")
    hits = [hit for source in report.sources for hit in source.hits]
    lines.append("")
    lines.append(f"cheap iphones: {len(hits)}")
    for hit in hits:
        lines.append(
            f"- {hit.source} | HKD {hit.price:,.0f} | ref {hit.reference:,.0f} | {hit.sku} | {hit.title} | {hit.url}"
        )
    return "\n".join(lines) + "\n"


def write_report(text: str, *, when: datetime) -> None:
    folder = PROJECT_ROOT / "reports" / "scans"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{when.strftime('%Y%m%dT%H%M%S')}.txt").write_text(text, encoding="utf-8")
    (PROJECT_ROOT / "reports" / "latest-scan.txt").write_text(text, encoding="utf-8")


@contextmanager
def _open(factory: Callable[[], Any]) -> Iterator[Any]:
    scraper = factory()
    try:
        yield scraper
    finally:
        close = getattr(scraper, "close", None)
        if close is not None:
            close()


def _known_ids(session: Session, platform: Platform) -> set[str]:
    return set(session.scalars(select(Listing.external_id).where(Listing.platform == platform)).all())


def _facebook_block() -> SourceResult | None:
    settings = get_settings()
    if not settings.facebook_enabled:
        return SourceResult(source="Facebook", status="disabled", note="HK_BAZAAR_FACEBOOK_ENABLED is false")
    if not Path(settings.facebook_storage_state).exists():
        return SourceResult(
            source="Facebook",
            status="error",
            note=f"session file missing: {settings.facebook_storage_state}",
        )
    return None


def run_scan(
    session: Session,
    *,
    query: str = "iphone",
    max_pages: int = SCAN_MAX_PAGES,
    scrapers: list[tuple[str, Callable[[], Any], dict[str, Any]]] | None = None,
    write: bool = True,
    now: datetime | None = None,
) -> ScanReport:
    when = now or datetime.now().astimezone()
    results: list[SourceResult] = []
    chosen = scrapers
    if chosen is None:
        chosen = [(name, factory, extra) for name, _platform, factory, extra in _SOURCES]

    for name, factory, extra in chosen:
        if scrapers is None and name == "Facebook":
            blocked = _facebook_block()
            if blocked is not None:
                results.append(blocked)
                continue
        if scrapers is None:
            platform = next(item[1] for item in _SOURCES if item[0] == name)
            extra = {**extra, "known_ids": _known_ids(session, platform), "recent": True}
        try:
            with _open(factory) as scraper:
                raw = scraper.scrape(query=query, max_pages=max_pages, **extra)
                pages = getattr(scraper, "pages_fetched", None)
                caught_up = getattr(scraper, "caught_up", None)
                page_note = getattr(scraper, "page_note", "")
            result = ingest_source(session, name, raw)
            result.pages = pages
            result.caught_up = caught_up
            if page_note:
                result.note = page_note
            results.append(result)
        except Exception as exc:
            logger.exception("{} scan failed", name)
            results.append(SourceResult(source=name, status="error", note=str(exc)))

    report = ScanReport(query=query, max_pages=max_pages, ran_at=when.isoformat(timespec="seconds"), sources=results)
    if write:
        write_report(format_report(report), when=when)
    return report
