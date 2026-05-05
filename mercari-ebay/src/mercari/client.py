from __future__ import annotations

import asyncio
import logging
import re

import httpx

from src.config import CONFIG, MERCARI_SESSION_TOKEN

logger = logging.getLogger(__name__)

_ITEM_DETAIL_URL = "https://api.mercari.jp/v2/entities/items/{item_id}"
_FAVORITES_URL = "https://api.mercari.jp/v1/me/likes"
_SEARCH_URL = "https://api.mercari.jp/v2/entities:search"
_WEB_ITEM_URL = "https://jp.mercari.com/item/{item_id}"

# Mercari item status values returned by the API
_STATUS_ON_SALE = "ITEM_STATUS_ON_SALE"
_STATUS_SOLD_OUT = "ITEM_STATUS_SOLD_OUT"
_STATUS_TRADING = "ITEM_STATUS_TRADING"
_STATUS_STOP = "ITEM_STATUS_STOP"


def _make_headers(with_auth: bool = True) -> dict:
    headers = {
        "User-Agent": CONFIG["scraping"]["user_agent"]
        if "scraping" in CONFIG else
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Platform": "web",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ja,en;q=0.9",
        "DPoP": "",
    }
    if with_auth and MERCARI_SESSION_TOKEN:
        headers["Authorization"] = f"Bearer {MERCARI_SESSION_TOKEN}"
    return headers


def _extract_item_id(url_or_id: str) -> str:
    """Extract item ID from a Mercari URL or return as-is if already an ID."""
    # Matches patterns like: jp.mercari.com/item/m12345678
    m = re.search(r"/item/([a-zA-Z0-9]+)", url_or_id)
    if m:
        return m.group(1)
    # Also handle bare IDs like "m12345678"
    return url_or_id.strip()


