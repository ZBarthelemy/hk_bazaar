"""Base scraper abstractions."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from hk_bazaar.config import Settings, get_settings
from hk_bazaar.database.models import Platform


@dataclass
class RawListing:
    platform: Platform
    external_id: str
    title: str
    url: str
    description: str | None = None
    price: float | None = None
    price_display: str | None = None
    location_raw: str | None = None
    district: str | None = None
    region: str | None = None
    category_raw: str | None = None
    category: str | None = None
    condition: str | None = None
    posted_at: datetime | None = None
    posted_at_raw: str | None = None
    seller_name: str | None = None
    seller_external_id: str | None = None
    image_urls: list[str] = field(default_factory=list)
    views: int | None = None
    favorites: int | None = None
    is_active: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class BaseScraper(ABC):
    platform: Platform
    pages_fetched: int = 0
    caught_up: bool = False
    page_note: str = ""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            headers={"User-Agent": self.settings.user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BaseScraper:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def polite_delay(self) -> None:
        if self.settings.request_delay_seconds > 0:
            time.sleep(self.settings.request_delay_seconds)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch(self, url: str) -> str:
        logger.debug("GET {}", url)
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    @abstractmethod
    def scrape(self, **kwargs: Any) -> list[RawListing]:
        """Scrape listings from the platform."""