"""Platform-specific outreach templates and send routing."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from hk_bazaar.database.models import Platform

_TEMPLATE_BY_PLATFORM: dict[str, str] = {
    Platform.CAROUSELL.value: "offer_carousell.txt.j2",
    Platform.FACEBOOK_MARKETPLACE.value: "offer_facebook.txt.j2",
    Platform.ASIA_XPAT.value: "offer_default.txt.j2",
}

_AUDIT_DIR = Path("data/outreach_audit")


def template_for_platform(platform: str) -> str:
    return _TEMPLATE_BY_PLATFORM.get(platform, "offer_default.txt.j2")


def _write_message_audit(attempt, *, prefix: str) -> tuple[bool, str]:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = _AUDIT_DIR / f"{prefix}_{attempt.id}.txt"
    audit_path.write_text(
        f"Platform: {attempt.platform.value}\n"
        f"URL: {attempt.listing_url}\n"
        f"Bid: {attempt.proposed_bid}\n\n"
        f"{attempt.message}",
        encoding="utf-8",
    )
    logger.info(
        "[MESSAGE ONLY] {} outreach #{} logged to {}",
        attempt.platform.value,
        attempt.id,
        audit_path,
    )
    return True, str(audit_path)


def submit_outreach(
    attempt,
    *,
    dry_run: bool | None = None,
) -> tuple[bool, str | None]:
    """Route outreach to the platform-specific sender."""
    from hk_bazaar.outreach.carousell_bidder import submit_carousell_offer
    from hk_bazaar.outreach.facebook_bidder import submit_facebook_message

    platform = attempt.platform.value
    if platform == Platform.CAROUSELL.value:
        return submit_carousell_offer(attempt, dry_run=dry_run)
    if platform == Platform.FACEBOOK_MARKETPLACE.value:
        return submit_facebook_message(attempt, dry_run=dry_run)
    return _write_message_audit(attempt, prefix="message_only")