from __future__ import annotations

import math

from src.config import CONFIG, USD_JPY_RATE_OVERRIDE


async def get_usd_jpy_rate() -> float:
    """Fetch current USD/JPY exchange rate. Falls back to config override or 150."""
    if USD_JPY_RATE_OVERRIDE:
        return float(USD_JPY_RATE_OVERRIDE)

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Free public API, no key required
            resp = await client.get(
                "https://open.er-api.com/v6/latest/USD",
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            rate = data.get("rates", {}).get("JPY", 0.0)
            if rate > 0:
                return float(rate)
    except Exception:
        pass

    # Secondary fallback
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.frankfurter.app/latest?from=USD&to=JPY",
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            rate = data.get("rates", {}).get("JPY", 0.0)
            if rate > 0:
                return float(rate)
    except Exception:
        pass

    return 150.0  # Last-resort fallback


def calculate_ebay_price(
    mercari_price_jpy: int,
    usd_jpy_rate: float,
    shipping_cost_usd: float | None = None,
) -> float:
    """
    Calculate the eBay listing price in USD given a Mercari price.

    Formula ensures the desired net profit margin after eBay fees:
      net_revenue = ebay_price × (1 - ebay_fee_rate)
      cost_jpy    = mercari_price_jpy
      cost_usd    = cost_jpy / usd_jpy_rate
      target:     net_revenue ≥ cost_usd × (1 + markup_rate)

    Solving for ebay_price:
      ebay_price = (cost_usd × (1 + markup_rate)) / (1 - ebay_fee_rate)
    """
    pricing = CONFIG.get("pricing", {})
    markup_rate = pricing.get("markup_rate", 0.35)
    ebay_fee_rate = pricing.get("ebay_fee_rate", 0.1325)
    min_price = pricing.get("min_ebay_price_usd", 5.0)

    if shipping_cost_usd is None:
        shipping_cost_usd = pricing.get("shipping_cost_usd", 15.0)

    cost_usd = mercari_price_jpy / usd_jpy_rate

    # Price must cover: cost + markup, after eBay fees are deducted
    raw_price = (cost_usd * (1 + markup_rate)) / (1 - ebay_fee_rate)

    # Round up to nearest $0.99 (e.g. $24.99, $39.99) - standard eBay pricing
    dollars = math.ceil(raw_price)
    ebay_price = float(dollars) - 0.01

    return max(ebay_price, min_price)


def price_changed_significantly(
    old_price_jpy: int, new_price_jpy: int
) -> bool:
    """Return True if the price change exceeds the notification threshold."""
    if old_price_jpy == 0:
        return new_price_jpy > 0
    threshold = CONFIG.get("pricing", {}).get("notify_price_change_threshold", 0.05)
    change_rate = abs(new_price_jpy - old_price_jpy) / old_price_jpy
    return change_rate >= threshold
