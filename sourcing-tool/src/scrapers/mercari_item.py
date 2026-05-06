from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from src.config import CONFIG

logger = logging.getLogger(__name__)

ITEM_URL = "https://jp.mercari.com/item/{item_id}"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class MercariItemFetcher:
    """Fetches individual Mercari item details from public item pages.

    Parses the __NEXT_DATA__ JSON embedded in each item's HTML page.
    No authentication required — item pages are publicly accessible.
    """

    def __init__(self):
        cfg = CONFIG["scraping"]
        self.delay = cfg["request_delay_sec"]
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": cfg["user_agent"],
                "Accept-Language": "ja-JP,ja;q=0.9",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def fetch_details(self, item_id: str) -> dict | None:
        """Fetch and parse item details. Returns dict with condition/description/images/stock_state."""
        await asyncio.sleep(self.delay)
        try:
            resp = await self.client.get(ITEM_URL.format(item_id=item_id))
            resp.raise_for_status()
            return self._parse_html(resp.text, item_id)
        except Exception:
            logger.warning("Failed to fetch item %s", item_id, exc_info=True)
            return None

    def _parse_html(self, html: str, item_id: str) -> dict | None:
        match = NEXT_DATA_RE.search(html)
        if not match:
            logger.warning("No __NEXT_DATA__ found for item %s", item_id)
            return None
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.warning("Failed to parse __NEXT_DATA__ for item %s", item_id)
            return None
        return self._extract(data, item_id)

    def _extract(self, data: dict, item_id: str) -> dict:
        # Navigate to item object — try common Next.js page prop locations
        page_props = data.get("props", {}).get("pageProps", {})
        item = (
            page_props.get("item")
            or page_props.get("product")
            or page_props.get("itemData")
            or {}
        )

        if not item:
            logger.warning("Could not find item data in __NEXT_DATA__ for %s (keys: %s)",
                           item_id, list(page_props.keys()))

        condition = self._get_condition(item)
        description = item.get("description") or item.get("itemDescription") or ""
        images = self._get_images(item)
        stock_state = self._get_stock_state(item)

        return {
            "condition": condition,
            "description": description,
            "extra_images": json.dumps(images, ensure_ascii=False),
            "stock_state": stock_state or "unknown",
        }

    def _get_condition(self, item: dict) -> str:
        for key in ("itemCondition", "condition"):
            cond = item.get(key)
            if isinstance(cond, dict):
                return cond.get("name") or cond.get("displayName") or ""
            if isinstance(cond, str):
                return cond
        return ""

    def _get_images(self, item: dict) -> list[str]:
        urls: list[str] = []
        for key in ("photos", "images", "thumbnails"):
            photos = item.get(key)
            if not photos:
                continue
            for p in photos:
                if isinstance(p, str):
                    urls.append(p)
                elif isinstance(p, dict):
                    url = p.get("imageUrl") or p.get("url") or p.get("thumbnail") or ""
                    if url:
                        urls.append(url)
            if urls:
                break
        return urls

    def _get_stock_state(self, item: dict) -> str:
        for key in ("status", "itemStatus", "stockState"):
            val = item.get(key)
            if isinstance(val, str) and val:
                return val
            if isinstance(val, dict):
                return val.get("name") or val.get("id") or ""
        return ""
