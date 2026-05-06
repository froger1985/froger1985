from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from playwright.async_api import BrowserContext, async_playwright

from src.config import CONFIG

logger = logging.getLogger(__name__)

ITEM_URL = "https://jp.mercari.com/item/{item_id}"
SESSION_FILE = Path("data/mercari_session.json")


class MercariItemFetcher:
    """Fetches individual Mercari item details via Playwright API interception.

    Navigates to each item page and intercepts the internal API call that
    returns item details (condition, description, images, stock_state).
    Reuses a single browser context across all items for efficiency.
    """

    def __init__(self):
        self.delay = CONFIG["scraping"]["request_delay_sec"]
        self._pw = None
        self._browser = None
        self._context: BrowserContext | None = None

    async def _ensure_context(self):
        if self._context:
            return
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        kwargs: dict = {"user_agent": CONFIG["scraping"]["user_agent"]}
        if SESSION_FILE.exists():
            kwargs["storage_state"] = str(SESSION_FILE)
        self._context = await self._browser.new_context(**kwargs)

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def fetch_details(self, item_id: str) -> dict | None:
        """Fetch item details by intercepting the API response on the item page."""
        await asyncio.sleep(self.delay)
        await self._ensure_context()

        result: dict | None = None
        found = asyncio.Event()
        api_urls: list[str] = []

        page = await self._context.new_page()

        async def on_response(response):
            nonlocal result
            url = response.url
            if "api.mercari.jp" not in url:
                return
            api_urls.append(url)
            if response.status != 200:
                return
            try:
                data = await response.json()
                parsed = self._try_parse(data, item_id)
                if parsed and not found.is_set():
                    result = parsed
                    found.set()
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(
                ITEM_URL.format(item_id=item_id),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            try:
                await asyncio.wait_for(found.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "No item data found for %s. API URLs intercepted: %s",
                    item_id, api_urls[:10],
                )
        except Exception:
            logger.warning("Failed to fetch item %s", item_id, exc_info=True)
        finally:
            await page.close()

        return result

    def _try_parse(self, data: dict, item_id: str) -> dict | None:
        item = data.get("item") or data.get("data") or data
        if not isinstance(item, dict):
            return None

        condition = self._get_condition(item)
        description = item.get("description") or item.get("itemDescription") or ""
        images = self._get_images(item)
        stock_state = self._get_stock_state(item)

        if not any([condition, description, images, stock_state]):
            return None

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
