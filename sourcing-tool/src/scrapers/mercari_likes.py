from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from src.db.models import SourceListing

logger = logging.getLogger(__name__)

WEB_BASE = "https://jp.mercari.com/item"
LIKES_PAGE = "https://jp.mercari.com/mypage/likes"
SESSION_FILE = Path("data/mercari_session.json")
SCROLL_PAUSE_MS = 2500


class MercariLikesScraper:
    """Fetches liked items from Mercari using Playwright browser automation.

    Launches a real browser, intercepts the API responses the likes page makes
    internally, and collects the JSON data — no JWT signing required.
    """

    async def fetch_all_likes(self, limit: int = 0) -> list[SourceListing]:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            # Load saved session at context creation (the proper Playwright way)
            storage_state = str(SESSION_FILE) if SESSION_FILE.exists() else None
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=storage_state)
            if storage_state:
                logger.info("Session loaded from %s", SESSION_FILE)

            page = await context.new_page()
            collected: list[dict] = []

            async def _intercept(response):
                url = response.url
                if (
                    "api.mercari.jp" in url
                    and response.status == 200
                    and any(k in url for k in ("likes", "favorites", "bookmarks"))
                ):
                    try:
                        data = await response.json()
                        items = data.get("items", data.get("data", []))
                        if items:
                            logger.info("Intercepted %d items from %s", len(items), url)
                            collected.extend(items)
                    except Exception:
                        pass

            page.on("response", _intercept)

            await page.goto(LIKES_PAGE, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            if not await self._is_logged_in(page):
                print("\nブラウザでメルカリにログインしてください。")
                print("ログイン完了後、ここで Enter キーを押してください: ", end="", flush=True)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input)
                await page.wait_for_load_state("networkidle")

            await self._scroll_to_collect(page, collected, limit)
            await self._save_session(context)
            await browser.close()

        listings = []
        seen_ids: set[str] = set()
        for item in collected:
            parsed = self._parse_item(item)
            if parsed and parsed.source_id not in seen_ids:
                seen_ids.add(parsed.source_id)
                listings.append(parsed)
                if limit > 0 and len(listings) >= limit:
                    break

        logger.info("Total likes fetched: %d", len(listings))
        return listings

    async def _is_logged_in(self, page) -> bool:
        url = page.url
        return "login" not in url and "signup" not in url

    async def _scroll_to_collect(self, page, collected: list[dict], limit: int) -> None:
        prev_count = 0
        no_change_streak = 0

        while True:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(SCROLL_PAUSE_MS)

            current_count = len(collected)
            if current_count == prev_count:
                no_change_streak += 1
                if no_change_streak >= 2:
                    break
            else:
                no_change_streak = 0

            prev_count = current_count

            if limit > 0 and current_count >= limit:
                break

    async def _save_session(self, context) -> None:
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(SESSION_FILE))
            logger.info("Session saved to %s", SESSION_FILE)
        except Exception:
            logger.warning("Failed to save session", exc_info=True)

    def _parse_item(self, item: dict) -> SourceListing | None:
        try:
            item_id = str(item.get("id", ""))
            if not item_id:
                return None

            title = item.get("name", "")
            price = item.get("price", 0)
            if not title or not price:
                return None

            image_url = ""
            thumbnails = item.get("thumbnails", [])
            if thumbnails:
                image_url = thumbnails[0] if isinstance(thumbnails[0], str) else ""
            if not image_url:
                image_url = item.get("thumbnail", "")

            condition = ""
            cond_obj = item.get("itemCondition", item.get("item_condition", {}))
            if isinstance(cond_obj, dict):
                condition = cond_obj.get("name", "")
            if not condition:
                condition = item.get("itemConditionText", "")

            return SourceListing(
                source="mercari_likes",
                source_id=item_id,
                category="unknown",
                title=title,
                price_jpy=int(price),
                url=f"{WEB_BASE}/{item_id}",
                image_url=image_url,
                condition=condition,
            )
        except Exception:
            logger.debug("Failed to parse item", exc_info=True)
            return None
