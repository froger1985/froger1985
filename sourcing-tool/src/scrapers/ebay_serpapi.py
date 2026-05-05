"""eBay sold listings via SerpAPI — more reliable than the Browse API for sold data."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlencode

import httpx

from src.db.models import EbaySold

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"


def _load_serpapi_key() -> str:
    key = os.environ.get("SERPAPI_KEY", "")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "SERPAPI_KEY":
                return v.strip()
    return ""


def _parse_price(raw: str) -> float:
    """Extract a float price from a raw string like '$12.50' or 'US $12.50'."""
    m = re.search(r"[\d,]+\.?\d*", raw.replace(",", ""))
    return float(m.group()) if m else 0.0


class EbaySerpAPI:
    """Fetch eBay sold/completed listings using SerpAPI."""

    def __init__(self):
        self._key = _load_serpapi_key()
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self.client.aclose()

    async def search_sold(self, query: str, limit: int = 60) -> list[EbaySold]:
        if not self._key:
            logger.warning("SERPAPI_KEY not set — skipping eBay sold search for '%s'", query)
            return []

        params = {
            "engine": "ebay",
            "ebay_domain": "ebay.com",
            "_nkw": query,
            "LH_Complete": "1",
            "LH_Sold": "1",
            "_sop": "13",
            "_ipg": str(min(limit, 60)),
            "api_key": self._key,
        }

        try:
            resp = await self.client.get(SERPAPI_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("SerpAPI request failed for '%s'", query)
            return []

        results: list[EbaySold] = []
        for item in data.get("organic_results", []):
            title = item.get("title", "")
            if not title:
                continue

            price_raw = ""
            price_info = item.get("price", {})
            if isinstance(price_info, dict):
                price_raw = price_info.get("raw", "")
                extracted = price_info.get("extracted")
                price_usd = float(extracted) if extracted is not None else _parse_price(price_raw)
            else:
                price_usd = _parse_price(str(price_info))

            if price_usd <= 0:
                continue

            sold_date = ""
            for key in ("date", "sold_date", "condition"):
                val = item.get(key, "")
                if val and "sold" in str(val).lower():
                    sold_date = str(val)
                    break

            results.append(
                EbaySold(
                    search_query=query,
                    item_title=title,
                    sold_price_usd=price_usd,
                    sold_date=sold_date,
                    item_url=item.get("link", ""),
                )
            )

        logger.info("SerpAPI eBay: %d sold results for '%s'", len(results), query)
        return results

    async def get_average_sold_price(self, query: str, limit: int = 60) -> dict:
        """Return avg sold price stats for a search query."""
        sold_items = await self.search_sold(query, limit=limit)

        if not sold_items:
            return {
                "avg_price_usd": 0.0,
                "sold_count": 0,
                "min_price_usd": 0.0,
                "max_price_usd": 0.0,
                "items": [],
            }

        prices = sorted(s.sold_price_usd for s in sold_items if s.sold_price_usd > 0)
        if not prices:
            return {"avg_price_usd": 0.0, "sold_count": 0, "min_price_usd": 0.0, "max_price_usd": 0.0, "items": []}

        # IQR outlier removal
        n = len(prices)
        q1 = prices[n // 4]
        q3 = prices[(3 * n) // 4]
        iqr = q3 - q1
        filtered = [p for p in prices if (q1 - 1.5 * iqr) <= p <= (q3 + 1.5 * iqr)] or prices

        return {
            "avg_price_usd": sum(filtered) / len(filtered),
            "sold_count": len(prices),
            "min_price_usd": min(filtered),
            "max_price_usd": max(filtered),
            "items": sold_items,
        }
