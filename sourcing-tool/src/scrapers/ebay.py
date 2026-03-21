from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from src.config import EBAY_CLIENT_ID, EBAY_CLIENT_SECRET
from src.db.models import EbaySold

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayAPI:
    """eBay Browse API client for fetching sold/completed listings."""

    def __init__(self):
        self._token: str = ""
        self._token_expires: datetime = datetime.min
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def _ensure_token(self):
        if self._token and datetime.now() < self._token_expires:
            return

        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            raise RuntimeError(
                "eBay API credentials not configured. "
                "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env"
            )

        resp = await self.client.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET),
            data={
                "grant_type": "client_credentials",
                "scope": SCOPE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = datetime.now() + timedelta(
            seconds=data.get("expires_in", 7200) - 60
        )
        logger.info("eBay OAuth token acquired")

    async def search_sold(
        self, query: str, limit: int = 50, category_id: str | None = None
    ) -> list[EbaySold]:
        """Search eBay for sold/completed items."""
        await self._ensure_token()

        params: dict = {
            "q": query,
            "limit": str(min(limit, 200)),
            "filter": "conditions:{USED},buyingOptions:{FIXED_PRICE|AUCTION}",
            "sort": "-price",
        }
        if category_id:
            params["category_ids"] = category_id

        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "X-EBAY-C-ENDUSERCTX": "affiliateCampaignId=<ePNCampaignId>,affiliateReferenceId=<referenceId>",
        }

        try:
            resp = await self.client.get(BROWSE_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("eBay API search failed for '%s'", query)
            return []

        results: list[EbaySold] = []
        for item in data.get("itemSummaries", []):
            price_val = item.get("price", {}).get("value", "0")
            sold = EbaySold(
                search_query=query,
                item_title=item.get("title", ""),
                sold_price_usd=float(price_val),
                sold_date=item.get("itemEndDate", ""),
                item_url=item.get("itemWebUrl", ""),
            )
            results.append(sold)

        logger.info("eBay: found %d sold items for '%s'", len(results), query)
        return results

    async def get_average_sold_price(self, query: str, limit: int = 30) -> dict:
        """Get average sold price and count for a search query.

        Returns:
            dict with keys: avg_price_usd, sold_count, min_price_usd, max_price_usd
        """
        sold_items = await self.search_sold(query, limit=limit)

        if not sold_items:
            return {
                "avg_price_usd": 0.0,
                "sold_count": 0,
                "min_price_usd": 0.0,
                "max_price_usd": 0.0,
                "items": [],
            }

        prices = [s.sold_price_usd for s in sold_items if s.sold_price_usd > 0]
        if not prices:
            return {
                "avg_price_usd": 0.0,
                "sold_count": 0,
                "min_price_usd": 0.0,
                "max_price_usd": 0.0,
                "items": [],
            }

        # Remove outliers (prices outside 1.5x IQR)
        prices.sort()
        q1_idx = len(prices) // 4
        q3_idx = 3 * len(prices) // 4
        q1 = prices[q1_idx] if q1_idx < len(prices) else prices[0]
        q3 = prices[q3_idx] if q3_idx < len(prices) else prices[-1]
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        filtered = [p for p in prices if lower <= p <= upper]

        if not filtered:
            filtered = prices

        return {
            "avg_price_usd": sum(filtered) / len(filtered),
            "sold_count": len(prices),
            "min_price_usd": min(filtered),
            "max_price_usd": max(filtered),
            "items": sold_items,
        }
