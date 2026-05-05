from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrackedItem:
    """A Mercari liked item that we're tracking and listing on eBay."""
    mercari_id: str
    title: str
    mercari_price_jpy: int
    mercari_url: str
    # 'on_sale', 'sold_out', 'deleted', 'unknown'
    mercari_status: str = "on_sale"
    image_url: str = ""
    condition: str = ""
    # eBay listing state
    ebay_listing_id: str = ""
    ebay_price_usd: float = 0.0
    # 'pending', 'active', 'ended', 'error', 'skipped'
    ebay_status: str = "pending"
    last_checked_at: datetime = field(default_factory=datetime.now)
    listed_at: datetime | None = None
    notes: str = ""
    id: int | None = None


@dataclass
class PriceHistory:
    """Records each time a tracked item's price changes."""
    tracked_item_id: int
    mercari_old_price_jpy: int
    mercari_new_price_jpy: int
    ebay_old_price_usd: float
    ebay_new_price_usd: float
    changed_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass
class SyncLog:
    """Summary record of each sync run."""
    run_at: datetime = field(default_factory=datetime.now)
    items_checked: int = 0
    sold_out_count: int = 0
    price_updated_count: int = 0
    newly_listed_count: int = 0
    errors: int = 0
    duration_sec: float = 0.0
    id: int | None = None
