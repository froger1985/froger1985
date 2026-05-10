from __future__ import annotations

import json
import socket
from pathlib import Path

_PRESETS_FILE = Path("data/category_presets.json")


def _load_presets() -> list[dict]:
    if _PRESETS_FILE.exists():
        try:
            return json.loads(_PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_presets(presets: list[dict]):
    _PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PRESETS_FILE.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")

import anthropic
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
    try:
        shipping_usd = float(form.get("shipping_usd", 0))
        margin = float(form.get("margin_pct", 15)) / 100
        condition_id = int(form.get("condition_id", 3000))
        price_usd = float(form.get("ebay_price_usd", 0))
    except (ValueError, TypeError):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse({"ok": False, "error": "入力値が不正です"}, status_code=400)
        return RedirectResponse("/", status_code=303)
    db = Database(DB_PATH)
    db.update_listing_fields(
        listing_id=item_id,
        listing_title=str(form.get("title", "")),
        listing_description=str(form.get("description", "")),
        listing_shipping_usd=shipping_usd,
        listing_margin=margin,
        ebay_condition_id=condition_id,
        listing_category_id=str(form.get("category_id", "")) or None,
        ebay_price_usd=price_usd,
    )
    db.close()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JSONResponse({"ok": True})
    return RedirectResponse("/", status_code=303)


@app.get("/api/item/{item_id}")
async def api_item(item_id: int):
    db = Database(DB_PATH)
    listing = db.get_listing_by_id(item_id)
    db.close()
    if not listing:
        return JSONResponse({"error": "not found"}, status_code=404)
    rate = await get_usd_to_jpy()
    shipping = listing.listing_shipping_usd if listing.listing_shipping_usd is not None else CONFIG["listing"]["international_shipping_usd"]
    margin = listing.listing_margin if listing.listing_margin is not None else CONFIG["listing"]["profit_margin"]
    price_usd = listing.ebay_price_usd or calculate_ebay_price(listing.price_jpy, rate)
    return JSONResponse({
        "id": listing.id,
        "title": listing.title,
        "listing_title": listing.listing_title or listing.title,
        "price_jpy": listing.price_jpy,
        "url": listing.url,
        "images": _parse_images(listing),
        "condition": listing.condition,
        "ebay_condition_id": listing.ebay_condition_id or 3000,
        "ebay_price_usd": round(price_usd, 2),
        "listing_description": listing.listing_description or listing.description or "",
        "listing_category_id": listing.listing_category_id or "",
        "shipping": round(shipping, 1),
        "margin_pct": round(margin * 100),
        "rate": round(rate, 1),
        "default_shipping": CONFIG["listing"]["international_shipping_usd"],
        "default_margin_pct": round(CONFIG["listing"]["profit_margin"] * 100),
        "ebay_listing_id": listing.ebay_listing_id,
    })


@app.get("/debug/auth-url")
async def debug_auth_url():
    url = _auth.get_auth_url()
    return JSONResponse({
        "auth_url": url,
        "client_id": _auth.client_id or "(未設定)",
        "runame": _auth.runame or "(未設定)",
        "is_sandbox": _auth.is_sandbox,
        "is_configured": _auth.is_configured(),
        "note": "is_sandbox=true の場合はSandbox認証を使用します。EBAY_CLIENT_IDにSBXが含まれているか確認してください",
    })


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
        title_for_display = (listing.listing_title or listing.title)[:40] if listing else f"ID:{item_id}"
        if not listing or not listing.listing_category_id:
            results.append({
                "title": title_for_display,
                "success": False,
                "listing_id": "",
                "error": "カテゴリが未設定です。編集画面で設定してください。",
            })
            continue
        if not listing.ebay_price_usd or listing.ebay_price_usd <= 0:
            results.append({
                "title": title_for_display,
                "success": False,
                "listing_id": "",
                "error": "eBay出品価格が未設定です。編集画面で価格を設定してください。",
            })
            continue

        images = _parse_images(listing)
        try:
            result = await ebay.create_listing(
                sku=f"mercari_{listing.source_id}",
                title=(listing.listing_title or listing.title)[:80],
                description=listing.listing_description or listing.description or listing.title,
                price_usd=listing.ebay_price_usd,
                condition_id=listing.ebay_condition_id or 3000,
                category_id=listing.listing_category_id,
                image_urls=images,
                fulfillment_policy_id=ff[0]["fulfillmentPolicyId"],
                payment_policy_id=pay[0]["paymentPolicyId"],
                return_policy_id=ret[0]["returnPolicyId"],
            )
        except Exception as e:
            results.append({
                "title": title_for_display,
                "success": False,
                "listing_id": "",
                "error": str(e),
            })
            continue
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


@app.post("/item/{item_id}/end")
async def end_item(item_id: int):
    db = Database(DB_PATH)
    listing = db.get_listing_by_id(item_id)
    if not listing or not listing.ebay_listing_id:
        db.close()
        return JSONResponse({"success": False, "error": "出品情報が見つかりません"})
    ebay = EbayListingAPI(_auth)
    sku = f"mercari_{listing.source_id}"
    result = await ebay.end_listing(sku)
    if result["success"]:
        db.conn.execute(
            "UPDATE source_listings SET ebay_listing_id=NULL, status='new' WHERE id=?",
            (item_id,),
        )
        db.conn.commit()
    db.close()
    return JSONResponse(result)


@app.get("/auth/ebay")
async def auth_ebay():
    return RedirectResponse(_auth.get_auth_url())


@app.get("/auth/ebay/callback")
async def auth_callback(code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/?auth=error")
    success = await _auth.exchange_code(code)
    return RedirectResponse("/?auth=" + ("ok" if success else "error"))


@app.post("/api/translate")
async def api_translate(request: Request):
    body = await request.json()
    title = str(body.get("title", "")).strip()
    description = str(body.get("description", "")).strip()
    if not title and not description:
        return JSONResponse({"error": "タイトルまたは説明が必要です"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY が設定されていません"}, status_code=500)

    prompt = f"""You are an eBay listing assistant specializing in Japanese secondhand goods sold internationally.
Translate the following Japanese product title and description into natural English optimized for eBay listings.

Rules:
- Title: concise, descriptive, under 80 characters, capitalize main words
- Description: clear and honest for international buyers, keep condition details
- Do NOT invent or add information not present in the original
- Return only valid JSON, no extra text

Input:
Title: {title}
Description: {description}

Return JSON: {{"title": "...", "description": "..."}}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # JSON部分だけ抽出
        start = raw.find("{")
        end = raw.rfind("}") + 1
        result = json.loads(raw[start:end])
        return JSONResponse({
            "title": result.get("title", ""),
            "description": result.get("description", ""),
        })
    except json.JSONDecodeError:
        return JSONResponse({"error": "翻訳結果のパースに失敗しました"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"翻訳エラー: {e}"}, status_code=500)


@app.get("/api/categories")
async def api_categories(q: str = ""):
    if len(q) < 2:
        return JSONResponse([])
    ebay = EbayListingAPI(_auth)
    return JSONResponse(await ebay.get_category_suggestions(q))


@app.get("/api/category-presets")
async def get_category_presets():
    return JSONResponse(_load_presets())


@app.post("/api/category-presets")
async def add_category_preset(request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    cat_id = str(body.get("id", "")).strip()
    if not name or not cat_id:
        return JSONResponse({"ok": False, "error": "name and id required"}, status_code=400)
    presets = _load_presets()
    if any(p["id"] == cat_id for p in presets):
        return JSONResponse({"ok": False, "error": "already exists"}, status_code=400)
    presets.append({"name": name, "id": cat_id})
    _save_presets(presets)
    return JSONResponse({"ok": True})


@app.delete("/api/category-presets/{cat_id}")
async def delete_category_preset(cat_id: str):
    presets = [p for p in _load_presets() if p["id"] != cat_id]
    _save_presets(presets)
    return JSONResponse({"ok": True})


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"
