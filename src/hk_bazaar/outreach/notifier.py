"""Telegram and console notifications for outreach approval."""

from __future__ import annotations

import httpx
from loguru import logger
from rich.console import Console
from rich.panel import Panel

from hk_bazaar.config import Settings, get_settings
from hk_bazaar.database.models import OutreachAttempt

console = Console()


def format_outreach_notification(attempt: OutreachAttempt) -> str:
    reasons = "\n".join(f"  • {r}" for r in attempt.qualification_reasons)
    return (
        f"Outreach #{attempt.id} — {attempt.sku}\n"
        f"Title: {attempt.listing_title[:80]}\n"
        f"Platform: {attempt.platform.value}\n"
        f"Listing: HKD {attempt.listing_price:,.0f} | buy_target: HKD {attempt.buy_target:,.0f}\n"
        f"Proposed bid: HKD {attempt.proposed_bid:,.0f}\n"
        f"Why qualified:\n{reasons}\n"
        f"URL: {attempt.listing_url}\n\n"
        f"Suggested message:\n{attempt.message}\n\n"
        f"Approve: hk-bazaar approve-outreach {attempt.id}"
    )


def notify_console(attempt: OutreachAttempt) -> None:
    console.print(Panel(format_outreach_notification(attempt), title="Outreach opportunity", border_style="green"))


def notify_telegram(attempt: OutreachAttempt, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        logger.debug("Telegram not configured — skipping")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": format_outreach_notification(attempt),
        "disable_web_page_preview": False,
    }
    try:
        response = httpx.post(url, json=payload, timeout=15.0)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Telegram notification failed: {}", exc)
        return False


def notify_outreach(attempt: OutreachAttempt) -> None:
    notify_console(attempt)
    notify_telegram(attempt)