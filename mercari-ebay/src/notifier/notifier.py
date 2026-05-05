from __future__ import annotations

import logging

import httpx

from src.config import CONFIG, LINE_NOTIFY_TOKEN, SLACK_WEBHOOK_URL

logger = logging.getLogger(__name__)


def _channels_enabled() -> list[str]:
    if not CONFIG.get("notifications", {}).get("enabled", True):
        return []
    return CONFIG.get("notifications", {}).get("channels", ["console"])


async def notify_sold_out(
    mercari_id: str,
    title: str,
    mercari_url: str,
    ebay_listing_id: str,
) -> None:
    msg = (
        f"[売切れ → eBay停止]\n"
        f"{title}\n"
        f"Mercari: {mercari_url}\n"
        f"eBay ItemID: {ebay_listing_id}\n"
        f"→ eBay出品を自動停止しました"
    )
    await _send_all(msg, event="sold_out")


async def notify_price_change(
    title: str,
    mercari_url: str,
    ebay_listing_id: str,
    old_price_jpy: int,
    new_price_jpy: int,
    old_ebay_usd: float,
    new_ebay_usd: float,
) -> None:
    direction = "↓ 値下げ" if new_price_jpy < old_price_jpy else "↑ 値上げ"
    change_pct = (new_price_jpy - old_price_jpy) / old_price_jpy * 100
    msg = (
        f"[価格変動 {direction} {change_pct:+.1f}%]\n"
        f"{title}\n"
        f"メルカリ: ¥{old_price_jpy:,} → ¥{new_price_jpy:,}\n"
        f"eBay: ${old_ebay_usd:.2f} → ${new_ebay_usd:.2f}\n"
        f"Mercari: {mercari_url}\n"
        f"eBay ItemID: {ebay_listing_id}"
    )
    event = "price_drop" if new_price_jpy < old_price_jpy else "price_rise"
    await _send_all(msg, event=event)


async def notify_listing_error(
    title: str,
    mercari_url: str,
    error: str,
) -> None:
    msg = (
        f"[eBay出品エラー]\n"
        f"{title}\n"
        f"Mercari: {mercari_url}\n"
        f"エラー: {error}"
    )
    await _send_all(msg, event="listing_error")


async def notify_sync_summary(
    items_checked: int,
    sold_out_count: int,
    price_updated_count: int,
    newly_listed_count: int,
    errors: int,
) -> None:
    msg = (
        f"[Sync完了]\n"
        f"チェック: {items_checked}件 | "
        f"売切れ停止: {sold_out_count}件 | "
        f"価格更新: {price_updated_count}件 | "
        f"新規出品: {newly_listed_count}件 | "
        f"エラー: {errors}件"
    )
    await _send_all(msg, event="sync_summary")


async def _send_all(message: str, event: str) -> None:
    notify_on = CONFIG.get("notifications", {}).get("notify_on", {})
    if not notify_on.get(event, True):
        return

    for channel in _channels_enabled():
        try:
            if channel == "console":
                print(f"\n{'='*55}\n{message}\n{'='*55}")
            elif channel == "slack" and SLACK_WEBHOOK_URL:
                await _send_slack(message)
            elif channel == "line" and LINE_NOTIFY_TOKEN:
                await _send_line(message)
            else:
                logger.debug("Channel '%s' not configured or disabled", channel)
        except Exception:
            logger.exception("Failed to send %s notification via %s", event, channel)


async def _send_slack(message: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(SLACK_WEBHOOK_URL, json={"text": message})
        resp.raise_for_status()
    logger.info("Slack notification sent")


async def _send_line(message: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"},
            data={"message": f"\n{message}"},
        )
        resp.raise_for_status()
    logger.info("LINE notification sent")
