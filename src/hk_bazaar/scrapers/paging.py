"""Stop a multi-page scrape once it overlaps listings already stored."""

from __future__ import annotations

from hk_bazaar.scrapers.base import RawListing


class PageWalk:
    """Collect pages until the feed is exhausted, repeats itself, or is already stored.

    `caught_up` is true when a page was empty or every new id on it is already in
    `known_ids`. A page that only repeats ids from earlier in this same walk is
    stuck pagination, not proof that older listings were reached.
    """

    def __init__(self, known_ids: set[str] | None) -> None:
        self.known_ids = known_ids
        self.seen: set[str] = set()
        self.listings: list[RawListing] = []
        self.pages_fetched = 0
        self.caught_up = False
        self.note = ""

    def add(self, batch: list[RawListing]) -> bool:
        """Record one page. Return True when the walk should stop."""
        self.pages_fetched += 1
        fresh = [item for item in batch if item.external_id not in self.seen]
        for item in fresh:
            self.seen.add(item.external_id)
        if not batch:
            self.caught_up = True
            return True
        if not fresh:
            self.note = "next page repeated listings already fetched; older pages were not read"
            return True
        self.listings.extend(fresh)
        if self.known_ids is not None and all(item.external_id in self.known_ids for item in fresh):
            self.caught_up = True
            return True
        return False
