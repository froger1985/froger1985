from __future__ import annotations

import logging

import httpx

from src.config import CONFIG, LINE_NOTIFY_TOKEN, SLACK_WEBHOOK_URL
from src.db.models import AnalysisResult, SourceListing

logger = logging.getLogger(__name__)


def format_alert(listing: SourceListing, analysis: AnalysisResult, rate: float) -> str:
    """Format an alert message."""
    highlight = CONFIG["alerts"].get("highlight_profit_jpy", 10000)
    prefix = "🔥 HIGH PROFIT" if analysis.estimated_profit_jpy >= highlight else "💰 Profitable"

    return (
        f"{prefix} [{listing.category.upper()}]\n"
        f"  {listing.title}\n"
        f"  Source: {listing.source} | ¥{listing.price_jpy:,}\n"
        f"  eBay avg: ${analysis.ebay_avg_price_usd:.2f} ({analysis.ebay_sold_count} sold)\n"
        f"  Est. profit: ¥{analysis.estimated_profit_jpy:,} ({analysis.profit_rate:.0%})\n"
        f"  Link: {listing.url}"
    )


async def send_alert(
    listing: SourceListing, analysis: AnalysisResult, rate: float
) -> list[str]:
    """Send alert to all configured channels. Returns list of channels sent to."""
    if not CONFIG["alerts"].get("enabled", True):
        return []

    message = format_alert(listing, analysis, rate)
    channels = CONFIG["alerts"].get("channels", ["console"])
    sent: list[str] = []

    for channel in channels:
        try:
            if channel == "console":
                print(f"\n{'='*60}\n{message}\n{'='*60}")
                sent.append("console")

            elif channel == "slack" and SLACK_WEBHOOK_URL:
                await _send_slack(message)
                sent.append("slack")

            elif channel == "line" and LINE_NOTIFY_TOKEN:
                await _send_line(message)
                sent.append("line")

            else:
                logger.warning("Alert channel '%s' not configured", channel)
        except Exception:
            logger.exception("Failed to send %s alert", channel)

    return sent


async def _send_slack(message: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            SLACK_WEBHOOK_URL,
            json={"text": message},
        )
        resp.raise_for_status()
    logger.info("Slack alert sent")


async def _send_line(message: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"},
            data={"message": message},
        )
        resp.raise_for_status()
    logger.info("LINE alert sent")
