from __future__ import annotations

import math

from src.config import CONFIG

# メルカリの状態表記 → eBay condition ID
CONDITION_MAP: dict[str, int] = {
    "新品、未使用": 1000,
    "未使用に近い": 1500,
    "目立った傷や汚れなし": 3000,
    "やや傷や汚れあり": 4000,
    "傷や汚れあり": 5000,
    "全体的に状態が悪い": 7000,
}

CONDITION_LABEL: dict[int, str] = {
    1000: "New",
    1500: "New other",
    3000: "Used",
    4000: "Good",
    5000: "Acceptable",
    7000: "For parts",
}


def calculate_ebay_price(price_jpy: int, usd_jpy_rate: float) -> float:
    """Calculate eBay listing price in USD.

    Formula:
      listing_price = (total_cost * (1 + margin) + payment_fixed) / (1 - ebay_fee - payment_fee)

    total_cost = mercari_price_in_usd + international_shipping_usd
    Result is rounded to X.99 pricing.
    """
    cfg_profit = CONFIG["profit"]
    cfg_listing = CONFIG["listing"]

    cost_usd = price_jpy / usd_jpy_rate
    shipping_usd = cfg_listing["international_shipping_usd"]
    total_cost = cost_usd + shipping_usd

    margin = cfg_listing["profit_margin"]
    ebay_fee = cfg_profit["ebay_fee_rate"]
    payment_fee = cfg_profit["payment_fee_rate"]
    payment_fixed = cfg_profit["payment_fee_fixed_usd"]

    raw = (total_cost * (1 + margin) + payment_fixed) / (1 - ebay_fee - payment_fee)
    return math.floor(raw) + 0.99


def get_ebay_condition_id(condition_jp: str) -> int:
    """Map Japanese Mercari condition string to eBay condition ID."""
    return CONDITION_MAP.get(condition_jp, 3000)


def condition_label(condition_id: int) -> str:
    return CONDITION_LABEL.get(condition_id, "Used")
