"""Flask web dashboard for the Mercari→eBay sourcing tool."""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import CONFIG, DB_PATH
from src.db.database import Database
from src.db.models import WatchlistItem
from src.main import run_pipeline

app = Flask(__name__)
logger = logging.getLogger(__name__)

# ── Scan state (thread-safe) ──────────────────────────────────────────────────
_scan_lock = threading.Lock()
_scan_state: dict = {
    "running": False,
    "started_at": None,
    "log": [],
    "last_completed_at": None,
    "last_result": None,
}


def _run_scan_thread(sources: list[str] | None, category: str | None, dry_run: bool) -> None:
    with _scan_lock:
        _scan_state["running"] = True
        _scan_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _scan_state["log"] = ["スキャン開始..."]
        _scan_state["last_result"] = None

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            run_pipeline(sources=sources, category=category, dry_run=dry_run)
        )
        loop.close()
        with _scan_lock:
            _scan_state["log"].append("✅ スキャン完了")
            _scan_state["last_result"] = "success"
    except Exception as exc:
        logger.exception("Scan error")
        with _scan_lock:
            _scan_state["log"].append(f"❌ エラー: {exc}")
            _scan_state["last_result"] = "error"
    finally:
        with _scan_lock:
            _scan_state["running"] = False
            _scan_state["last_completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard() -> str:
    db = Database(DB_PATH)
    total = db.conn.execute("SELECT COUNT(*) FROM source_listings").fetchone()[0]
    new_count = db.conn.execute(
        "SELECT COUNT(*) FROM source_listings WHERE status='new'"
    ).fetchone()[0]
    alerted = db.conn.execute(
        "SELECT COUNT(*) FROM source_listings WHERE status='alerted'"
    ).fetchone()[0]
    analyses = db.conn.execute("SELECT COUNT(*) FROM analysis_results").fetchone()[0]
    buys = db.conn.execute(
        "SELECT COUNT(*) FROM analysis_results WHERE recommendation='buy'"
    ).fetchone()[0]

    rows = db.conn.execute(
        """
        SELECT sl.title, sl.source, sl.price_jpy, sl.url, sl.image_url,
               ar.estimated_profit_jpy, ar.profit_rate, ar.ebay_avg_price_usd,
               ar.ebay_sold_count, sl.category, sl.condition,
               strftime('%Y-%m-%d', sl.found_at) AS found_date
        FROM analysis_results ar
        JOIN source_listings sl ON sl.id = ar.source_listing_id
        WHERE ar.recommendation = 'buy'
        ORDER BY ar.estimated_profit_jpy DESC
        LIMIT 20
        """
    ).fetchall()
    db.close()

    return render_template(
        "dashboard.html",
        total=total,
        new_count=new_count,
        alerted=alerted,
        analyses=analyses,
        buys=buys,
        opportunities=rows,
        scan_running=_scan_state["running"],
    )


@app.route("/watchlist")
def watchlist() -> str:
    db = Database(DB_PATH)
    category = request.args.get("category") or None
    items = db.get_watchlist(category)
    db.close()
    return render_template("watchlist.html", items=items, category=category)


@app.route("/watchlist/add", methods=["POST"])
def watchlist_add():
    category = request.form.get("category", "game")
    keyword = request.form.get("keyword", "").strip()
    min_profit = float(request.form.get("min_profit", 0.30))
    max_price_raw = request.form.get("max_price", "").strip()
    max_price_jpy = int(max_price_raw) if max_price_raw.isdigit() else None

    if keyword:
        db = Database(DB_PATH)
        item = WatchlistItem(
            category=category,
            keyword=keyword,
            min_profit_rate=min_profit,
            max_buy_price_jpy=max_price_jpy,
        )
        db.add_watchlist_item(item)
        db.close()
    return redirect(url_for("watchlist"))


@app.route("/watchlist/delete/<int:item_id>", methods=["POST"])
def watchlist_delete(item_id: int):
    db = Database(DB_PATH)
    db.conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
    db.conn.commit()
    db.close()
    return redirect(url_for("watchlist"))


@app.route("/scan", methods=["GET", "POST"])
def scan():
    if request.method == "POST":
        if not _scan_state["running"]:
            sources_raw = request.form.get("sources", "").strip()
            sources = [s.strip() for s in sources_raw.split(",") if s.strip()] or None
            category = request.form.get("category") or None
            dry_run = request.form.get("dry_run") == "1"

            t = threading.Thread(
                target=_run_scan_thread,
                args=(sources, category, dry_run),
                daemon=True,
            )
            t.start()
        return redirect(url_for("scan"))

    return render_template("scan.html", scan_state=_scan_state)


@app.route("/api/scan-status")
def api_scan_status():
    with _scan_lock:
        return jsonify(dict(_scan_state))


@app.route("/results")
def results() -> str:
    db = Database(DB_PATH)
    recommendation = request.args.get("recommendation", "buy")
    category = request.args.get("category") or None

    sql = """
        SELECT sl.title, sl.source, sl.price_jpy, sl.url, sl.image_url,
               ar.estimated_profit_jpy, ar.profit_rate, ar.ebay_avg_price_usd,
               ar.ebay_sold_count, sl.category, sl.condition,
               ar.recommendation, ar.estimated_shipping_jpy,
               strftime('%Y-%m-%d', sl.found_at) AS found_date
        FROM analysis_results ar
        JOIN source_listings sl ON sl.id = ar.source_listing_id
        WHERE ar.recommendation = ?
    """
    params: list = [recommendation]
    if category:
        sql += " AND sl.category = ?"
        params.append(category)
    sql += " ORDER BY ar.estimated_profit_jpy DESC LIMIT 100"

    rows = db.conn.execute(sql, params).fetchall()
    db.close()
    return render_template(
        "results.html", rows=rows, recommendation=recommendation, category=category
    )


@app.route("/calculator")
def calculator() -> str:
    return render_template("calculator.html")
