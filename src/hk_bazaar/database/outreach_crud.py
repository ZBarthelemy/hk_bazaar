"""CRUD for outreach attempts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hk_bazaar.database.models import Listing, OutreachAttempt, OutreachStatus, Platform


def create_outreach_attempt(
    session: Session,
    *,
    listing: Listing,
    sku: str,
    listing_price: float,
    buy_target: float,
    proposed_bid: float,
    message: str,
    qualification_reasons: list[str],
    dry_run: bool,
) -> OutreachAttempt:
    attempt = OutreachAttempt(
        listing_id=listing.id,
        platform=listing.platform,
        sku=sku,
        listing_price=listing_price,
        buy_target=buy_target,
        proposed_bid=proposed_bid,
        message=message,
        qualification_reasons=qualification_reasons,
        seller_external_id=listing.seller_external_id,
        listing_url=listing.url,
        listing_title=listing.title,
        dry_run=dry_run,
        status=OutreachStatus.DRY_RUN if dry_run else OutreachStatus.PENDING,
    )
    session.add(attempt)
    session.flush()
    return attempt


def get_outreach_attempt(session: Session, attempt_id: int) -> OutreachAttempt | None:
    return session.get(OutreachAttempt, attempt_id)


ACTIONABLE_OUTREACH_STATUSES = (OutreachStatus.PENDING, OutreachStatus.DRY_RUN)

ELECTRONICS_FAMILIES = frozenset({"phone", "laptop", "tablet", "gaming", "appliance"})


def _skus_for_families(families: frozenset[str] | set[str]) -> list[str]:
    from hk_bazaar.outreach.catalog import load_outreach_catalog

    catalog = load_outreach_catalog()
    return [sku for sku, item in catalog.items() if item.family in families]


def list_outreach_attempts(
    session: Session,
    *,
    statuses: tuple[OutreachStatus, ...] | None = None,
    platform: Platform | None = None,
    category: str | None = None,
    families: frozenset[str] | set[str] | None = None,
    limit: int = 50,
) -> list[OutreachAttempt]:
    statuses = statuses or ACTIONABLE_OUTREACH_STATUSES
    stmt = select(OutreachAttempt).where(OutreachAttempt.status.in_(statuses))
    if platform is not None:
        stmt = stmt.where(OutreachAttempt.platform == platform)
    if category:
        stmt = stmt.join(Listing, OutreachAttempt.listing_id == Listing.id).where(
            Listing.category.ilike(f"%{category}%")
        )
    if families:
        skus = _skus_for_families(families)
        if not skus:
            return []
        stmt = stmt.where(OutreachAttempt.sku.in_(skus))
    stmt = stmt.order_by(OutreachAttempt.created_at.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def list_pending_outreaches(session: Session, *, limit: int = 50) -> list[OutreachAttempt]:
    return list_outreach_attempts(session, limit=limit)


def outreach_already_queued(session: Session, listing_id: int) -> bool:
    stmt = select(OutreachAttempt.id).where(
        OutreachAttempt.listing_id == listing_id,
        OutreachAttempt.status.in_(
            [OutreachStatus.PENDING, OutreachStatus.APPROVED, OutreachStatus.SENT, OutreachStatus.DRY_RUN]
        ),
    )
    return session.execute(stmt).first() is not None


def count_outreaches_since(session: Session, since: datetime) -> int:
    stmt = select(func.count()).select_from(OutreachAttempt).where(
        OutreachAttempt.created_at >= since,
        OutreachAttempt.status.in_(
            [OutreachStatus.PENDING, OutreachStatus.APPROVED, OutreachStatus.SENT]
        ),
    )
    return int(session.execute(stmt).scalar_one())


def seller_in_cooldown(
    session: Session,
    seller_external_id: str | None,
    *,
    cooldown_days: int,
) -> bool:
    if not seller_external_id:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=cooldown_days)
    stmt = select(OutreachAttempt.id).where(
        OutreachAttempt.seller_external_id == seller_external_id,
        OutreachAttempt.created_at >= cutoff,
        OutreachAttempt.status.in_([OutreachStatus.SENT, OutreachStatus.APPROVED, OutreachStatus.PENDING]),
    )
    return session.execute(stmt).first() is not None


def get_outreach_stats(session: Session) -> dict[str, int | float]:
    total = session.execute(select(func.count()).select_from(OutreachAttempt)).scalar_one()
    by_status = dict(
        session.execute(
            select(OutreachAttempt.status, func.count()).group_by(OutreachAttempt.status)
        ).all()
    )
    sent_today = count_outreaches_since(
        session,
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0),
    )
    return {
        "total": int(total),
        "sent_today": sent_today,
        "by_status": {k.value if hasattr(k, "value") else str(k): v for k, v in by_status.items()},
    }


def approve_outreach(
    session: Session,
    attempt: OutreachAttempt,
    *,
    proposed_bid: float | None = None,
) -> OutreachAttempt:
    if proposed_bid is not None:
        attempt.proposed_bid = proposed_bid
    attempt.status = OutreachStatus.APPROVED
    attempt.approved_at = datetime.now(UTC)
    attempt.dry_run = False
    session.flush()
    return attempt


def mark_outreach_sent(session: Session, attempt: OutreachAttempt, *, screenshot_path: str | None = None) -> None:
    attempt.status = OutreachStatus.SENT
    attempt.sent_at = datetime.now(UTC)
    attempt.screenshot_path = screenshot_path
    session.flush()


def mark_outreach_failed(session: Session, attempt: OutreachAttempt, error: str) -> None:
    attempt.status = OutreachStatus.FAILED
    attempt.error_message = error
    session.flush()


def cancel_outreach(session: Session, attempt: OutreachAttempt) -> OutreachAttempt:
    attempt.status = OutreachStatus.CANCELLED
    session.flush()
    return attempt


def clear_outreach_queue(
    session: Session,
    *,
    statuses: tuple[OutreachStatus, ...] | None = None,
    platform: Platform | None = None,
) -> int:
    """Cancel queued outreaches so listings can be re-scanned. Returns count cancelled."""
    statuses = statuses or ACTIONABLE_OUTREACH_STATUSES
    stmt = select(OutreachAttempt).where(OutreachAttempt.status.in_(statuses))
    if platform is not None:
        stmt = stmt.where(OutreachAttempt.platform == platform)
    attempts = list(session.execute(stmt).scalars().all())
    for attempt in attempts:
        cancel_outreach(session, attempt)
    session.flush()
    return len(attempts)


def resolve_listing_by_url_or_id(session: Session, ref: str) -> Listing | None:
    if ref.isdigit():
        return session.get(Listing, int(ref))
    stmt = select(Listing).where(Listing.url.contains(ref)).limit(1)
    return session.execute(stmt).scalar_one_or_none()