"""Carousell Hong Kong scraper — Playwright + HTML/JSON parsing."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus, urlencode, urljoin

from loguru import logger
from playwright.sync_api import Browser, Page, sync_playwright
from selectolax.parser import HTMLParser

from hk_bazaar.database.models import Platform
from hk_bazaar.scrapers.base import BaseScraper, RawListing
from hk_bazaar.scrapers.paging import PageWalk
from hk_bazaar.scrapers.parsers import clean_text, parse_price

# ---------------------------------------------------------------------------
# INTERNAL API NOTE (discovered via browser DevTools → Network):
#
# Carousell's web app often calls REST endpoints such as:
#   POST https://www.carousell.com.hk/api-service/search/products/v4/
#   GET  https://www.carousell.com.hk/api-service/product/{id}/
#
# Payloads include country_code="HK", query, filters (price, sort), and
# return structured listing JSON. These are undocumented, change without notice,
# and may require session cookies after Cloudflare challenge.
#
# To switch to API mode:
#   1. Open DevTools → Network while searching on carousell.com.hk
#   2. Copy the search request headers + JSON body
#   3. Replay with httpx using cookies from a Playwright storage_state export
#   4. Map response["data"]["results"] fields to RawListing
#
# This implementation uses Playwright to pass Cloudflare and parse __NEXT_DATA__
# or listing card HTML. Update selectors after inspecting live page.
# ---------------------------------------------------------------------------


class CarousellScraper(BaseScraper):
    platform = Platform.CAROUSELL

    def scrape(
        self,
        *,
        query: str | None = None,
        category_slug: str | None = None,
        max_price: float | None = None,
        max_pages: int = 3,
        known_ids: set[str] | None = None,
        recent: bool = False,
        **_: Any,
    ) -> list[RawListing]:
        base = self.settings.carousell_base_url
        if query:
            path = f"/search/{quote_plus(query)}"
        elif category_slug:
            path = category_slug if category_slug.startswith("/") else f"/{category_slug}"
        else:
            path = "/categories/home-living-20/"

        walk = PageWalk(known_ids)

        with sync_playwright() as pw:
            browser = self._launch_browser(pw)
            try:
                page = browser.new_page(user_agent=self.settings.user_agent)
                page.set_default_timeout(self.settings.playwright_timeout_ms)

                for page_num in range(1, max_pages + 1):
                    url = _page_url(urljoin(base, path), page_num=page_num, recent=recent)
                    logger.info("Carousell page {}/{}: {}", page_num, max_pages, url)
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)  # allow hydration / CF

                    batch = self._extract_listings(page, base_url=base)
                    if not batch:
                        logger.warning("No Carousell listings on page {}", page_num)
                        walk.add([])
                        break
                    if max_price is not None:
                        batch = [item for item in batch if item.price is None or item.price <= max_price]
                        if not batch:
                            self.polite_delay()
                            continue
                    if walk.add(batch):
                        break
                    self.polite_delay()
            finally:
                browser.close()

        self.pages_fetched = walk.pages_fetched
        self.caught_up = walk.caught_up
        self.page_note = walk.note
        logger.info("Carousell scraped {} listings", len(walk.listings))
        return walk.listings

    def _launch_browser(self, pw: Any) -> Browser:
        return pw.chromium.launch(headless=self.settings.playwright_headless)

    def _extract_listings(self, page: Page, *, base_url: str) -> list[RawListing]:
        html_text = page.content()
        from_next = parse_next_data(html_text, base_url=base_url)
        if from_next:
            return from_next
        return parse_listing_cards(html_text, base_url=base_url)


def parse_next_data(html_text: str, *, base_url: str) -> list[RawListing]:
    """Parse listings embedded in Next.js __NEXT_DATA__."""
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    if not match:
        return []

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    results: list[RawListing] = []
    _walk_for_listings(payload, base_url, results)
    return results


def _walk_for_listings(obj: Any, base_url: str, out: list[RawListing]) -> None:
    if isinstance(obj, dict):
        if _looks_like_listing(obj):
            parsed = _dict_to_listing(obj, base_url)
            if parsed:
                out.append(parsed)
        for v in obj.values():
            _walk_for_listings(v, base_url, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_listings(item, base_url, out)


def _seller_name(d: dict[str, Any]) -> str | None:
    seller = d.get("seller")
    if isinstance(seller, dict):
        return clean_text(str(seller.get("username", "")))
    return None


def _looks_like_listing(d: dict[str, Any]) -> bool:
    return "id" in d and ("title" in d or "name" in d) and (
        "price" in d or "price_formatted" in d or "currency_symbol" in d
    )


def _dict_to_listing(d: dict[str, Any], base_url: str) -> RawListing | None:
    external_id = str(d.get("id", ""))
    title = clean_text(d.get("title") or d.get("name"))
    if not external_id or not title:
        return None

    price_display = d.get("price_formatted") or d.get("price")
    if isinstance(price_display, (int, float)):
        price_display = f"HKD {price_display}"
    price, price_disp = parse_price(str(price_display) if price_display else None)

    slug = d.get("slug") or d.get("listing_url") or ""
    if slug and not slug.startswith("http"):
        url = urljoin(base_url, f"/p/{slug}" if not slug.startswith("/") else slug)
    else:
        url = urljoin(base_url, f"/p/{external_id}")

    images: list[str] = []
    for key in ("photos", "images", "thumbnail_url"):
        val = d.get(key)
        if isinstance(val, str) and val.startswith("http"):
            images.append(val)
        elif isinstance(val, list):
            for photo in val:
                if isinstance(photo, str) and photo.startswith("http"):
                    images.append(photo)
                elif isinstance(photo, dict):
                    u = photo.get("url") or photo.get("image_url")
                    if u:
                        images.append(str(u))

    location_raw = None
    loc = d.get("location") or d.get("marketplace")
    if isinstance(loc, dict):
        location_raw = clean_text(loc.get("name") or loc.get("address"))
    elif isinstance(loc, str):
        location_raw = clean_text(loc)

    return RawListing(
        platform=Platform.CAROUSELL,
        external_id=external_id,
        title=title,
        url=url,
        description=clean_text(d.get("description")),
        price=price,
        price_display=price_disp,
        location_raw=location_raw,
        category_raw=clean_text(str(d.get("category_name") or d.get("collection_name") or "")),
        condition=clean_text(str(d.get("condition") or "")),
        posted_at=_coerce_posted_at(d.get("time_created") or d.get("created_at")),
        image_urls=images,
        seller_name=_seller_name(d),
        extra={"source": "next_data"},
    )


def _page_url(url: str, *, page_num: int, recent: bool) -> str:
    """`sort_by=3` is Carousell's recent sort (newest listed first)."""
    params: dict[str, str] = {}
    if recent:
        params["sort_by"] = "3"
    if page_num > 1:
        params["page"] = str(page_num)
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode(params)}"


