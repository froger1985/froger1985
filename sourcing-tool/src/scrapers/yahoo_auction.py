from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from src.db.models import SourceListing
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://auctions.yahoo.co.jp"
SEARCH_URL = f"{BASE_URL}/search/search"


class YahooAuctionScraper(BaseScraper):
    """Scraper for Yahoo Auctions Japan."""

    source_name = "yahoo_auction"

    async def search(self, keyword: str, category: str = "game") -> list[SourceListing]:
        listings: list[SourceListing] = []

        try:
            resp = await self._get(SEARCH_URL, params={
                "p": keyword,
                "va": keyword,
                "exflg": "1",
                "b": "1",
                "n": str(min(self.max_results, 50)),
                "s1": "new",       # Sort by newest
                "o1": "d",
                "auccat": "",
                "tab_ex": "commerce",
                "ei": "utf-8",
                "fr": "auc_top",
            })
        except Exception:
            logger.exception("Yahoo Auction search failed for '%s'", keyword)
            return listings

        soup = BeautifulSoup(resp.text, "html.parser")

        # Try multiple selectors for auction items
        items = soup.select(".Product, .Result__item, li.Product")
        if not items:
            items = soup.select("[class*='Product']")

        for item in items:
            listing = self._parse_item(item, category)
            if listing:
                listings.append(listing)

        logger.info("Yahoo Auction: found %d items for '%s'", len(listings), keyword)
        return listings[:self.max_results]

    def _parse_item(self, item, category: str) -> SourceListing | None:
        try:
            # Find link
            link = item.select_one("a[href*='page.auctions.yahoo.co.jp'], a[href*='auctions.yahoo.co.jp/jp/auction']")
            if not link:
                link = item.find("a", href=True)
            if not link:
                return None

            href = link["href"]
            # Extract auction ID
            match = re.search(r"([a-zA-Z]\d{10,})", href)
            source_id = match.group(1) if match else href.rstrip("/").split("/")[-1]

            # Title
            title_el = item.select_one(
                ".Product__title, .Product__titleLink, [class*='title'] a, h3 a"
            ) or link
            title = title_el.get_text(strip=True)
            if not title:
                return None

            # Price (current bid or buy-it-now)
            price_jpy = 0
            price_el = item.select_one(
                ".Product__priceValue, .Product__price, [class*='price']"
            )
            if price_el:
                price_jpy = self._parse_price(price_el.get_text(strip=True))

            if not price_jpy:
                # Fallback: search for price in text
                text = item.get_text()
                match = re.search(r"([\d,]+)\s*円", text)
                if match:
                    price_jpy = self._parse_price(match.group(1))

            if not price_jpy:
                return None

            # Image
            img = item.find("img", src=True)
            image_url = img["src"] if img else ""

            return self._make_listing(
                source_id=source_id,
                category=category,
                title=title,
                price_jpy=price_jpy,
                url=href,
                image_url=image_url,
            )
        except Exception:
            logger.debug("Failed to parse Yahoo Auction item", exc_info=True)
            return None

    @staticmethod
    def _parse_price(text: str) -> int:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
