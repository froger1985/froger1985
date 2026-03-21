from __future__ import annotations

import logging

from src.config import CONFIG
from src.db.models import AnalysisResult, SourceListing
from src.utils.currency import usd_to_jpy

logger = logging.getLogger(__name__)


def estimate_shipping_jpy(category: str, title: str = "") -> int:
    """Estimate international shipping cost based on category."""
    shipping = CONFIG["shipping"]

    if category == "game":
        return shipping["game_ems_jpy"]

    # Audio: estimate based on keywords in title
    title_lower = title.lower()
    large_keywords = ["amp", "アンプ", "speaker", "スピーカー", "turntable",
                      "レコードプレーヤー", "cassette deck", "カセットデッキ"]
    if any(kw in title_lower for kw in large_keywords):
        return shipping["audio_large_ems_jpy"]

    return shipping["audio_small_ems_jpy"]


def calculate_profit(
    listing: SourceListing,
    ebay_avg_price_usd: float,
    ebay_sold_count: int,
    usd_jpy_rate: float,
) -> AnalysisResult:
    """Calculate expected profit for a sourced item.

    Profit = eBay selling price (JPY) - buy price - shipping - eBay fees - payment fees
    """
    cfg = CONFIG["profit"]

    # Convert eBay average price to JPY
    selling_price_jpy = usd_to_jpy(ebay_avg_price_usd, usd_jpy_rate)

    # Costs
    buy_price = listing.price_jpy
    shipping = estimate_shipping_jpy(listing.category, listing.title)

    # eBay final value fee
    ebay_fee = int(selling_price_jpy * cfg["ebay_fee_rate"])

    # Payment processing fee
    payment_fee = int(selling_price_jpy * cfg["payment_fee_rate"] + cfg["payment_fee_fixed_usd"] * usd_jpy_rate)

    # Net profit
    profit = selling_price_jpy - buy_price - shipping - ebay_fee - payment_fee

    # Profit rate (relative to buy price)
    profit_rate = profit / buy_price if buy_price > 0 else 0.0

    # Recommendation
    min_rate = cfg["min_profit_rate"]
    min_sold = cfg["min_ebay_sold_count"]

    if profit_rate >= min_rate and ebay_sold_count >= min_sold:
        recommendation = "buy"
    elif profit_rate >= min_rate * 0.7 and ebay_sold_count >= min_sold:
        recommendation = "watch"
    else:
        recommendation = "skip"

    logger.info(
        "Profit analysis: %s | buy=¥%d sell=¥%d profit=¥%d (%.0f%%) → %s",
        listing.title[:40], buy_price, selling_price_jpy, profit, profit_rate * 100,
        recommendation,
    )

    return AnalysisResult(
        source_listing_id=listing.id or 0,
        ebay_avg_price_usd=ebay_avg_price_usd,
        ebay_sold_count=ebay_sold_count,
        estimated_shipping_jpy=shipping,
        ebay_fee_rate=cfg["ebay_fee_rate"],
        estimated_profit_jpy=profit,
        profit_rate=profit_rate,
        recommendation=recommendation,
    )
