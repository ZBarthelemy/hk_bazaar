"""asiaXPAT classifieds scraper — public HTML, no login required."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from selectolax.parser import HTMLParser, Node

from hk_bazaar.database.models import Platform
from hk_bazaar.scrapers.base import BaseScraper, RawListing
from hk_bazaar.scrapers.parsers import (
    absolutize_url,
    clean_text,
    extract_json_ld_products,
    parse_price,
)


class AsiaXpatScraper(BaseScraper):
    """
    Scrape https://hongkong.asiaxpat.com/classifieds

    Index pages are server-rendered Rails/Turbo cards.
    Detail pages expose schema.org Product JSON-LD — preferred for full data.
    Update selectors after inspecting live page — sites change frequently.
    """

    platform = Platform.ASIA_XPAT

    def scrape(self, *, max_pages: int = 5, fetch_details: bool = True, **_: Any) -> list[RawListing]:
        base = self.settings.asiaxpat_base_url
        seen_ids: set[str] = set()
        listings: list[RawListing] = []

        for page in range(1, max_pages + 1):
            url = f"{base}/classifieds" if page == 1 else f"{base}/classifieds?page={page}"
            logger.info("asiaXPAT index page {}/{}: {}", page, max_pages, url)
            html_text = self.fetch(url)
            page_listings = parse_index_page(html_text, base_url=base)

            if not page_listings:
                logger.warning("No listings on page {}, stopping", page)
                break

            for stub in page_listings:
                if stub.external_id in seen_ids:
                    continue
                seen_ids.add(stub.external_id)

                if fetch_details:
                    self.polite_delay()
                    detail_url = stub.url
                    try:
                        detail_html = self.fetch(detail_url)
                        stub = enrich_from_detail(stub, detail_html, base_url=base)
                    except Exception as exc:
                        logger.warning("Detail fetch failed for {}: {}", detail_url, exc)

                listings.append(stub)
                self.polite_delay()

            self.polite_delay()

        logger.info("asiaXPAT scraped {} listings", len(listings))
        return listings


def parse_index_page(html_text: str, *, base_url: str) -> list[RawListing]:
    """Parse listing cards from an index page."""
    tree = HTMLParser(html_text)
    stubs: list[RawListing] = []
    seen: set[str] = set()

    # Primary: photo-carousel data attribute marks real listing cards
    for node in tree.css("[data-photo-carousel-url-value]"):
        path = node.attributes.get("data-photo-carousel-url-value", "")
        match = re.search(r"/classifieds/(\d+)", path)
        if not match:
            continue
        external_id = match.group(1)
        if external_id in seen:
            continue
        seen.add(external_id)

        card = _card_for_listing(tree, external_id) or node
        stub = _parse_card_stub(card, external_id, base_url)
        if stub:
            stubs.append(stub)

    # Fallback: any classifieds links not yet captured
    for link in tree.css('a[href^="/classifieds/"]'):
        href = link.attributes.get("href", "")
        match = re.search(r"/classifieds/(\d+)$", href)
        if not match:
            continue
        external_id = match.group(1)
        if external_id in seen:
            continue
        seen.add(external_id)
        stub = _parse_card_stub(link, external_id, base_url)
        if stub:
            stubs.append(stub)

    return stubs


def _card_for_listing(tree: HTMLParser, external_id: str) -> Node | None:
    """Find the tightest DOM node for a single listing card."""
    href = f"/classifieds/{external_id}"
    for link in tree.css(f'a[href="{href}"]'):
        current: Node | None = link
        for _ in range(6):
            if current is None:
                break
            # Return the smallest subtree that still contains exactly one title
            if len(current.css("h2")) == 1:
                return current
            current = current.parent
        return link
    return None


def _parse_card_stub(node: Node, external_id: str, base_url: str) -> RawListing | None:
    title = None
    for h in node.css("h2"):
        title = clean_text(h.text())
        if title:
            break
    if not title:
        return None

    category_raw = None
    for span in node.css("span, p, div"):
        text = clean_text(span.text())
        if text and text in {
            "Electronics", "Furniture", "Home goods", "Clothing",
            "Books & media", "Toys & games", "Appliances",
            "Sports & outdoors", "Other",
        }:
            category_raw = text
            break

    price_display = None
    for el in node.css("span, p, div"):
        text = clean_text(el.text()) or ""
        if re.search(r"^(HKD|Free)\b", text, re.I) or text.lower() == "free":
            price_display = text
            break

    description = None
    for p in node.css("p"):
        text = clean_text(p.text())
        if text and text != title and len(text) > 20:
            description = text
            break

    image_urls: list[str] = []
    for img in node.css("img"):
        src = img.attributes.get("src")
        full = absolutize_url(base_url, src)
        if full and full not in image_urls:
            image_urls.append(full)

    price, price_disp = parse_price(price_display)

    return RawListing(
        platform=Platform.ASIA_XPAT,
        external_id=external_id,
        title=title,
        url=f"{base_url}/classifieds/{external_id}",
        description=description,
        price=price,
        price_display=price_disp or price_display,
        category_raw=category_raw,
        image_urls=image_urls,
        extra={"source": "index_card"},
    )


def enrich_from_detail(stub: RawListing, html_text: str, *, base_url: str) -> RawListing:
    """Enrich stub with JSON-LD Product and page content."""
    products = extract_json_ld_products(html_text)
    if products:
        product = products[0]
        stub.title = clean_text(product.get("name")) or stub.title
        stub.description = clean_text(product.get("description")) or stub.description
        stub.category_raw = product.get("category") or stub.category_raw

        offers = product.get("offers") or {}
        if isinstance(offers, dict):
            price_val = offers.get("price")
            currency = offers.get("priceCurrency", "HKD")
            if price_val is not None:
                stub.price = float(price_val)
                stub.price_display = f"{currency} {price_val}"

        image = product.get("image")
        if image:
            if isinstance(image, list):
                stub.image_urls = [
                    u for u in (absolutize_url(base_url, i) for i in image) if u
                ]
            else:
                full = absolutize_url(base_url, str(image))
                if full:
                    stub.image_urls = [full]

    tree = HTMLParser(html_text)
    # Update selectors after inspecting live page — sites change frequently
    for img in tree.css("img[src*='active_storage']"):
        src = img.attributes.get("src")
        full = absolutize_url(base_url, src)
        if full and full not in stub.image_urls:
            stub.image_urls.append(full)

    if not stub.description:
        meta = tree.css_first('meta[name="description"]')
        if meta:
            stub.description = clean_text(meta.attributes.get("content"))

    stub.extra["source"] = "detail_page"
    return stub