from __future__ import annotations

import json
import socket
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

from src.analysis.ebay_pricing import calculate_ebay_price
from src.config import CONFIG, DB_PATH
from src.db.database import Database
from src.utils.currency import get_usd_to_jpy
from src.web.ebay_api import EbayListingAPI
from src.web.ebay_auth import EbayAuth

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

_auth = EbayAuth()


def _parse_images(listing) -> list[str]:
    imgs: list[str] = []
    if listing.extra_images:
        try:
            imgs = json.loads(listing.extra_images)
        except Exception:
            pass
    if not imgs and listing.image_url:
        imgs = [listing.image_url]
    return imgs


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, tab: str = "active", auth: str = ""):
    db = Database(DB_PATH)
    listings = db.get_listings_for_ui(filter_mode=tab)
    counts = {
        "active": len(db.get_listings_for_ui(filter_mode="active")),
        "listed": len(db.get_listings_for_ui(filter_mode="listed")),
        "sold": len(db.get_listings_for_ui(filter_mode="sold")),
    }
    db.close()
    return templates.TemplateResponse(request, "index.html", {
        "listings": listings,
        "tab": tab,
        "counts": counts,
        "authenticated": _auth.is_authenticated(),
        "configured": _auth.is_configured(),
        "auth_msg": auth,
    })


@app.get("/item/{item_id}/edit", response_class=HTMLResponse)
async def edit_item(request: Request, item_id: int):
    db = Database(DB_PATH)
    listing = db.get_listing_by_id(item_id)
    db.close()
    if not listing:
        return HTMLResponse("商品が見つかりません", status_code=404)

    rate = await get_usd_to_jpy()
    shipping = listing.listing_shipping_usd if listing.listing_shipping_usd is not None else CONFIG["listing"]["international_shipping_usd"]
    margin = listing.listing_margin if listing.listing_margin is not None else CONFIG["listing"]["profit_margin"]
    price_usd = listing.ebay_price_usd or calculate_ebay_price(listing.price_jpy, rate)

    return templates.TemplateResponse(request, "edit.html", {
        "listing": listing,
        "images": _parse_images(listing),
        "shipping": round(shipping, 1),
        "margin_pct": round(margin * 100),
        "price_usd": round(price_usd, 2),
        "rate": round(rate, 1),
        "default_shipping": CONFIG["listing"]["international_shipping_usd"],
        "default_margin_pct": round(CONFIG["listing"]["profit_margin"] * 100),
    })


@app.post("/item/{item_id}/save")
async def save_item(request: Request, item_id: int):
    form = await request.form()
    db = Database(DB_PATH)
    db.update_listing_fields(
        listing_id=item_id,
        listing_title=str(form.get("title", "")),
        listing_description=str(form.get("description", "")),
        listing_shipping_usd=float(form.get("shipping_usd", 0)),
        listing_margin=float(form.get("margin_pct", 15)) / 100,
        ebay_condition_id=int(form.get("condition_id", 3000)),
        listing_category_id=str(form.get("category_id", "")) or None,
        ebay_price_usd=float(form.get("ebay_price_usd", 0)),
    )
    db.close()
    return RedirectResponse("/", status_code=303)


@app.post("/list")
async def list_items(request: Request):
    form = await request.form()
    item_ids = [int(v) for v in form.getlist("item_ids")]

    if not item_ids:
        return RedirectResponse("/", status_code=303)

    ebay = EbayListingAPI(_auth)
    policies = await ebay.get_policies()
    ff = policies.get("fulfillment", [])
    pay = policies.get("payment", [])
    ret = policies.get("return", [])

    if not ff or not pay or not ret:
        return templates.TemplateResponse(request, "result.html", {
            "results": [],
            "error": "eBayアカウントに配送・支払い・返品ポリシーが設定されていません。eBayセラーアカウントの「Business policies」で設定してください。",
        })

    db = Database(DB_PATH)
    results = []
    for item_id in item_ids:
        listing = db.get_listing_by_id(item_id)
        if not listing or not listing.listing_category_id:
            results.append({
                "title": (listing.listing_title or listing.title)[:40] if listing else f"ID:{item_id}",
                "success": False,
                "listing_id": "",
                "error": "カテゴリが未設定です。編集画面で設定してください。",
            })
            continue

        images = _parse_images(listing)
        result = await ebay.create_listing(
            sku=f"mercari_{listing.source_id}",
            title=(listing.listing_title or listing.title)[:80],
            description=listing.listing_description or listing.description or listing.title,
            price_usd=listing.ebay_price_usd or 0,
            condition_id=listing.ebay_condition_id or 3000,
            category_id=listing.listing_category_id,
            image_urls=images,
            fulfillment_policy_id=ff[0]["fulfillmentPolicyId"],
            payment_policy_id=pay[0]["paymentPolicyId"],
            return_policy_id=ret[0]["returnPolicyId"],
        )
        if result["success"]:
            db.mark_as_listed(item_id, result["listing_id"])
        results.append({
            "title": (listing.listing_title or listing.title)[:40],
            "success": result["success"],
            "listing_id": result.get("listing_id", ""),
            "error": result.get("error", ""),
        })

    db.close()
    return templates.TemplateResponse(request, "result.html", {
        "results": results,
        "error": None,
    })


@app.get("/auth/ebay")
async def auth_ebay():
    return RedirectResponse(_auth.get_auth_url())


@app.get("/auth/ebay/callback")
async def auth_callback(code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/?auth=error")
    success = await _auth.exchange_code(code)
    return RedirectResponse("/?auth=" + ("ok" if success else "error"))


@app.get("/api/categories")
async def api_categories(q: str = ""):
    if len(q) < 2:
        return JSONResponse([])
    ebay = EbayListingAPI(_auth)
    return JSONResponse(await ebay.get_category_suggestions(q))


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"
