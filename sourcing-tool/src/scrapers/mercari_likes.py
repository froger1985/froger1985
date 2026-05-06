from __future__ import annotations

import asyncio
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
            storage_state = str(SESSION_FILE) if SESSION_FILE.exists() else None
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=storage_state)
            if storage_state:
                logger.info("Session loaded from %s", SESSION_FILE)

            page = await context.new_page()
            collected: list[dict] = []
            # Event fires when the first likes API response arrives
            first_data_received = asyncio.Event()

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
                            first_data_received.set()
                    except Exception:
                        pass

            page.on("response", _intercept)

            print("メルカリのいいねページを開いています...")
            await page.goto(LIKES_PAGE, wait_until="domcontentloaded")

            # Give the page 4 seconds to load liked items (works if already logged in)
            try:
                await asyncio.wait_for(first_data_received.wait(), timeout=4.0)
                print(f"ログイン済みを確認。商品データを取得中...")
            except asyncio.TimeoutError:
                # Not logged in — show message and wait up to 3 minutes
                print("\nログインが必要です。ブラウザでメルカリにログインしてください。")
                print("ログインが完了すると自動で続行します（最大3分）...\n")
                try:
                    await asyncio.wait_for(first_data_received.wait(), timeout=180.0)
                    print("ログインを確認しました。商品データを取得中...")
                except asyncio.TimeoutError:
                    print("3分待ってもログインが確認できませんでした。")
                    print("（いいねが0件の場合も同様です）")
                    await self._save_session(context)
                    await browser.close()
                    return []

            # Scroll down to trigger pagination and collect all items
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
