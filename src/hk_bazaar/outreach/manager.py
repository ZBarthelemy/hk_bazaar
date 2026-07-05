"""Outreach orchestration — qualify, queue, approve, send."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from hk_bazaar.config import Settings, get_settings
from hk_bazaar.database.models import Listing, OutreachStatus
from hk_bazaar.database.outreach_crud import (
    approve_outreach,
    count_outreaches_since,
    create_outreach_attempt,
    get_outreach_attempt,
    mark_outreach_failed,
    mark_outreach_sent,
    outreach_already_queued,
    seller_in_cooldown,
)
from hk_bazaar.outreach.bidding import calculate_proposed_bid, render_offer_message
from hk_bazaar.outreach.notifier import notify_outreach
from hk_bazaar.outreach.platform_outreach import submit_outreach, template_for_platform
from hk_bazaar.outreach.qualification import qualify_listing


class OutreachManager:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def _within_daily_limit(self) -> bool:
        since = datetime.now(UTC) - timedelta(days=1)
        return count_outreaches_since(self.session, since) < self.settings.outreach_max_daily

    def _platform_allowed(self, platform: str) -> bool:
        raw = self.settings.outreach_platforms.strip().lower()
        if not raw or raw in {"all", "*"}:
            return True
        allowed = {p.strip() for p in self.settings.outreach_platforms.split(",") if p.strip()}
        return platform in allowed

    def scan_listings(
        self,
        listings: list[Listing],
        *,
        dry_run: bool | None = None,
        notify: bool = True,
    ) -> list[int]:
        """Scan listings, queue outreach for qualified deals. Returns new attempt IDs."""
        dry_run = self.settings.outreach_dry_run if dry_run is None else dry_run
        created_ids: list[int] = []

        if not dry_run and not self._within_daily_limit():
            logger.warning("Daily outreach limit reached ({})", self.settings.outreach_max_daily)
            return created_ids

        for listing in listings:
            if listing.external_id.startswith("seed-"):
                continue
            if not self._platform_allowed(listing.platform.value):
                continue
            if outreach_already_queued(self.session, listing.id):
                continue
            if seller_in_cooldown(
                self.session,
                listing.seller_external_id,
                cooldown_days=self.settings.outreach_cooldown_days,
            ):
                logger.debug("Seller cooldown active for listing {}", listing.id)
                continue

            deal = qualify_listing(listing)
            if deal is None:
                continue

            proposed_bid = calculate_proposed_bid(deal.buy_target)
            message = render_offer_message(
                deal,
                proposed_bid,
                template_name=template_for_platform(listing.platform.value),
            )

            attempt = create_outreach_attempt(
                self.session,
                listing=listing,
                sku=deal.match.sku,
                listing_price=deal.listing_price,
                buy_target=deal.buy_target,
                proposed_bid=float(proposed_bid),
                message=message,
                qualification_reasons=deal.reasons,
                dry_run=dry_run,
            )
            created_ids.append(attempt.id)
            logger.info(
                "Queued outreach #{} {} @ HKD {:,.0f} → bid HKD {:,.0f}",
                attempt.id,
                deal.match.sku,
                deal.listing_price,
                proposed_bid,
            )
            if notify:
                notify_outreach(attempt)

            if not dry_run and not self._within_daily_limit():
                break

        self.session.commit()
        return created_ids

    def watch_new_listings(self, *, dry_run: bool | None = None) -> list[int]:
        """Check all active listings scraped within deal_recent_days for outreach."""
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.deal_recent_days)
        stmt = (
            select(Listing)
            .where(Listing.is_active.is_(True), Listing.scraped_at >= cutoff)
            .order_by(Listing.scraped_at.desc())
        )
        listings = list(self.session.execute(stmt).scalars().all())
        return self.scan_listings(listings, dry_run=dry_run)

    def approve_and_send(self, attempt_id: int, *, proposed_bid: float | None = None) -> OutreachAttempt:
        attempt = get_outreach_attempt(self.session, attempt_id)
        if attempt is None:
            raise ValueError(f"Outreach attempt {attempt_id} not found")
        if attempt.status not in {OutreachStatus.PENDING, OutreachStatus.DRY_RUN}:
            raise ValueError(f"Attempt {attempt_id} is not pending (status={attempt.status})")

        if self.settings.outreach_auto_approve:
            logger.warning("AUTO_APPROVE is enabled — use with extreme caution")

        approve_outreach(self.session, attempt, proposed_bid=proposed_bid)

        ok, detail = submit_outreach(attempt, dry_run=self.settings.outreach_dry_run)

        if ok and not self.settings.outreach_dry_run:
            mark_outreach_sent(self.session, attempt, screenshot_path=detail if detail and detail.endswith(".png") else None)
        elif ok:
            attempt.status = OutreachStatus.DRY_RUN
        else:
            mark_outreach_failed(self.session, attempt, detail or "unknown error")

        self.session.commit()
        return attempt

    def simulate_bid(self, listing: Listing) -> dict[str, object]:
        deal = qualify_listing(listing)
        if deal is None:
            return {"qualified": False, "reason": "Does not meet buy_target + urgency rules"}
        proposed_bid = calculate_proposed_bid(deal.buy_target)
        message = render_offer_message(
            deal,
            proposed_bid,
            template_name=template_for_platform(listing.platform.value),
        )
        return {
            "qualified": True,
            "sku": deal.match.sku,
            "display_name": deal.match.item.display_name,
            "listing_price": deal.listing_price,
            "buy_target": deal.buy_target,
            "proposed_bid": proposed_bid,
            "reasons": deal.reasons,
            "message": message,
        }