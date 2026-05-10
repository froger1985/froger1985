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

_CONDITION_FALLBACK: dict[str, str] = {
    "USED_VERY_GOOD": "USED_EXCELLENT",
    "USED_EXCELLENT": "USED_GOOD",
    "USED_GOOD": "USED_ACCEPTABLE",
}

_CONDITION_LABELS: dict[str, str] = {
    "NEW": "新品 (New)",
    "LIKE_NEW": "未使用に近い (Like New)",
    "NEW_OTHER": "新品・その他 (New Other)",
    "NEW_WITH_DEFECTS": "新品・難あり (New with defects)",
    "MANUFACTURER_REFURBISHED": "メーカー整備済み",
    "CERTIFIED_REFURBISHED": "認定整備済み",
    "EXCELLENT_REFURBISHED": "整備済み・非常に良い",
    "VERY_GOOD_REFURBISHED": "整備済み・良い",
    "GOOD_REFURBISHED": "整備済み・普通",
    "USED_EXCELLENT": "中古・非常に良い (Excellent)",
    "USED_VERY_GOOD": "目立った傷や汚れなし (Used)",
    "USED_GOOD": "中古・やや傷あり (Good)",
    "USED_ACCEPTABLE": "中古・傷・汚れあり (Acceptable)",
    "FOR_PARTS_OR_NOT_WORKING": "ジャンク (For Parts)",
}

# Metadata API の conditionId → 日本語ラベル
_CONDITION_ID_LABELS: dict[str, str] = {
    "1000": "新品、未使用 (New)",
    "1500": "未使用に近い (New other)",
    "2000": "認定整備済み (Certified Refurbished)",
    "2500": "出品者整備済み (Seller Refurbished)",
    "3000": "目立った傷や汚れなし (Used)",
    "4000": "やや傷や汚れあり (Good)",
    "5000": "傷や汚れあり (Acceptable)",
    "7000": "全体的に状態が悪い (For Parts)",
}