class MercariClient:
    def __init__(self):
        delay = 2.0
        if "scraping" in CONFIG:
            delay = CONFIG["scraping"].get("request_delay_sec", 2.0)
        self._delay = CONFIG.get("sync", {}).get("request_delay_sec", delay)
        self.client = httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=_make_headers(with_auth=False),
        )

    async def close(self):
        await self.client.aclose()

    async def get_item_status(self, mercari_id: str) -> dict:
        """
        Check a single Mercari item's current price and status.

        Returns dict with keys:
          status: 'on_sale' | 'sold_out' | 'deleted' | 'unknown'
          price_jpy: int
          title: str
          image_url: str
          condition: str
        """
        item_id = _extract_item_id(mercari_id)
        await asyncio.sleep(self._delay)

        # Strategy 1: Use the item detail REST endpoint
        try:
            resp = await self.client.get(
                _ITEM_DETAIL_URL.format(item_id=item_id),
                headers=_make_headers(with_auth=False),
            )
            if resp.status_code == 404:
                return self._deleted_result()
            if resp.status_code == 200:
                data = resp.json()
                return self._parse_item_detail(data)
        except Exception:
            logger.debug("Item detail API failed for %s, trying fallback", item_id)

        # Strategy 2: Search for the specific item ID in Mercari search
        try:
            resp = await self.client.post(
                _SEARCH_URL,
                json={
                    "searchSessionId": "",
                    "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
                    "searchCondition": {
                        "keyword": item_id,
                        "sort": "SORT_DEFAULT",
                        "order": "ORDER_DESC",
                        "status": ["STATUS_ON_SALE", "STATUS_SOLD_OUT"],
                        "sizeId": [],
                        "categoryId": [],
                        "brandId": [],
                        "sellerId": [],
                        "priceMin": 0,
                        "priceMax": 0,
                        "itemConditionId": [],
                        "shippingPayerId": [],
                        "shippingFromArea": [],
                        "shippingMethod": [],
                        "colorId": [],
                        "hasCoupon": False,
                        "attributes": [],
                        "itemTypes": [],
                        "skuIds": [],
                    },
                    "defaultDatasets": ["DATASET_TYPE_MERCARI"],
                    "serviceFrom": "suruga",
                    "userId": "",
                    "withItemBrand": False,
                    "withItemSize": False,
                    "withItemPromotions": False,
                    "withItemSizes": False,
                    "withShopname": False,
                    "limit": 10,
                    "pageToken": "",
                },
                headers=_make_headers(with_auth=False),
            )
            if resp.status_code == 200:
                data = resp.json()
                for it in data.get("items", []):
                    if str(it.get("id", "")) == item_id:
                        return self._parse_search_item(it)
                # Item not found in search - likely sold/deleted
                return self._sold_result()
        except Exception:
            logger.warning("Both status checks failed for Mercari item %s", item_id)

        return {"status": "unknown", "price_jpy": 0, "title": "", "image_url": "", "condition": ""}

    async def get_favorites(self, max_pages: int = 10) -> list[dict]:
        """
        Fetch the authenticated user's liked/favorited items from Mercari.
        Requires MERCARI_SESSION_TOKEN to be set.

        Returns list of item dicts with: mercari_id, title, price_jpy, url, image_url, condition
        """
        if not MERCARI_SESSION_TOKEN:
            logger.warning(
                "MERCARI_SESSION_TOKEN not set. "
                "Cannot auto-import favorites. Use 'add-item' command instead."
            )
            return []

        items: list[dict] = []
        page_token = ""

        for page_num in range(max_pages):
            await asyncio.sleep(self._delay)
            try:
                params = {"status": "on_sale", "page_size": "30"}
                if page_token:
                    params["page_token"] = page_token

                resp = await self.client.get(
                    _FAVORITES_URL,
                    params=params,
                    headers=_make_headers(with_auth=True),
                )

                if resp.status_code == 401:
                    logger.error(
                        "Mercari auth failed (401). "
                        "MERCARI_SESSION_TOKEN may be expired - re-extract from browser."
                    )
                    break

                resp.raise_for_status()
                data = resp.json()

                page_items = data.get("items", [])
                if not page_items:
                    break

                for it in page_items:
                    parsed = self._parse_favorites_item(it)
                    if parsed:
                        items.append(parsed)

                page_token = data.get("nextPageToken", "")
                if not page_token:
                    break

                logger.info("Favorites page %d: fetched %d items (total %d)",
                            page_num + 1, len(page_items), len(items))

            except Exception:
                logger.exception("Failed to fetch Mercari favorites page %d", page_num + 1)
                break

        logger.info("Total favorites fetched: %d", len(items))
        return items

    # --- Parsing helpers ---

    def _parse_item_detail(self, data: dict) -> dict:
        item = data.get("item", data)  # API may wrap in 'item' key
        status_raw = item.get("status", "")
        price = int(item.get("price", 0))
        thumbnails = item.get("thumbnails", [])
        image_url = thumbnails[0] if thumbnails else item.get("imageUrl", "")

        if status_raw in (_STATUS_SOLD_OUT, _STATUS_TRADING):
            status = "sold_out"
        elif status_raw == _STATUS_STOP:
            status = "sold_out"
        elif status_raw == _STATUS_ON_SALE:
            status = "on_sale"
        else:
            # If item exists with unknown status, treat as on_sale
            status = "on_sale" if price > 0 else "unknown"

        return {
            "status": status,
            "price_jpy": price,
            "title": item.get("name", item.get("title", "")),
            "image_url": image_url,
            "condition": item.get("itemConditionText", item.get("conditionText", "")),
        }

    def _parse_search_item(self, item: dict) -> dict:
        status_raw = item.get("status", "")
        price = int(item.get("price", 0))
        thumbnails = item.get("thumbnails", [])

        if status_raw in ("ITEM_STATUS_SOLD_OUT", "ITEM_STATUS_TRADING"):
            status = "sold_out"
        else:
            status = "on_sale"

        return {
            "status": status,
            "price_jpy": price,
            "title": item.get("name", ""),
            "image_url": thumbnails[0] if thumbnails else "",
            "condition": item.get("itemConditionText", ""),
        }

    def _parse_favorites_item(self, item: dict) -> dict | None:
        item_id = str(item.get("id", ""))
        if not item_id:
            return None
        thumbnails = item.get("thumbnails", [])
        return {
            "mercari_id": item_id,
            "title": item.get("name", ""),
            "price_jpy": int(item.get("price", 0)),
            "url": f"https://jp.mercari.com/item/{item_id}",
            "image_url": thumbnails[0] if thumbnails else "",
            "condition": item.get("itemConditionText", ""),
        }

    @staticmethod
    def _deleted_result() -> dict:
        return {"status": "deleted", "price_jpy": 0, "title": "", "image_url": "", "condition": ""}

    @staticmethod
    def _sold_result() -> dict:
        return {"status": "sold_out", "price_jpy": 0, "title": "", "image_url": "", "condition": ""}
