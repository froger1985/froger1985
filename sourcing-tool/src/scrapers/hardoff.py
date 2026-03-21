from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from src.db.models import SourceListing
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://netmall.hardoff.co.jp"
SEARCH_URL = f"{BASE_URL}/search"


class HardOffScraper(BaseScraper):
    """Scraper for Hard Off Net Mall (netmall.hardoff.co.jp)."""

    source_name = "hardoff"

    async def search(self, keyword: str, category: str = "game") -> list[SourceListing]:
        listings: list[SourceListing] = []
        page = 1

        while len(listings) < self.max_results:
            try:
                resp = await self._get(SEARCH_URL, params={
                    "q": keyword,
                    "page": page,
                })
            except Exception:
                logger.exception("Hard Off search failed for '%s' page %d", keyword, page)
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".itemList__item, .p-product-list__item, .item-list-item")

            if not items:
                # Try alternative selectors
                items = soup.select("[class*='item']")
                items = [i for i in items if i.find("a") and i.find(string=re.compile(r"¥|円|\d{3,}"))]

            if not items:
                break

            for item in items:
                listing = self._parse_item(item, category)
                if listing:
                    listings.append(listing)

            # Check if there's a next page
            next_link = soup.select_one("a[rel='next'], .pagination__next, .next")
            if not next_link:
                break
            page += 1

        logger.info("Hard Off: found %d items for '%s'", len(listings), keyword)
        return listings[:self.max_results]

    def _parse_item(self, item, category: str) -> SourceListing | None:
        try:
            # Find the link
            link = item.find("a", href=True)
            if not link:
                return None

            href = link["href"]
            if not href.startswith("http"):
                href = BASE_URL + href

            # Extract item ID from URL
            source_id = href.rstrip("/").split("/")[-1]

            # Find title
            title_el = (
                item.select_one(".itemList__title, .p-product-list__title, [class*='title'], h3, h2")
                or link
            )
            title = title_el.get_text(strip=True)
            if not title:
                return None

            # Find price
            price_text = ""
            price_el = item.select_one(".itemList__price, [class*='price'], .price")
            if price_el:
                price_text = price_el.get_text(strip=True)
            else:
                # Search for price pattern in full text
                full_text = item.get_text()
                match = re.search(r"[¥￥]?\s*([\d,]+)\s*円?", full_text)
                if match:
                    price_text = match.group(1)

            price_jpy = self._parse_price(price_text)
            if not price_jpy:
                return None

            # Find image
            img = item.find("img", src=True)
            image_url = img["src"] if img else ""
            if image_url and not image_url.startswith("http"):
                image_url = BASE_URL + image_url

            # Find condition
            condition = ""
            cond_el = item.select_one("[class*='condition'], [class*='rank']")
            if cond_el:
                condition = cond_el.get_text(strip=True)

            return self._make_listing(
                source_id=source_id,
                category=category,
                title=title,
                price_jpy=price_jpy,
                url=href,
                image_url=image_url,
                condition=condition,
            )
        except Exception:
            logger.debug("Failed to parse Hard Off item", exc_info=True)
            return None

    @staticmethod
    def _parse_price(text: str) -> int:
        if not text:
            return 0
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
