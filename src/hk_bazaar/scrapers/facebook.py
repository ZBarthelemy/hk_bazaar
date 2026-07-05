"""
Facebook Marketplace scraper — OPTIONAL, HIGH RISK.

⚠️  READ BEFORE ENABLING (HK_BAZAAR_FACEBOOK_ENABLED=true):

1. TERMS OF SERVICE: Automated scraping of Facebook Marketplace violates Meta's
   Terms of Service. This can result in account restrictions, CAPTCHAs, or permanent bans.

2. NO OFFICIAL READ API: Meta's Marketplace Partner Item API is for *uploading*
   partner inventory, not reading consumer listings.

3. LOGIN REQUIRED: Marketplace browsing requires an authenticated Facebook session.
   Treat session files as secrets; never commit them.

4. RATE LIMITING: Aggressive scraping triggers automated defences. Use long delays
   (5–15s), low volume, and personal-use-only schedules.

5. LEGAL: Personal research only. Do not resell data or build commercial products.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from loguru import logger
from playwright.sync_api import Page, sync_playwright

from hk_bazaar.database.models import Platform
from hk_bazaar.scrapers.base import BaseScraper, RawListing
from hk_bazaar.scrapers.parsers import clean_text, parse_price
from hk_bazaar.utils.hk_locations import normalize_location

# UI badges on feed cards — not title/price/location.
_BADGE_LINES = frozenset({
    "just listed",
    "price drop",
    "price lowered",
    "pending",
    "sold",
    "available",
    "in stock",
    "featured",
    "today's picks",
    "new",
})

_LOCATION_MARKERS = (
    "hong kong",
    "kowloon",
    "new territories",
    "outlying islands",
    "香港",
    "九龍",
    "新界",
)

_ITEM_LINK_SELECTOR = 'a[href*="/marketplace/item/"]'

_EXTRACT_CARDS_JS = """
() => {
  const seen = new Set();
  const results = [];
  for (const anchor of document.querySelectorAll('a[href*="/marketplace/item/"]')) {
    const href = anchor.getAttribute('href') || '';
    const id = href.split('/marketplace/item/')[1]?.split('/')[0]?.split('?')[0];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const spans = [...anchor.querySelectorAll('span')]
      .map((node) => (node.innerText || '').trim())
      .filter((text) => text.length > 0);
    results.push({
      id,
      href: anchor.href || href,
      spans,
      text: (anchor.innerText || '').trim(),
    });
  }
  return results;
}
"""


def _dedupe_lines(lines: list[str]) -> list[str]:
    """Facebook repeats the same span text multiple times per card."""
    seen: list[str] = []
    for line in lines:
        if line not in seen:
            seen.append(line)
    return seen


def _is_badge_line(line: str) -> bool:
    return line.strip().lower() in _BADGE_LINES


def _looks_like_price_line(line: str) -> bool:
    """Avoid treating product titles with years/model numbers (e.g. '2007 GSXR 600') as prices."""
    if re.search(r"HK\$|\$|HKD|港幣|元", line, re.I):
        return True
    lower = line.lower()
    return lower in {"free", "免費"} or any(kw in lower for kw in ("negotiable", "obo", "ono", "面議"))


def _looks_like_location(line: str) -> bool:
    cleaned = clean_text(line)
    if not cleaned:
        return False
    lower = cleaned.lower()
    if any(marker in lower for marker in _LOCATION_MARKERS):
        return True
    if lower.startswith("hong k"):
        return True
    _, district, _ = normalize_location(cleaned)
    return district is not None


def _pick_title(lines: list[str]) -> str | None:
    """Title is the first line after price that is not a badge, price, or location."""
    for line in lines:
        if _looks_like_location(line) or _looks_like_price_line(line) or _is_badge_line(line):
            continue
        return line
    return None


def parse_facebook_card(*, external_id: str, url: str, text: str, spans: list[str] | None = None) -> RawListing:
    """
    Parse a Marketplace feed card into structured fields.

    Facebook cards commonly render as:
      [badge?] / price / title / location
    but inner_text often merges them into one blob — we split and classify lines.
    """
    raw_lines = spans if spans else text.splitlines()
    lines = _dedupe_lines([clean_text(line) for line in raw_lines if clean_text(line)])
    lines = [line for line in lines if not _is_badge_line(line)]

    price: float | None = None
    price_display: str | None = None
    price_idx: int | None = None

    for idx, line in enumerate(lines):
        if _looks_like_price_line(line):
            price, price_display = parse_price(line)
            price_idx = idx
            break

    location_raw: str | None = None
    title: str | None = None

    if price_idx is not None:
        after_price = lines[price_idx + 1 :]
        if after_price:
            if _looks_like_location(after_price[-1]):
                location_raw = after_price[-1]
                title = _pick_title(after_price[:-1])
            else:
                title = _pick_title(after_price)
    else:
        # No explicit price line — pick title from remaining content.
        if lines:
            if _looks_like_location(lines[-1]) and len(lines) > 1:
                location_raw = lines[-1]
                title = _pick_title(lines[:-1])
            else:
                title = _pick_title(lines)

    if not title:
        title = f"FB item {external_id}"

    return RawListing(
        platform=Platform.FACEBOOK_MARKETPLACE,
        external_id=external_id,
        title=title,
        url=url,
        price=price,
        price_display=price_display,
        location_raw=location_raw,
    )


class FacebookMarketplaceScraper(BaseScraper):
    platform = Platform.FACEBOOK_MARKETPLACE

    def scrape(self, *, query: str | None = None, max_pages: int = 1, **_: Any) -> list[RawListing]:
        if not self.settings.facebook_enabled:
            logger.warning(
                "Facebook Marketplace scraping is DISABLED. "
                "Set HK_BAZAAR_FACEBOOK_ENABLED=true only after reading scrapers/facebook.py warnings."
            )
            return []

        storage = self.settings.facebook_storage_state
        if not storage.exists():
            raise FileNotFoundError(
                f"Facebook session not found at {storage}. "
                "Export Playwright storage_state after manual login — see docs/PLATFORMS.md"
            )

        logger.warning(
            "Facebook scrape starting — account ban risk is REAL. "
            "Use low frequency and personal-use only."
        )

        base = self.settings.facebook_marketplace_url.rstrip("/") + "/"
        search_url = base if not query else f"{base}search/?query={quote_plus(query)}"

        listings: list[RawListing] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.settings.playwright_headless)
            try:
                context = browser.new_context(
                    storage_state=str(storage),
                    user_agent=self.settings.user_agent,
                )
                page = context.new_page()
                page.set_default_timeout(self.settings.playwright_timeout_ms)

                logger.info("Facebook Marketplace: {} (max_pages={})", search_url, max_pages)
                page.goto(search_url, wait_until="domcontentloaded")
                page.wait_for_selector(_ITEM_LINK_SELECTOR, timeout=self.settings.playwright_timeout_ms)
                page.wait_for_timeout(2000)

                for page_num in range(1, max(1, max_pages) + 1):
                    batch = self._extract_listings(page)
                    new_count = 0
                    for item in batch:
                        if item.external_id in seen_ids:
                            continue
                        seen_ids.add(item.external_id)
                        item.extra["query"] = query
                        item.extra["feed_page"] = page_num
                        listings.append(item)
                        new_count += 1

                    logger.info(
                        "Facebook feed page {}/{}: {} cards, {} new ({} total)",
                        page_num,
                        max_pages,
                        len(batch),
                        new_count,
                        len(listings),
                    )

                    if page_num >= max_pages:
                        break
                    if not self._scroll_for_more(page):
                        logger.info("Facebook feed: no more listings after scroll — stopping early")
                        break
                    self.polite_delay()

            finally:
                browser.close()

        logger.info("Facebook Marketplace returned {} listings", len(listings))
        return listings

    def _extract_listings(self, page: Page) -> list[RawListing]:
        cards = page.evaluate(_EXTRACT_CARDS_JS)
        listings: list[RawListing] = []
        for card in cards:
            href = card.get("href") or ""
            external_id = card.get("id") or ""
            if not external_id:
                continue
            url = href if href.startswith("http") else f"https://www.facebook.com{href}"
            listings.append(
                parse_facebook_card(
                    external_id=external_id,
                    url=url,
                    text=card.get("text") or "",
                    spans=card.get("spans") or [],
                )
            )
        return listings

    def _scroll_for_more(self, page: Page) -> bool:
        """Scroll the infinite feed; return True if new listing links appeared."""
        before = page.locator(_ITEM_LINK_SELECTOR).count()
        page.evaluate("window.scrollBy(0, window.innerHeight * 2.5)")
        for _ in range(12):
            page.wait_for_timeout(500)
            if page.locator(_ITEM_LINK_SELECTOR).count() > before:
                page.wait_for_timeout(1000)
                return True

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        return page.locator(_ITEM_LINK_SELECTOR).count() > before