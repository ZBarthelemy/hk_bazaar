"""
Carousell Make Offer automation — dry-run by default.

⚠️  Automating offers may violate Carousell ToS. Use approval flow + rate limits.
Selectors change frequently — expect maintenance.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from loguru import logger
from playwright.sync_api import sync_playwright

from hk_bazaar.config import get_settings
from hk_bazaar.database.models import OutreachAttempt

_AUDIT_DIR = Path("data/outreach_audit")


def _polite_pause() -> None:
    settings = get_settings()
    base = max(settings.request_delay_seconds, 3.0)
    time.sleep(base + random.uniform(1.0, 3.0))


def submit_carousell_offer(
    attempt: OutreachAttempt,
    *,
    dry_run: bool | None = None,
) -> tuple[bool, str | None]:
    """
    Navigate to listing and submit Make Offer with proposed_bid.
    Returns (success, screenshot_path_or_error).
    """
    settings = get_settings()
    dry_run = settings.outreach_dry_run if dry_run is None else dry_run
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    if attempt.platform.value != "carousell":
        return False, "Only Carousell supports Make Offer automation in v1"

    if dry_run:
        logger.info(
            "[DRY RUN] Would open {} and offer HKD {:,.0f}\nMessage:\n{}",
            attempt.listing_url,
            attempt.proposed_bid,
            attempt.message,
        )
        audit_path = _AUDIT_DIR / f"dry_run_{attempt.id}.txt"
        audit_path.write_text(
            f"URL: {attempt.listing_url}\nBid: {attempt.proposed_bid}\n\n{attempt.message}",
            encoding="utf-8",
        )
        return True, str(audit_path)

    storage = settings.carousell_storage_state
    if not storage.exists():
        return False, f"Carousell session not found at {storage}. Log in via Playwright first."

    screenshot_path = str(_AUDIT_DIR / f"offer_{attempt.id}.png")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=settings.playwright_headless)
        try:
            context = browser.new_context(
                storage_state=str(storage),
                user_agent=settings.user_agent,
            )
            page = context.new_page()
            page.set_default_timeout(settings.playwright_timeout_ms)
            page.goto(attempt.listing_url, wait_until="domcontentloaded")
            _polite_pause()

            # Selectors are best-effort — update after inspecting live Carousell UI.
            make_offer = page.get_by_role("button", name="Make Offer")
            if make_offer.count() == 0:
                make_offer = page.locator("button:has-text('Make Offer'), button:has-text('出價')")
            if make_offer.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Make Offer button not found — chat fallback required"

            make_offer.first.click()
            page.wait_for_timeout(1500)

            price_input = page.locator(
                "input[type='number'], input[name*='price'], input[placeholder*='HK']"
            )
            if price_input.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Offer price input not found"

            price_input.first.fill(str(int(attempt.proposed_bid)))
            page.wait_for_timeout(800)

            submit = page.get_by_role("button", name="Submit")
            if submit.count() == 0:
                submit = page.locator("button:has-text('Submit'), button:has-text('送出')")
            submit.first.click()
            _polite_pause()

            page.screenshot(path=screenshot_path)
            logger.info("Submitted Carousell offer HKD {:,.0f} for attempt {}", attempt.proposed_bid, attempt.id)
            return True, screenshot_path
        except Exception as exc:
            logger.exception("Carousell offer failed")
            return False, str(exc)
        finally:
            browser.close()