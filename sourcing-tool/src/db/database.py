from __future__ import annotations

import sqlite3
from pathlib import Path

from src.db.models import AnalysisResult, EbaySold, SourceListing, WatchlistItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    price_jpy INTEGER NOT NULL,
    url TEXT NOT NULL,
    image_url TEXT DEFAULT '',
    condition TEXT DEFAULT '',
    found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'new',
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS ebay_sold (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_query TEXT NOT NULL,
    item_title TEXT DEFAULT '',
    sold_price_usd REAL NOT NULL,
    sold_date TEXT DEFAULT '',
    item_url TEXT DEFAULT '',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_listing_id INTEGER REFERENCES source_listings(id),
    ebay_avg_price_usd REAL,
    ebay_sold_count INTEGER,
    estimated_shipping_jpy INTEGER,
    ebay_fee_rate REAL DEFAULT 0.1325,
    estimated_profit_jpy INTEGER,
    profit_rate REAL,
    recommendation TEXT,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    keyword TEXT NOT NULL,
    min_profit_rate REAL DEFAULT 0.30,
    max_buy_price_jpy INTEGER,
    enabled BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_listing_id INTEGER REFERENCES source_listings(id),
    channel TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message TEXT
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(_SCHEMA)
        self._migrate_schema()
        self.conn.commit()

    def _migrate_schema(self):
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(source_listings)")}
        new_columns = [
            ("description", "TEXT DEFAULT ''"),
            ("extra_images", "TEXT DEFAULT ''"),
            ("stock_state", "TEXT DEFAULT ''"),
            ("ebay_price_usd", "REAL DEFAULT NULL"),
            ("ebay_condition_id", "INTEGER DEFAULT NULL"),
            ("listing_title", "TEXT DEFAULT NULL"),
            ("listing_description", "TEXT DEFAULT NULL"),
            ("listing_shipping_usd", "REAL DEFAULT NULL"),
            ("listing_margin", "REAL DEFAULT NULL"),
            ("listing_category_id", "TEXT DEFAULT NULL"),
            ("ebay_listing_id", "TEXT DEFAULT NULL"),
        ]
        for col, definition in new_columns:
            if col not in existing:
                self.conn.execute(f"ALTER TABLE source_listings ADD COLUMN {col} {definition}")

    def close(self):
        self.conn.close()

    # --- Source Listings ---

    def upsert_listing(self, listing: SourceListing) -> int:
        cur = self.conn.execute(
            """INSERT INTO source_listings (source, source_id, category, title, price_jpy, url, image_url, condition)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source, source_id) DO UPDATE SET
                 price_jpy = excluded.price_jpy,
                 title = excluded.title
               RETURNING id""",
            (listing.source, listing.source_id, listing.category,
             listing.title, listing.price_jpy, listing.url,
             listing.image_url, listing.condition),
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def get_listings_without_details(self, source: str | None = None, limit: int = 0) -> list[SourceListing]:
        query = "SELECT * FROM source_listings WHERE stock_state = '' OR condition = ''"
        params: list = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY found_at DESC"
        if limit > 0:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_listing(r) for r in rows]

    def get_ebay_listed_listings(self, source: str | None = None) -> list[SourceListing]:
        """eBayに出品中（ebay_listing_id あり）の商品を返す。売切れ定期チェック用。"""
        query = "SELECT * FROM source_listings WHERE ebay_listing_id IS NOT NULL"
        params: list = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY found_at DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_listing(r) for r in rows]

    def update_listing_details(
        self, listing_id: int, condition: str, description: str,
        extra_images: str, stock_state: str,
    ):
        self.conn.execute(
            """UPDATE source_listings
               SET condition = ?, description = ?, extra_images = ?, stock_state = ?
               WHERE id = ?""",
            (condition, description, extra_images, stock_state, listing_id),
        )
        self.conn.commit()

    def get_listing_by_id(self, listing_id: int) -> SourceListing | None:
        row = self.conn.execute(
            "SELECT * FROM source_listings WHERE id = ?", (listing_id,)
        ).fetchone()
        return self._row_to_listing(row) if row else None

    @staticmethod
    def _is_in_stock(stock_state: str) -> bool:
        s = stock_state.lower()
        return bool(s) and "sold" not in s and "out" not in s and s not in ("stop", "trading")

    def get_listings_for_ui(self, source: str = "mercari_likes", filter_mode: str = "active") -> list[SourceListing]:
        rows = self.conn.execute(
            "SELECT * FROM source_listings WHERE source = ? ORDER BY found_at DESC",
            (source,),
        ).fetchall()
        listings = [self._row_to_listing(r) for r in rows]
        if filter_mode == "active":
            return [l for l in listings if l.ebay_listing_id is None and self._is_in_stock(l.stock_state)]
        if filter_mode == "sold":
            return [l for l in listings if not self._is_in_stock(l.stock_state)]
        if filter_mode == "listed":
            return [l for l in listings if l.ebay_listing_id is not None]
        return listings

    def update_listing_fields(
        self,
        listing_id: int,
        listing_title: str,
        listing_description: str,
        listing_shipping_usd: float,
        listing_margin: float,
        ebay_condition_id: int,
        listing_category_id: str | None,
        ebay_price_usd: float,
    ):
        self.conn.execute(
            """UPDATE source_listings
               SET listing_title=?, listing_description=?, listing_shipping_usd=?,
                   listing_margin=?, ebay_condition_id=?, listing_category_id=?, ebay_price_usd=?
               WHERE id=?""",
            (listing_title, listing_description, listing_shipping_usd,
             listing_margin, ebay_condition_id, listing_category_id, ebay_price_usd, listing_id),
        )
        self.conn.commit()

    def mark_as_listed(self, listing_id: int, ebay_listing_id: str):
        self.conn.execute(
            "UPDATE source_listings SET ebay_listing_id=?, status='alerted' WHERE id=?",
            (ebay_listing_id, listing_id),
        )
        self.conn.commit()

    def get_listings_for_pricing(self, source: str | None = None, limit: int = 0) -> list[SourceListing]:
        query = "SELECT * FROM source_listings WHERE condition != '' AND ebay_price_usd IS NULL"
        params: list = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY found_at DESC"
        if limit > 0:
            query += f" LIMIT {limit}"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_listing(r) for r in rows]

    def update_ebay_price(self, listing_id: int, ebay_price_usd: float, ebay_condition_id: int):
        self.conn.execute(
            "UPDATE source_listings SET ebay_price_usd = ?, ebay_condition_id = ? WHERE id = ?",
            (ebay_price_usd, ebay_condition_id, listing_id),
        )
        self.conn.commit()

    def get_new_listings(self) -> list[SourceListing]:
        rows = self.conn.execute(
            "SELECT * FROM source_listings WHERE status = 'new' ORDER BY found_at DESC"
        ).fetchall()
        return [self._row_to_listing(r) for r in rows]

    def update_listing_status(self, listing_id: int, status: str):
        self.conn.execute(
            "UPDATE source_listings SET status = ? WHERE id = ?",
            (status, listing_id),
        )
        self.conn.commit()

    def listing_exists(self, source: str, source_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM source_listings WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return row is not None

    def get_all_source_ids(self, source: str) -> list[tuple[str, str | None]]:
        """Return (source_id, ebay_listing_id) for all rows with the given source."""
        rows = self.conn.execute(
            "SELECT source_id, ebay_listing_id FROM source_listings WHERE source = ?",
            (source,),
        ).fetchall()
        return [(r["source_id"], r["ebay_listing_id"]) for r in rows]

    def delete_listing_by_source_id(self, source: str, source_id: str):
        self.conn.execute(
            "DELETE FROM source_listings WHERE source = ? AND source_id = ?",
            (source, source_id),
        )
        self.conn.commit()

    # --- eBay Sold ---

    def save_ebay_sold(self, sold: EbaySold):
        self.conn.execute(
            """INSERT INTO ebay_sold (search_query, item_title, sold_price_usd, sold_date, item_url)
               VALUES (?, ?, ?, ?, ?)""",
            (sold.search_query, sold.item_title, sold.sold_price_usd,
             sold.sold_date, sold.item_url),
        )
        self.conn.commit()

    def get_ebay_sold_stats(self, query: str) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) as cnt, AVG(sold_price_usd) as avg_price,
                      MIN(sold_price_usd) as min_price, MAX(sold_price_usd) as max_price
               FROM ebay_sold WHERE search_query = ?""",
            (query,),
        ).fetchone()
        return {
            "count": row["cnt"],
            "avg_price": row["avg_price"] or 0,
            "min_price": row["min_price"] or 0,
            "max_price": row["max_price"] or 0,
        }

    # --- Analysis Results ---

    def save_analysis(self, result: AnalysisResult) -> int:
        cur = self.conn.execute(
            """INSERT INTO analysis_results
               (source_listing_id, ebay_avg_price_usd, ebay_sold_count,
                estimated_shipping_jpy, ebay_fee_rate, estimated_profit_jpy,
                profit_rate, recommendation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               RETURNING id""",
            (result.source_listing_id, result.ebay_avg_price_usd,
             result.ebay_sold_count, result.estimated_shipping_jpy,
             result.ebay_fee_rate, result.estimated_profit_jpy,
             result.profit_rate, result.recommendation),
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    # --- Watchlist ---

    def get_watchlist(self, category: str | None = None) -> list[WatchlistItem]:
        if category:
            rows = self.conn.execute(
                "SELECT * FROM watchlist WHERE enabled = 1 AND category = ?",
                (category,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM watchlist WHERE enabled = 1"
            ).fetchall()
        return [self._row_to_watchlist(r) for r in rows]

    def add_watchlist_item(self, item: WatchlistItem) -> int:
        cur = self.conn.execute(
            """INSERT INTO watchlist (category, keyword, min_profit_rate, max_buy_price_jpy, enabled)
               VALUES (?, ?, ?, ?, ?)
               RETURNING id""",
            (item.category, item.keyword, item.min_profit_rate,
             item.max_buy_price_jpy, item.enabled),
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    # --- Alerts ---

    def save_alert(self, source_listing_id: int, channel: str, message: str):
        self.conn.execute(
            "INSERT INTO alerts (source_listing_id, channel, message) VALUES (?, ?, ?)",
            (source_listing_id, channel, message),
        )
        self.conn.commit()

    # --- Helpers ---

    @staticmethod
    def _row_to_listing(row: sqlite3.Row) -> SourceListing:
        keys = row.keys()
        return SourceListing(
            id=row["id"], source=row["source"], source_id=row["source_id"],
            category=row["category"], title=row["title"],
            price_jpy=row["price_jpy"], url=row["url"],
            image_url=row["image_url"], condition=row["condition"],
            status=row["status"],
            description=row["description"] if "description" in keys else "",
            extra_images=row["extra_images"] if "extra_images" in keys else "",
            stock_state=row["stock_state"] if "stock_state" in keys else "",
            ebay_price_usd=row["ebay_price_usd"] if "ebay_price_usd" in keys else None,
            ebay_condition_id=row["ebay_condition_id"] if "ebay_condition_id" in keys else None,
            listing_title=row["listing_title"] if "listing_title" in keys else None,
            listing_description=row["listing_description"] if "listing_description" in keys else None,
            listing_shipping_usd=row["listing_shipping_usd"] if "listing_shipping_usd" in keys else None,
            listing_margin=row["listing_margin"] if "listing_margin" in keys else None,
            listing_category_id=row["listing_category_id"] if "listing_category_id" in keys else None,
            ebay_listing_id=row["ebay_listing_id"] if "ebay_listing_id" in keys else None,
        )

    @staticmethod
    def _row_to_watchlist(row: sqlite3.Row) -> WatchlistItem:
        return WatchlistItem(
            id=row["id"], category=row["category"], keyword=row["keyword"],
            min_profit_rate=row["min_profit_rate"],
            max_buy_price_jpy=row["max_buy_price_jpy"],
            enabled=bool(row["enabled"]),
        )
