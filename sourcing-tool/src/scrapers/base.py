from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

from src.config import CONFIG
from src.db.models import SourceListing

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all sourcing site scrapers."""

    source_name: str = ""

    def __init__(self):
        scraping_cfg = CONFIG["scraping"]
        self.delay = scraping_cfg["request_delay_sec"]
        self.max_results = scraping_cfg["max_results_per_search"]
        self.user_agent = scraping_cfg["user_agent"]
        self.client = httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        await asyncio.sleep(self.delay)
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp

    @abstractmethod
    async def search(self, keyword: str, category: str = "game") -> list[SourceListing]:
        """Search for items matching the keyword. Returns a list of SourceListing."""
        ...

    def _make_listing(
        self,
        source_id: str,
        category: str,
        title: str,
        price_jpy: int,
        url: str,
        image_url: str = "",
        condition: str = "",
    ) -> SourceListing:
        return SourceListing(
            source=self.source_name,
            source_id=source_id,
            category=category,
            title=title,
            price_jpy=price_jpy,
            url=url,
            image_url=image_url,
            condition=condition,
        )
