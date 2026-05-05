from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from src.config import CONFIG
from src.db.database import Database
from src.db.models import PriceHistory, SyncLog, TrackedItem
from src.ebay.trading_api import EbayTradingClient
from src.mercari.client import MercariClient
from src.notifier.notifier import (
    notify_listing_error,
    notify_price_change,
    notify_sold_out,
    notify_sync_summary,
)
from src.sync.price_calculator import (
    calculate_ebay_price,
    get_usd_jpy_rate,
    price_changed_significantly,
)

logger = logging.getLogger(__name__)


def _build_description(item: TrackedItem, usd_jpy_rate: float) -> str:
    template = CONFIG.get("description_template", "")
    if not template:
        return (
            f"Item shipped from Japan.\n\n"
            f"Condition: {item.condition or 'Used'}\n"
            f"Original listing: {item.mercari_url}"
        )
    return template.format(
        condition=item.condition or "Used",
        mercari_url=item.mercari_url,
        title=item.title,
        price_jpy=item.mercari_price_jpy,
    )


class Syncer:
    """
    Orchestrates the full Mercari → eBay sync workflow.

    import_favorites(): Pull Mercari liked items and list new ones on eBay.
    add_item(): Add a single item by Mercari URL/ID and list it.
    sync(): Check all active eBay listings for stock/price changes.
    """

    def __init__(self, db: Database, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.mercari = MercariClient()
        self.ebay = EbayTradingClient()

    async def close(self):
        await self.mercari.close()
        await self.ebay.close()

    # ---------------------------------------------------------------
    # Import favorites from Mercari
    # ---------------------------------------------------------------

    async def import_favorites(self, max_pages: int = 10) -> int:
        """
        Fetch Mercari liked items and list any new ones on eBay.
        Returns the count of newly listed items.
        """
        usd_jpy = await get_usd_jpy_rate()
        logger.info("Exchange rate: 1 USD = %.2f JPY", usd_jpy)

        favorites = await self.mercari.get_favorites(max_pages=max_pages)
        if not favorites:
            logger.warning("No favorites returned (token missing or no liked items).")
            return 0

        new_count = 0
        for fav in favorites:
            mercari_id = fav["mercari_id"]
            if self.db.item_exists(mercari_id):
                logger.debug("Already tracking %s - skipping", mercari_id)
                continue

            listed = await self._add_and_list_item(
                mercari_id=mercari_id,
                title=fav["title"],
                price_jpy=fav["price_jpy"],
                url=fav["url"],
                image_url=fav["image_url"],
                condition=fav["condition"],
                usd_jpy=usd_jpy,
            )
            if listed:
                new_count += 1

        logger.info("import_favorites complete: %d new listings", new_count)
        return new_count

    # ---------------------------------------------------------------
    # Add a single item by URL / Mercari ID
    # ---------------------------------------------------------------

    async def add_item(self, mercari_url_or_id: str) -> bool:
        """
        Add a single Mercari item to the tracker and list it on eBay.
        Returns True on success.
        """
        from src.mercari.client import _extract_item_id
        mercari_id = _extract_item_id(mercari_url_or_id)

        if self.db.item_exists(mercari_id):
            logger.info("Item %s is already being tracked", mercari_id)
            return False

        usd_jpy = await get_usd_jpy_rate()

        # Fetch current item details from Mercari
        status_info = await self.mercari.get_item_status(mercari_id)
        if status_info["status"] in ("sold_out", "deleted"):
            logger.warning("Item %s is already %s on Mercari - not adding", mercari_id, status_info["status"])
            return False

        price_jpy = status_info["price_jpy"]
        if not price_jpy:
            logger.warning("Could not fetch price for item %s", mercari_id)
            return False

        # Construct URL
        url = f"https://jp.mercari.com/item/{mercari_id}"

        return await self._add_and_list_item(
            mercari_id=mercari_id,
            title=status_info["title"] or f"Mercari item {mercari_id}",
            price_jpy=price_jpy,
            url=url,
            image_url=status_info["image_url"],
            condition=status_info["condition"],
            usd_jpy=usd_jpy,
        )

    async def _add_and_list_item(
        self,
        mercari_id: str,
        title: str,
        price_jpy: int,
        url: str,
        image_url: str,
        condition: str,
        usd_jpy: float,
    ) -> bool:
        ebay_price = calculate_ebay_price(price_jpy, usd_jpy)
        shipping_usd = CONFIG.get("pricing", {}).get("shipping_cost_usd", 15.0)
        category_id = CONFIG.get("ebay_default_category_id", "99")

        item = TrackedItem(
            mercari_id=mercari_id,
            title=title,
            mercari_price_jpy=price_jpy,
            mercari_url=url,
            mercari_status="on_sale",
            image_url=image_url,
            condition=condition,
            ebay_price_usd=ebay_price,
            ebay_status="pending",
        )
        item_id = self.db.add_item(item)
        item.id = item_id

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would list: '%s' ¥%d → $%.2f (ItemID: dry-run)",
                title[:50], price_jpy, ebay_price,
            )
            return True

        description = _build_description(item, usd_jpy)

        try:
            ebay_item_id = await self.ebay.add_fixed_price_item(
                title=title,
                description=description,
                price_usd=ebay_price,
                category_id=category_id,
                condition_text=condition,
                image_url=image_url,
                shipping_cost_usd=shipping_usd,
            )
            self.db.update_ebay_listed(mercari_id, ebay_item_id, ebay_price)
            logger.info(
                "Listed: '%s' ¥%d → $%.2f  eBay#%s",
                title[:50], price_jpy, ebay_price, ebay_item_id,
            )
            return True

        except Exception as exc:
            error_msg = str(exc)
            self.db.update_ebay_error(mercari_id, error_msg[:200])
            logger.error("Failed to list '%s' on eBay: %s", title[:50], error_msg)
            await notify_listing_error(title, url, error_msg)
            return False

    # ---------------------------------------------------------------
    # 3x/day sync: check all active listings
    # ---------------------------------------------------------------

    async def sync(self) -> SyncLog:
        """
        Check all active eBay listings against current Mercari status/price.
        - Sold out / deleted on Mercari → end eBay listing
        - Price changed on Mercari → update eBay price
        Returns a SyncLog with run statistics.
        """
        start = time.monotonic()
        log = SyncLog(run_at=datetime.now())

        usd_jpy = await get_usd_jpy_rate()
        logger.info("Sync start | rate: 1 USD = %.2f JPY", usd_jpy)

        active_items = self.db.get_active_items()
        log.items_checked = len(active_items)
        logger.info("Active listings to check: %d", len(active_items))

        batch_size = CONFIG.get("sync", {}).get("batch_size", 50)

        for i in range(0, len(active_items), batch_size):
            batch = active_items[i:i + batch_size]
            results = await asyncio.gather(
                *[self._check_item(item, usd_jpy) for item in batch],
                return_exceptions=True,
            )
            for item, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error("Error checking %s: %s", item.mercari_id, result)
                    log.errors += 1
                elif result == "sold_out":
                    log.sold_out_count += 1
                elif result == "price_updated":
                    log.price_updated_count += 1

        log.duration_sec = time.monotonic() - start
        self.db.save_sync_log(log)

        logger.info(
            "Sync done in %.1fs | checked=%d sold_out=%d price_updated=%d errors=%d",
            log.duration_sec, log.items_checked,
            log.sold_out_count, log.price_updated_count, log.errors,
        )

        notify_cfg = CONFIG.get("notifications", {}).get("notify_on", {})
        if notify_cfg.get("sync_summary", False):
            await notify_sync_summary(
                log.items_checked, log.sold_out_count,
                log.price_updated_count, log.newly_listed_count, log.errors,
            )

        return log

    async def _check_item(self, item: TrackedItem, usd_jpy: float) -> str:
        """Check one item. Returns 'sold_out' | 'price_updated' | 'ok'."""
        status_info = await self.mercari.get_item_status(item.mercari_id)
        status = status_info["status"]

        if status in ("sold_out", "deleted"):
            return await self._handle_sold_out(item)

        if status == "unknown":
            logger.warning("Unknown status for %s - skipping", item.mercari_id)
            self.db.touch_checked(item.mercari_id)
            return "ok"

        # Item is still on_sale - check price
        new_price_jpy = status_info["price_jpy"]
        if new_price_jpy and new_price_jpy != item.mercari_price_jpy:
            return await self._handle_price_change(item, new_price_jpy, usd_jpy)

        self.db.touch_checked(item.mercari_id)
        self.db.update_mercari_status(item.mercari_id, "on_sale")
        return "ok"

    async def _handle_sold_out(self, item: TrackedItem) -> str:
        logger.info("Sold out on Mercari: %s '%s'", item.mercari_id, item.title[:50])
        self.db.update_mercari_status(item.mercari_id, "sold_out")

        if not self.dry_run and item.ebay_listing_id:
            try:
                await self.ebay.end_fixed_price_item(
                    item.ebay_listing_id, reason="NotAvailable"
                )
                self.db.update_ebay_ended(item.mercari_id)
            except Exception as exc:
                logger.error(
                    "Failed to end eBay listing %s: %s",
                    item.ebay_listing_id, exc,
                )
                self.db.update_ebay_error(item.mercari_id, str(exc)[:200])

        await notify_sold_out(
            mercari_id=item.mercari_id,
            title=item.title,
            mercari_url=item.mercari_url,
            ebay_listing_id=item.ebay_listing_id,
        )
        return "sold_out"

    async def _handle_price_change(
        self, item: TrackedItem, new_price_jpy: int, usd_jpy: float
    ) -> str:
        new_ebay_price = calculate_ebay_price(new_price_jpy, usd_jpy)
        old_ebay_price = item.ebay_price_usd

        logger.info(
            "Price change: %s ¥%d→¥%d ($%.2f→$%.2f)",
            item.mercari_id, item.mercari_price_jpy, new_price_jpy,
            old_ebay_price, new_ebay_price,
        )

        if not self.dry_run and item.ebay_listing_id:
            try:
                await self.ebay.revise_fixed_price_item(
                    item.ebay_listing_id, new_ebay_price
                )
            except Exception as exc:
                logger.error(
                    "Failed to revise eBay price for %s: %s",
                    item.ebay_listing_id, exc,
                )
                self.db.update_ebay_error(item.mercari_id, str(exc)[:200])
                return "ok"

        # Save price history record
        if item.id:
            self.db.save_price_change(PriceHistory(
                tracked_item_id=item.id,
                mercari_old_price_jpy=item.mercari_price_jpy,
                mercari_new_price_jpy=new_price_jpy,
                ebay_old_price_usd=old_ebay_price,
                ebay_new_price_usd=new_ebay_price,
            ))

        self.db.update_price(item.mercari_id, new_price_jpy, new_ebay_price)

        # Notify only for significant changes
        if price_changed_significantly(item.mercari_price_jpy, new_price_jpy):
            await notify_price_change(
                title=item.title,
                mercari_url=item.mercari_url,
                ebay_listing_id=item.ebay_listing_id,
                old_price_jpy=item.mercari_price_jpy,
                new_price_jpy=new_price_jpy,
                old_ebay_usd=old_ebay_price,
                new_ebay_usd=new_ebay_price,
            )

        return "price_updated"
