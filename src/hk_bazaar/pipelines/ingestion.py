"""Ingest scraped listings into the database."""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from hk_bazaar.database.crud import upsert_listing
from hk_bazaar.pipelines.cleaning import clean_listing
from hk_bazaar.scrapers.base import RawListing


def ingest_listings(session: Session, raw_listings: list[RawListing]) -> dict[str, int]:
    created = 0
    updated = 0
    for raw in raw_listings:
        cleaned = clean_listing(raw)
        _, is_new = upsert_listing(session, cleaned)
        if is_new:
            created += 1
        else:
            updated += 1
    session.commit()
    logger.info("Ingested {} listings ({} new, {} updated)", len(raw_listings), created, updated)
    return {"total": len(raw_listings), "created": created, "updated": updated}