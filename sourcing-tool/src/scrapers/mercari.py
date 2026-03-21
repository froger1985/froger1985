from __future__ import annotations

import logging
import re

from src.db.models import SourceListing
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.mercari.jp/v2/entities:search"
WEB_BASE = "https://jp.mercari.com/item"


class MercariScraper(BaseScraper):
    """Scraper for Mercari using their internal API.

    Mercari's web app calls an internal JSON API. We replicate those
    requests directly, which is faster and more reliable than browser
    automation. If Mercari changes the API, this will need updating.
    """

    source_name = "mercari"

    async def search(self, keyword: str, category: str = "game") -> list[SourceListing]:
        listings: list[SourceListing] = []

        try:
            # Mercari internal search API (JSON)
            resp = await self.client.post(
                SEARCH_URL,
                json={
                    "searchSessionId": "",
                    "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
                    "searchCondition": {
                        "keyword": keyword,
                        "excludeKeyword": "",
                        "sort": "SORT_CREATED_TIME",
                        "order": "ORDER_DESC",
                        "status": ["STATUS_ON_SALE"],
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
                    "withItemBrand": True,
                    "withItemSize": False,
                    "withItemPromotions": True,
                    "withItemSizes": False,
                    "withShopname": False,
                    "limit": min(self.max_results, 30),
                    "pageToken": "",
                },
                headers={
                    "User-Agent": self.user_agent,
                    "X-Platform": "web",
                    "Accept": "application/json, text/plain, */*",
                    "Dpop": "",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Mercari search failed for '%s'", keyword)
            return listings

        items = data.get("items", [])
        for item in items:
            listing = self._parse_item(item, category)
            if listing:
                listings.append(listing)

        logger.info("Mercari: found %d items for '%s'", len(listings), keyword)
        return listings[:self.max_results]

    def _parse_item(self, item: dict, category: str) -> SourceListing | None:
        try:
            item_id = item.get("id", "")
            if not item_id:
                return None

            title = item.get("name", "")
            price = item.get("price", 0)
            if not title or not price:
                return None

            image_url = ""
            thumbnails = item.get("thumbnails", [])
            if thumbnails:
                image_url = thumbnails[0]

            status_text = item.get("itemConditionText", "")

            return self._make_listing(
                source_id=str(item_id),
                category=category,
                title=title,
                price_jpy=int(price),
                url=f"{WEB_BASE}/{item_id}",
                image_url=image_url,
                condition=status_text,
            )
        except Exception:
            logger.debug("Failed to parse Mercari item", exc_info=True)
            return None
