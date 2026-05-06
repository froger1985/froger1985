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
    """Fetches liked items from Mercari using Playwright browser automation."""

    async def fetch_all_likes(self, limit: int = 0) -> list[SourceListing]:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            storage_state = str(SESSION_FILE) if SESSION_FILE.exists() else None
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context(storage_state=storage_state)

            page = await context.new_page()
            collected: list[dict] = []
            first_data_received = asyncio.Event()

            async def _intercept(response):
                url = response.url
                # Capture ALL api.mercari.jp JSON responses for debugging
                if "api.mercari.jp" in url and response.status == 200:
                    try:
                        content_type = response.headers.get("content-type", "")
                        if "json" not in content_type:
                            return
                        data = await response.json()
                        # Look for items in common response shapes
                        items = (
                            data.get("items")
                            or data.get("data")
                            or (data.get("result") or {}).get("items")
                            or []
                        )
                        if items and isinstance(items, list) and len(items) > 0:
                            print(f"  → 商品データ取得: {len(items)}件 ({url[:80]})")
                            collected.extend(items)
                            first_data_received.set()
                        else:
                            # Show all API calls so we can debug the URL
                            print(f"  [API] {url[:80]}")
                    except Exception:
                        pass

            page.on("response", _intercept)

            print("ブラウザを起動しています...")
            await page.goto(LIKES_PAGE, wait_until="domcontentloaded")
            print("いいねページを開きました。4秒待機中...")
            await page.wait_for_timeout(4000)

            if not first_data_received.is_set():
                print("\n[!] まだ商品データが届いていません。")
                print("    ブラウザでメルカリにログインしてください。")
                print("    ログイン完了後、メルカリがいいね一覧を読み込むと自動で続行します。")
                print("    (最大3分待機)\n")
                try:
                    await asyncio.wait_for(first_data_received.wait(), timeout=180.0)
                    print("データを受信しました！スクロールして全件取得します...")
                except asyncio.TimeoutError:
                    print("3分タイムアウト。ログインが完了しなかったか、いいねが0件です。")
                    await self._save_session(context)
                    await browser.close()
                    return []

            # Re-navigate to likes page if user ended up elsewhere after login
            if "mypage/likes" not in page.url:
                print("いいねページに戻ります...")
                await page.goto(LIKES_PAGE, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

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
