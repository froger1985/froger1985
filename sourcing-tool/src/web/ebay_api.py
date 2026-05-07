from __future__ import annotations

import re

import httpx

_PROD_BASE = "https://api.ebay.com"
_SBX_BASE = "https://api.sandbox.ebay.com"

CONDITION_ENUM: dict[int, str] = {
    1000: "NEW",
    1500: "LIKE_NEW",
    3000: "USED_VERY_GOOD",
    4000: "USED_GOOD",
    5000: "USED_ACCEPTABLE",
    7000: "FOR_PARTS_OR_NOT_WORKING",
}


class EbayListingAPI:
    def __init__(self, auth):
        self.auth = auth
        self.base = _SBX_BASE if getattr(auth, "is_sandbox", False) else _PROD_BASE

    async def _headers(self) -> dict:
        token = await self.auth.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-US",
        }

    async def get_category_suggestions(self, query: str) -> list[dict]:
        token = await self.auth.get_app_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(
                f"{self.base}/commerce/taxonomy/v1/category_tree/0/get_category_suggestions",
                headers=headers,
                params={"q": query},
            )
        if resp.status_code != 200:
            print(f"[eBay category] {resp.status_code}: {resp.text[:300]}")
            return []
        suggestions = resp.json().get("categorySuggestions", [])[:5]
        return [
            {
                "id": s["category"]["categoryId"],
                "name": " > ".join(
                    [a["categoryName"] for a in reversed(s.get("categoryTreeNodeAncestors", []))]
                    + [s["category"]["categoryName"]]
                ),
            }
            for s in suggestions
        ]

    async def _ensure_merchant_location(self, c: httpx.AsyncClient, headers: dict) -> str:
        key = "JP01"
        r = await c.get(f"{self.base}/sell/inventory/v1/location/{key}", headers=headers)
        if r.status_code == 200:
            print(f"[eBay] location {key} already exists")
            return key
        loc_headers = {
            "Authorization": headers["Authorization"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "location": {
                "address": {
                    "country": "JP",
                    "city": "Tokyo",
                    "postalCode": "1000001",
                }
            },
            "merchantLocationStatus": "ENABLED",
            "name": "Japan",
        }
        print(f"[eBay] creating location with body: {body}")
        r = await c.post(
            f"{self.base}/sell/inventory/v1/location/{key}",
            headers=loc_headers,
            json=body,
        )
        print(f"[eBay] create location: {r.status_code} {r.text[:300]}")
        return key

    async def get_policies(self) -> dict[str, list]:
        headers = await self._headers()
        result: dict[str, list] = {}
        async with httpx.AsyncClient(timeout=10.0) as c:
            for ptype in ("fulfillment", "payment", "return"):
                resp = await c.get(
                    f"{self.base}/sell/account/v1/{ptype}_policy",
                    headers=headers,
                    params={"marketplace_id": "EBAY_US"},
                )
                key = f"{ptype}Policies"
                result[ptype] = resp.json().get(key, []) if resp.status_code == 200 else []
        return result

    async def create_listing(
        self,
        sku: str,
        title: str,
        description: str,
        price_usd: float,
        condition_id: int,
        category_id: str,
        image_urls: list[str],
        fulfillment_policy_id: str,
        payment_policy_id: str,
        return_policy_id: str,
    ) -> dict:
        headers = await self._headers()
        condition = CONDITION_ENUM.get(condition_id, "USED_GOOD")

        inventory_body = {
            "availability": {
                "shipToLocationAvailability": {"quantity": 1}
            },
            "condition": condition,
            "product": {
                "title": title[:80],
                "description": description or title,
                "aspects": {},
            },
        }
        if image_urls:
            inventory_body["product"]["imageUrls"] = image_urls[:12]

        async with httpx.AsyncClient(timeout=30.0) as c:
            location_key = await self._ensure_merchant_location(c, headers)

            # Step 1: Create inventory item
            print(f"[eBay] PUT inventory_item SKU={sku} condition={condition} images={len(image_urls)}")
            r = await c.put(
                f"{self.base}/sell/inventory/v1/inventory_item/{sku}",
                headers=headers,
                json=inventory_body,
            )
            print(f"[eBay] inventory response: {r.status_code} {r.text[:300]}")
            if r.status_code not in (200, 204):
                return {"success": False, "error": f"inventory: {r.status_code} {r.text[:200]}"}

            # Step 2: Create or update offer
            offer_body = {
                "sku": sku,
                "marketplaceId": "EBAY_US",
                "format": "FIXED_PRICE",
                "availableQuantity": 1,
                "categoryId": category_id,
                "listingDescription": description or title,
                "merchantLocationKey": location_key,
                "listingPolicies": {
                    "fulfillmentPolicyId": fulfillment_policy_id,
                    "paymentPolicyId": payment_policy_id,
                    "returnPolicyId": return_policy_id,
                },
                "pricingSummary": {
                    "price": {"currency": "USD", "value": f"{price_usd:.2f}"}
                },
            }
            r = await c.post(f"{self.base}/sell/inventory/v1/offer", headers=headers, json=offer_body)
            if r.status_code in (200, 201):
                offer_id = r.json()["offerId"]
            elif r.status_code == 400 and any(
                e.get("errorId") == 25002 for e in r.json().get("errors", [])
            ):
                # Offer already exists — get its ID from error params or via GET
                offer_id = next(
                    (p.get("value") for e in r.json().get("errors", [])
                     for p in e.get("parameters", []) if p.get("name") == "offerId"),
                    None,
                )
                if not offer_id:
                    gr = await c.get(
                        f"{self.base}/sell/inventory/v1/offer",
                        headers=headers,
                        params={"sku": sku},
                    )
                    offer_id = gr.json().get("offers", [{}])[0].get("offerId")
                if not offer_id:
                    return {"success": False, "error": "offer: cannot retrieve existing offerId"}
                # Delete stale offer and recreate to avoid cached category/aspects state
                dr = await c.delete(
                    f"{self.base}/sell/inventory/v1/offer/{offer_id}",
                    headers=headers,
                )
                print(f"[eBay] deleted stale offer {offer_id}: {dr.status_code}")
                r = await c.post(f"{self.base}/sell/inventory/v1/offer", headers=headers, json=offer_body)
                if r.status_code not in (200, 201):
                    return {"success": False, "error": f"offer recreate: {r.status_code} {r.text[:200]}"}
                offer_id = r.json()["offerId"]
                print(f"[eBay] recreated offer {offer_id}")
            else:
                return {"success": False, "error": f"offer: {r.status_code} {r.text[:200]}"}

            # Step 3: Publish offer (loop to fill missing item specifics one at a time)
            aspects: dict[str, list[str]] = {}
            for _ in range(10):
                r = await c.post(
                    f"{self.base}/sell/inventory/v1/offer/{offer_id}/publish",
                    headers=headers,
                )
                if r.status_code == 200:
                    break
                if r.status_code != 400:
                    break
                new_aspect = None
                for e in r.json().get("errors", []):
                    m = re.search(r"item specific (.+?) is missing", e.get("message", ""))
                    if m:
                        new_aspect = m.group(1)
                        break
                if not new_aspect:
                    break
                aspects[new_aspect] = [title[:65]]
                print(f"[eBay] adding missing aspect '{new_aspect}', total aspects: {list(aspects)}")
                inventory_body["product"]["aspects"] = aspects
                await c.put(
                    f"{self.base}/sell/inventory/v1/inventory_item/{sku}",
                    headers=headers,
                    json=inventory_body,
                )
            if r.status_code != 200:
                return {"success": False, "error": f"publish: {r.status_code} {r.text[:200]}"}
            return {"success": True, "listing_id": r.json().get("listingId", "")}
