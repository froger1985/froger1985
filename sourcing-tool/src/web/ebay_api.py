from __future__ import annotations

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
        }

    async def get_category_suggestions(self, query: str) -> list[dict]:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(
                f"{self.base}/commerce/taxonomy/v1/category_tree/0/get_category_suggestions",
                headers=headers,
                params={"q": query},
            )
        if resp.status_code != 200:
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

        async with httpx.AsyncClient(timeout=30.0) as c:
            # Step 1: Create inventory item
            r = await c.put(
                f"{self.base}/sell/inventory/v1/inventory_item/{sku}",
                headers=headers,
                json={
                    "availability": {
                        "shipToLocationAvailability": {"quantity": 1}
                    },
                    "condition": condition,
                    "product": {
                        "title": title[:80],
                        "description": description or title,
                        "imageUrls": image_urls[:12],
                    },
                },
            )
            if r.status_code not in (200, 204):
                return {"success": False, "error": f"inventory: {r.status_code} {r.text[:200]}"}

            # Step 2: Create offer
            r = await c.post(
                f"{self.base}/sell/inventory/v1/offer",
                headers=headers,
                json={
                    "sku": sku,
                    "marketplaceId": "EBAY_US",
                    "format": "FIXED_PRICE",
                    "availableQuantity": 1,
                    "categoryId": category_id,
                    "listingDescription": description or title,
                    "listingPolicies": {
                        "fulfillmentPolicyId": fulfillment_policy_id,
                        "paymentPolicyId": payment_policy_id,
                        "returnPolicyId": return_policy_id,
                    },
                    "pricingSummary": {
                        "price": {"currency": "USD", "value": f"{price_usd:.2f}"}
                    },
                },
            )
            if r.status_code not in (200, 201):
                return {"success": False, "error": f"offer: {r.status_code} {r.text[:200]}"}
            offer_id = r.json()["offerId"]

            # Step 3: Publish offer
            r = await c.post(
                f"{self.base}/sell/inventory/v1/offer/{offer_id}/publish",
                headers=headers,
            )
            if r.status_code != 200:
                return {"success": False, "error": f"publish: {r.status_code} {r.text[:200]}"}
            return {"success": True, "listing_id": r.json().get("listingId", "")}
