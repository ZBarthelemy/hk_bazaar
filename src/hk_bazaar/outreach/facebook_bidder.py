"""
Facebook Marketplace Messenger outreach — dry-run by default.

⚠️  Automating messages may violate Meta ToS. Use approval flow + rate limits.
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
    base = max(settings.request_delay_seconds, 5.0)
    time.sleep(base + random.uniform(2.0, 5.0))


def submit_facebook_message(
    attempt: OutreachAttempt,
    *,
    dry_run: bool | None = None,
) -> tuple[bool, str | None]:
    """
    Open listing and send a Messenger offer message.
    Returns (success, audit_path_or_error).
    """
    settings = get_settings()
    dry_run = settings.outreach_dry_run if dry_run is None else dry_run
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    if attempt.platform.value != "facebook_marketplace":
        return False, "Only Facebook Marketplace supports Messenger outreach in v1"

    if dry_run:
        logger.info(
            "[DRY RUN] Would message {} with HKD {:,.0f}\nMessage:\n{}",
            attempt.listing_url,
            attempt.proposed_bid,
            attempt.message,
        )
        audit_path = _AUDIT_DIR / f"facebook_dry_run_{attempt.id}.txt"
        audit_path.write_text(
            f"URL: {attempt.listing_url}\nBid: {attempt.proposed_bid}\n\n{attempt.message}",
            encoding="utf-8",
        )
        return True, str(audit_path)

    storage = settings.facebook_storage_state
    if not storage.exists():
        return False, f"Facebook session not found at {storage}. Log in via Playwright first."

    screenshot_path = str(_AUDIT_DIR / f"facebook_offer_{attempt.id}.png")

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

            message_btn = page.get_by_role("button", name="Message")
            if message_btn.count() == 0:
                message_btn = page.locator(
                    "div[role='button']:has-text('Message'), "
                    "a:has-text('Message'), "
                    "div[role='button']:has-text('傳送訊息')"
                )
            if message_btn.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Message button not found — open listing manually"

            message_btn.first.click(force=True)
            page.wait_for_timeout(2000)

            dialog = page.locator("[role='dialog']").last
            composer = dialog.locator("[contenteditable='true'], textarea")
            if composer.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Messenger composer not found"

            composer.last.click()
            composer.last.fill(attempt.message)
            page.wait_for_timeout(800)

            send_btn = dialog.get_by_role("button", name="Send message")
            if send_btn.count() == 0:
                send_btn = dialog.get_by_role("button", name="Send")
            if send_btn.count() == 0:
                send_btn = page.locator("div[aria-label='Send'], div[aria-label='傳送']")
            if send_btn.count() == 0:
                page.screenshot(path=screenshot_path)
                return False, "Send button not found — message drafted but not sent"

            send_btn.first.click()
            _polite_pause()
            page.screenshot(path=screenshot_path)
            logger.info("Sent Facebook message for attempt {}", attempt.id)
            return True, screenshot_path
        except Exception as exc:
            logger.exception("Facebook outreach failed")
            try:
                page.screenshot(path=screenshot_path)
            except Exception:
                pass
            return False, str(exc)
        finally:
            browser.close()