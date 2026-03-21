from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# Cached exchange rate
_cached_rate: float = 0.0
_cached_at: datetime = datetime.min
_CACHE_TTL = timedelta(hours=6)

# Fallback rate if API is unavailable
_FALLBACK_RATE = 150.0  # 1 USD = 150 JPY (update as needed)


async def get_usd_to_jpy() -> float:
    """Get current USD to JPY exchange rate. Cached for 6 hours."""
    global _cached_rate, _cached_at

    if _cached_rate > 0 and datetime.now() - _cached_at < _CACHE_TTL:
        return _cached_rate

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.exchangerate-api.com/v4/latest/USD"
            )
            resp.raise_for_status()
            data = resp.json()
            rate = data["rates"]["JPY"]
            _cached_rate = rate
            _cached_at = datetime.now()
            logger.info("Exchange rate updated: 1 USD = %.2f JPY", rate)
            return rate
    except Exception:
        logger.warning("Failed to fetch exchange rate, using fallback %.0f", _FALLBACK_RATE)
        return _cached_rate if _cached_rate > 0 else _FALLBACK_RATE


def usd_to_jpy(usd: float, rate: float) -> int:
    """Convert USD to JPY."""
    return int(usd * rate)


def jpy_to_usd(jpy: int, rate: float) -> float:
    """Convert JPY to USD."""
    return round(jpy / rate, 2) if rate > 0 else 0.0
