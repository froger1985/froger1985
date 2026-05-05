from __future__ import annotations

import logging
import textwrap
from xml.etree import ElementTree as ET

import httpx

from src.config import (
    CONFIG,
    EBAY_APP_ID,
    EBAY_CERT_ID,
    EBAY_DEV_ID,
    EBAY_SELLER_EMAIL,
    EBAY_USER_TOKEN,
)

logger = logging.getLogger(__name__)

_TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
_API_VERSION = "1249"

# eBay condition text → ConditionID
_CONDITION_MAP: dict[str, int] = {
    "新品、未使用": 1000,
    "未使用に近い": 1500,
    "目立った傷や汚れなし": 4000,
    "やや傷や汚れあり": 5000,
    "傷や汚れあり": 6000,
    "全体的に状態が悪い": 7000,
}


def _condition_id(condition_text: str) -> int:
    cfg_map = CONFIG.get("condition_map", {})
    if condition_text in cfg_map:
        return int(cfg_map[condition_text])
    return _CONDITION_MAP.get(condition_text, 3000)  # default: Used


def _base_xml(call_name: str, body_xml: str) -> str:
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <{call_name}Request xmlns="urn:ebay:apis:eBLBaseComponents">
          <RequesterCredentials>
            <eBayAuthToken>{EBAY_USER_TOKEN}</eBayAuthToken>
          </RequesterCredentials>
          <ErrorLanguage>en_US</ErrorLanguage>
          <WarningLevel>High</WarningLevel>
          {body_xml}
        </{call_name}Request>
    """)


def _trading_headers(call_name: str) -> dict:
    return {
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-SITEID": str(CONFIG.get("ebay", {}).get("site_id", 0)),
        "X-EBAY-API-COMPATIBILITY-LEVEL": _API_VERSION,
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml;charset=utf-8",
    }


def _parse_response(xml_text: str, call_name: str) -> dict:
    """Parse eBay Trading API XML response. Raises on Failure ack."""
    try:
        root = ET.fromstring(xml_text)
        ns = {"e": "urn:ebay:apis:eBLBaseComponents"}

        def find(path: str) -> str:
            el = root.find(path, ns)
            return el.text or "" if el is not None else ""

        ack = find("e:Ack")
        if ack not in ("Success", "Warning"):
            errors = root.findall(".//e:Errors", ns)
            msgs = [
                f"[{e.findtext('e:SeverityCode', namespaces=ns)}] "
                f"{e.findtext('e:LongMessage', namespaces=ns) or e.findtext('e:ShortMessage', namespaces=ns)}"
                for e in errors
            ]
            raise RuntimeError(f"eBay {call_name} failed ({ack}): " + " | ".join(msgs))

        return {"ack": ack, "root": root, "ns": ns}
    except ET.ParseError as exc:
        raise RuntimeError(f"Failed to parse eBay response XML: {exc}") from exc


class EbayTradingClient:
    """Thin wrapper around eBay Trading API for Fixed Price listing management."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    def _check_credentials(self):
        missing = [k for k, v in {
            "EBAY_APP_ID": EBAY_APP_ID,
            "EBAY_DEV_ID": EBAY_DEV_ID,
            "EBAY_CERT_ID": EBAY_CERT_ID,
            "EBAY_USER_TOKEN": EBAY_USER_TOKEN,
        }.items() if not v]
        if missing:
            raise RuntimeError(
                f"eBay credentials not configured: {', '.join(missing)}. "
                "Set them in your .env file."
            )

    async def add_fixed_price_item(
        self,
        title: str,
        description: str,
        price_usd: float,
        category_id: str,
        condition_text: str,
        image_url: str,
        shipping_cost_usd: float,
    ) -> str:
        """
        Create a Fixed Price listing on eBay.
        Returns the new eBay ItemID on success.
        """
        self._check_credentials()

        ebay_cfg = CONFIG.get("ebay", {})
        condition_id = _condition_id(condition_text)

        # Build ship-to locations XML
        ship_to_xml = "\n    ".join(
            f"<ShipToLocations>{loc}</ShipToLocations>"
            for loc in ebay_cfg.get("ship_to_locations", ["US", "Worldwide"])
        )

        # Truncate title to eBay's 80-char limit
        safe_title = title[:80]

        # Picture URL (only include if non-empty; eBay rejects empty PictureURL)
        picture_xml = ""
        if image_url:
            picture_xml = f"""
    <PictureDetails>
      <PictureURL>{image_url}</PictureURL>
    </PictureDetails>"""

        # PayPal / payment line removed (eBay managed payments since 2021)
        body = f"""
  <Item>
    <Title>{safe_title}</Title>
    <Description><![CDATA[{description}]]></Description>
    <PrimaryCategory>
      <CategoryID>{category_id}</CategoryID>
    </PrimaryCategory>
    <StartPrice>{price_usd:.2f}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>
    <Country>{ebay_cfg.get('country', 'JP')}</Country>
    <Currency>USD</Currency>
    <DispatchTimeMax>{ebay_cfg.get('dispatch_time_max', 7)}</DispatchTimeMax>
    <ListingDuration>{ebay_cfg.get('listing_duration', 'GTC')}</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    {picture_xml}
    <Quantity>1</Quantity>
    {ship_to_xml}
    <ShippingDetails>
      <ShippingType>Flat</ShippingType>
      <ShippingServiceOptions>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>EconomyInternationalShipping</ShippingService>
        <ShippingServiceCost currencyID="USD">{shipping_cost_usd:.2f}</ShippingServiceCost>
      </ShippingServiceOptions>
    </ShippingDetails>
    <Site>US</Site>
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption>
    </ReturnPolicy>
  </Item>"""

        xml_body = _base_xml("AddFixedPriceItem", body)
        resp = await self.client.post(
            _TRADING_API_URL,
            content=xml_body.encode("utf-8"),
            headers=_trading_headers("AddFixedPriceItem"),
        )
        resp.raise_for_status()

        parsed = _parse_response(resp.text, "AddFixedPriceItem")
        root, ns = parsed["root"], parsed["ns"]
        item_id = root.findtext("e:ItemID", namespaces=ns) or ""
        if not item_id:
            raise RuntimeError("AddFixedPriceItem succeeded but returned no ItemID")

        logger.info("eBay listing created: ItemID=%s title=%s", item_id, safe_title[:50])
        return item_id

    async def end_fixed_price_item(self, ebay_item_id: str, reason: str = "NotAvailable") -> None:
        """
        End (de-list) a Fixed Price listing.
        reason: 'NotAvailable' | 'LostOrBroken' | 'OtherListingError'
        """
        self._check_credentials()

        body = f"""
  <EndingReason>{reason}</EndingReason>
  <ItemID>{ebay_item_id}</ItemID>"""

        xml_body = _base_xml("EndFixedPriceItem", body)
        resp = await self.client.post(
            _TRADING_API_URL,
            content=xml_body.encode("utf-8"),
            headers=_trading_headers("EndFixedPriceItem"),
        )
        resp.raise_for_status()
        _parse_response(resp.text, "EndFixedPriceItem")
        logger.info("eBay listing ended: ItemID=%s reason=%s", ebay_item_id, reason)

    async def revise_fixed_price_item(
        self, ebay_item_id: str, new_price_usd: float
    ) -> None:
        """Update the price of an active Fixed Price listing."""
        self._check_credentials()

        body = f"""
  <Item>
    <ItemID>{ebay_item_id}</ItemID>
    <StartPrice>{new_price_usd:.2f}</StartPrice>
  </Item>"""

        xml_body = _base_xml("ReviseFixedPriceItem", body)
        resp = await self.client.post(
            _TRADING_API_URL,
            content=xml_body.encode("utf-8"),
            headers=_trading_headers("ReviseFixedPriceItem"),
        )
        resp.raise_for_status()
        _parse_response(resp.text, "ReviseFixedPriceItem")
        logger.info("eBay price updated: ItemID=%s new_price=$%.2f", ebay_item_id, new_price_usd)

    async def get_item(self, ebay_item_id: str) -> dict:
        """Fetch basic info about an eBay listing (used for verification)."""
        self._check_credentials()

        body = f"<ItemID>{ebay_item_id}</ItemID>"
        xml_body = _base_xml("GetItem", body)
        resp = await self.client.post(
            _TRADING_API_URL,
            content=xml_body.encode("utf-8"),
            headers=_trading_headers("GetItem"),
        )
        resp.raise_for_status()
        parsed = _parse_response(resp.text, "GetItem")
        root, ns = parsed["root"], parsed["ns"]

        listing_status = root.findtext(".//e:ListingStatus", namespaces=ns) or ""
        selling_state = root.findtext(".//e:SellingState", namespaces=ns) or ""
        current_price = root.findtext(".//e:CurrentPrice", namespaces=ns) or "0"

        return {
            "item_id": ebay_item_id,
            "listing_status": listing_status,
            "selling_state": selling_state,
            "current_price_usd": float(current_price),
        }