def _coerce_posted_at(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("seconds") or value.get("low")
        if isinstance(value, dict):
            value = value.get("low")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    if value > 10_000_000_000:
        value = value / 1000
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def parse_listing_cards(html_text: str, *, base_url: str) -> list[RawListing]:
    """Fallback: parse listing links from rendered HTML cards."""
    tree = HTMLParser(html_text)
    results: list[RawListing] = []
    seen: set[str] = set()

    # Update selectors after inspecting live page — sites change frequently
    for link in tree.css('a[href*="/p/"], a[href*="/products/"]'):
        href = link.attributes.get("href", "")
        match = re.search(r"/(?:p|products)/([^/?#]+)", href)
        if not match:
            continue
        slug = match.group(1)
        if slug in seen:
            continue
        seen.add(slug)

        title = clean_text(link.text()) or slug.replace("-", " ")
        price_display = None
        parent = link.parent
        for _ in range(4):
            if parent is None:
                break
            for el in parent.css("span, p"):
                text = clean_text(el.text()) or ""
                if re.search(r"HK\$|\$|HKD|免費|Free", text, re.I):
                    price_display = text
                    break
            if price_display:
                break
            parent = parent.parent

        price, price_disp = parse_price(price_display)
        url = href if href.startswith("http") else urljoin(base_url, href)

        results.append(
            RawListing(
                platform=Platform.CAROUSELL,
                external_id=slug,
                title=title,
                url=url,
                price=price,
                price_display=price_disp,
                extra={"source": "html_card"},
            )
        )

    return results