class EbayListingAPI:
    def __init__(self, auth):
        self.auth = auth
        self.base = _SBX_BASE if getattr(auth, "is_sandbox", False) else _PROD_BASE

    async def _headers(self) -> dict:
        token = await self.auth.get_token()
        if not token:
            raise RuntimeError("eBay認証が切れています。再ログインしてください。")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-US",
        }

    async def _get_required_aspects(self, category_id: str, title: str) -> dict[str, list[str]]:
        """Fetch required aspects for a category from the Taxonomy API and return defaults."""
        token = await self.auth.get_app_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(
                f"{self.base}/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category",
                headers=headers,
                params={"category_id": category_id},
            )
        if resp.status_code != 200:
            print(f"[eBay aspects] {resp.status_code}: {resp.text[:200]}")
            return {}
        aspects: dict[str, list[str]] = {}
        for aspect in resp.json().get("aspects", []):
            if not aspect.get("aspectConstraint", {}).get("aspectRequired"):
                continue
            name: str = aspect["localizedAspectName"]
            allowed = [v["localizedValue"] for v in aspect.get("aspectValues", [])]
            name_lower = name.lower()
            if allowed:
                aspects[name] = [allowed[0]]
            elif "country" in name_lower or "region of manufacture" in name_lower:
                aspects[name] = ["Japan"]
            else:
                aspects[name] = [title[:65]]
        print(f"[eBay aspects] required for category {category_id}: {list(aspects)}")
        return aspects

    async def get_valid_conditions(self, category_id: str) -> list[str]:
        """Return human-readable valid condition labels for a category via Sell Metadata API."""
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(
                f"{self.base}/sell/metadata/v1/marketplace/EBAY_US/get_item_condition_policies",
                headers=headers,
                params={"filter": f"categoryId:{category_id}"},
            )
        if resp.status_code != 200:
            print(f"[eBay conditions] {resp.status_code}: {resp.text[:200]}")
            return []
        policies = resp.json().get("itemConditionPolicies", [])
        if not policies:
            return []
        # 対象カテゴリのポリシーを探す。見つからなければ最初のものを使用
        policy = next((p for p in policies if p.get("categoryId") == category_id), policies[0])
        return [
            _CONDITION_ID_LABELS.get(c["conditionId"], c.get("conditionDescription", c["conditionId"]))
            for c in policy.get("itemConditions", [])
        ]

    async def end_listing(self, sku: str) -> dict:
        """Withdraw (end) a published eBay listing by SKU."""
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(
                f"{self.base}/sell/inventory/v1/offer",
                headers=headers,
                params={"sku": sku},
            )
            if r.status_code != 200:
                return {"success": False, "error": f"オファー取得失敗: {r.status_code}"}
            offers = r.json().get("offers", [])
            if not offers:
                return {"success": False, "error": "eBay上にオファーが見つかりません"}
            offer_id = offers[0].get("offerId")
            if not offer_id:
                return {"success": False, "error": "offerId が取得できませんでした"}
            r = await c.post(
                f"{self.base}/sell/inventory/v1/offer/{offer_id}/withdraw",
                headers=headers,
            )
        if r.status_code in (200, 204):
            return {"success": True}
        return {"success": False, "error": f"取り消し失敗: {r.status_code} {r.text[:200]}"}

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

        required_aspects = await self._get_required_aspects(category_id, title)

        inventory_body = {
            "availability": {
                "shipToLocationAvailability": {"quantity": 1}
            },
            "condition": condition,
            "product": {
                "title": title[:80],
                "description": description or title,
                "aspects": required_aspects,
            },
        }
        if image_urls:
            inventory_body["product"]["imageUrls"] = image_urls[:12]

        async with httpx.AsyncClient(timeout=30.0) as c:
            location_key = await self._ensure_merchant_location(c, headers)

            # Link availability to the merchant location explicitly
            inventory_body["availability"]["shipToLocationAvailability"][
                "availabilityDistributions"
            ] = [{"merchantLocationKey": location_key, "quantity": 1}]

            # Step 1: Delete then recreate inventory item to clear stale aspects
            print(f"[eBay] DELETE inventory_item SKU={sku}")
            await c.delete(
                f"{self.base}/sell/inventory/v1/inventory_item/{sku}",
                headers=headers,
            )
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

            # Step 3: Publish offer
            # Loop handles missing item specifics: add the aspect and retry
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

                errors = r.json().get("errors", [])
                print(f"[eBay publish error] status={r.status_code} errors={errors}")

                # Invalid condition → try fallback condition automatically
                if any(
                    e.get("errorId") == 25021
                    and any(p.get("value") == "CONDITION_ID" for p in e.get("parameters", []))
                    for e in errors
                ):
                    fallback = _CONDITION_FALLBACK.get(condition)
                    if fallback:
                        print(f"[eBay] condition {condition} rejected, retrying with {fallback}")
                        condition = fallback
                        inventory_body["condition"] = condition
                        await c.put(
                            f"{self.base}/sell/inventory/v1/inventory_item/{sku}",
                            headers=headers,
                            json=inventory_body,
                        )
                        continue
                    valid = await self.get_valid_conditions(category_id)
                    if valid:
                        labels = [_CONDITION_ID_LABELS.get(v, v) for v in valid]
                        return {
                            "success": False,
                            "error": (
                                f"コンディション「{_CONDITION_LABELS.get(condition, condition)}」は"
                                f"このカテゴリ（ID: {category_id}）では使用できません。\n"
                                f"使用可能なコンディション:\n"
                                + "\n".join(f"  ・{l}" for l in labels)
                            ),
                            "error_type": "invalid_condition",
                            "valid_conditions": valid,
                        }
                    return {
                        "success": False,
                        "error": f"コンディション「{_CONDITION_LABELS.get(condition, condition)}」はこのカテゴリで使用できません。編集画面でコンディションを変更してください。",
                        "error_type": "invalid_condition",
                    }

                # Missing item specific → add it and retry
                new_aspect = None
                for e in errors:
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
                print(f"[eBay] FULL publish error: {r.text}")
                return {"success": False, "error": f"publish: {r.status_code} {r.text[:200]}"}
            return {"success": True, "listing_id": r.json().get("listingId", "")}
