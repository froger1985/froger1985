from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SourceListing:
    source: str          # 'hardoff', 'yahoo_auction', 'mercari', etc.
    source_id: str       # ID on the source site
    category: str        # 'game' or 'audio'
    title: str
    price_jpy: int
    url: str
    image_url: str = ""
    condition: str = ""
    found_at: datetime = field(default_factory=datetime.now)
    status: str = "new"  # 'new', 'analyzed', 'alerted', 'purchased', 'skipped'
    id: int | None = None
    description: str = ""
    extra_images: str = ""   # JSON array of additional image URLs
    stock_state: str = ""    # e.g. 'on_sale', 'sold_out', 'trading'


@dataclass
class EbaySold:
    search_query: str
    sold_price_usd: float
    item_title: str = ""
    sold_date: str = ""
    item_url: str = ""
    fetched_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass
class AnalysisResult:
    source_listing_id: int
    ebay_avg_price_usd: float
    ebay_sold_count: int
    estimated_shipping_jpy: int
    ebay_fee_rate: float
    estimated_profit_jpy: int
    profit_rate: float
    recommendation: str  # 'buy', 'watch', 'skip'
    analyzed_at: datetime = field(default_factory=datetime.now)
    id: int | None = None


@dataclass
class WatchlistItem:
    category: str        # 'game' or 'audio'
    keyword: str
    min_profit_rate: float = 0.30
    max_buy_price_jpy: int | None = None
    enabled: bool = True
    id: int | None = None
