"""asiaXPAT listing message — dry-run by default."""

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
    base = max(settings.request_delay_seconds, 2.0)
    time.sleep(base + random.uniform(0.5, 1.5))


def submit_asiaxpat_message(
    attempt: OutreachAttempt,
    *,
    dry_run: bool | None = None,
) -> tuple[bool, str | None]:
    """Fill the listing's Message seller box and submit it."""
    settings = get_settings()
    dry_run = settings.outreach_dry_run if dry_run is None else dry_run
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    if attempt.platform.value != "asia_xpat":
        return False, "Only asiaXPAT uses the classifieds message form"

    if dry_run:
        logger.info(
            "[DRY RUN] Would message {} with HKD {:,.0f}\nMessage:\n{}",
            attempt.listing_url,
            attempt.proposed_bid,
            attempt.message,
        )
        audit_path = _AUDIT_DIR / f"asiaxpat_dry_run_{attempt.id}.txt"
        audit_path.write_text(
            f"URL: {attempt.listing_url}\nBid: {attempt.proposed_bid}\n\n{attempt.message}",
            encoding="utf-8",
        )
        return True, str(audit_path)

    storage = settings.asiaxpat_storage_state
    if not storage.exists():
        return False, f"asiaXPAT session not found at {storage}. Log in via Playwright first."

    screenshot_path = str(_AUDIT_DIR / f"asiaxpat_offer_{attempt.id}.png")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=settings.playwright_headless)
        try:
            context = browser.new_context(
                storage_state=str(storage),
                user_agent=settings.user_agent,
                locale="en-HK",
                viewport={"width": 1280, "height": 1400},
            )
            page = context.new_page()
            page.set_default_timeout(settings.playwright_timeout_ms)
            page.goto(attempt.listing_url, wait_until="domcontentloaded")
            _polite_pause()

            box = page.locator("textarea[name='message[body]']:visible")
            if box.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Message box not found — member login may have expired"

            box.first.fill(attempt.message)
            send = page.get_by_role("button", name="Message seller")
            if send.count() == 0:
                send = page.locator("text=Message seller")
            if send.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Message seller button not found"

            send.first.click()
            page.wait_for_timeout(2500)
            page.screenshot(path=screenshot_path)
            if "sign_in" in page.url:
                return False, "asiaXPAT asked to sign in again"
            logger.info("Sent asiaXPAT message for attempt {}", attempt.id)
            return True, screenshot_path
        except Exception as exc:
            logger.exception("asiaXPAT outreach failed")
            return False, str(exc)
        finally:
            browser.close()
