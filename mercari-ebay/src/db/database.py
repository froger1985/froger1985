from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.db.models import PriceHistory, SyncLog, TrackedItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mercari_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    mercari_price_jpy INTEGER NOT NULL,
    mercari_url TEXT NOT NULL,
    mercari_status TEXT DEFAULT 'on_sale',
    image_url TEXT DEFAULT '',
    condition TEXT DEFAULT '',
    ebay_listing_id TEXT DEFAULT '',
    ebay_price_usd REAL DEFAULT 0.0,
    ebay_status TEXT DEFAULT 'pending',
    last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    listed_at TIMESTAMP,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracked_item_id INTEGER REFERENCES tracked_items(id),
    mercari_old_price_jpy INTEGER NOT NULL,
    mercari_new_price_jpy INTEGER NOT NULL,
    ebay_old_price_usd REAL NOT NULL,
    ebay_new_price_usd REAL NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    items_checked INTEGER DEFAULT 0,
    sold_out_count INTEGER DEFAULT 0,
    price_updated_count INTEGER DEFAULT 0,
    newly_listed_count INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    duration_sec REAL DEFAULT 0.0
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- TrackedItem CRUD ---

    def add_item(self, item: TrackedItem) -> int:
        cur = self.conn.execute(
            """INSERT INTO tracked_items
               (mercari_id, title, mercari_price_jpy, mercari_url,
                mercari_status, image_url, condition,
                ebay_listing_id, ebay_price_usd, ebay_status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mercari_id) DO NOTHING
               RETURNING id""",
            (item.mercari_id, item.title, item.mercari_price_jpy,
             item.mercari_url, item.mercari_status, item.image_url,
             item.condition, item.ebay_listing_id, item.ebay_price_usd,
             item.ebay_status, item.notes),
        )
        row = cur.fetchone()
        self.conn.commit()
        if row:
            return row["id"]
        # Already existed - return existing id
        existing = self.get_item_by_mercari_id(item.mercari_id)
        return existing.id if existing else -1

    def get_item_by_mercari_id(self, mercari_id: str) -> TrackedItem | None:
        row = self.conn.execute(
            "SELECT * FROM tracked_items WHERE mercari_id = ?", (mercari_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def get_active_items(self) -> list[TrackedItem]:
        """Return items with active eBay listings to sync."""
        rows = self.conn.execute(
            "SELECT * FROM tracked_items WHERE ebay_status = 'active' ORDER BY last_checked_at ASC"
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_pending_items(self) -> list[TrackedItem]:
        """Return items not yet listed on eBay."""
        rows = self.conn.execute(
            "SELECT * FROM tracked_items WHERE ebay_status = 'pending' ORDER BY id ASC"
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_all_items(self) -> list[TrackedItem]:
        rows = self.conn.execute(
            "SELECT * FROM tracked_items ORDER BY id DESC"
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def update_ebay_listed(self, mercari_id: str, ebay_listing_id: str, ebay_price_usd: float):
        self.conn.execute(
            """UPDATE tracked_items
               SET ebay_listing_id = ?, ebay_price_usd = ?,
                   ebay_status = 'active', listed_at = CURRENT_TIMESTAMP
               WHERE mercari_id = ?""",
            (ebay_listing_id, ebay_price_usd, mercari_id),
        )
        self.conn.commit()

    def update_ebay_ended(self, mercari_id: str):
        self.conn.execute(
            "UPDATE tracked_items SET ebay_status = 'ended' WHERE mercari_id = ?",
            (mercari_id,),
        )
        self.conn.commit()

    def update_ebay_error(self, mercari_id: str, note: str):
        self.conn.execute(
            "UPDATE tracked_items SET ebay_status = 'error', notes = ? WHERE mercari_id = ?",
            (note, mercari_id),
        )
        self.conn.commit()

    def update_mercari_status(self, mercari_id: str, status: str):
        self.conn.execute(
            """UPDATE tracked_items
               SET mercari_status = ?, last_checked_at = CURRENT_TIMESTAMP
               WHERE mercari_id = ?""",
            (status, mercari_id),
        )
        self.conn.commit()

    def update_price(
        self,
        mercari_id: str,
        new_mercari_price_jpy: int,
        new_ebay_price_usd: float,
    ):
        self.conn.execute(
            """UPDATE tracked_items
               SET mercari_price_jpy = ?, ebay_price_usd = ?,
                   last_checked_at = CURRENT_TIMESTAMP
               WHERE mercari_id = ?""",
            (new_mercari_price_jpy, new_ebay_price_usd, mercari_id),
        )
        self.conn.commit()

    def touch_checked(self, mercari_id: str):
        self.conn.execute(
            "UPDATE tracked_items SET last_checked_at = CURRENT_TIMESTAMP WHERE mercari_id = ?",
            (mercari_id,),
        )
        self.conn.commit()

    def item_exists(self, mercari_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM tracked_items WHERE mercari_id = ?", (mercari_id,)
        ).fetchone()
        return row is not None

    # --- PriceHistory ---

    def save_price_change(self, change: PriceHistory):
        self.conn.execute(
            """INSERT INTO price_history
               (tracked_item_id, mercari_old_price_jpy, mercari_new_price_jpy,
                ebay_old_price_usd, ebay_new_price_usd)
               VALUES (?, ?, ?, ?, ?)""",
            (change.tracked_item_id, change.mercari_old_price_jpy,
             change.mercari_new_price_jpy, change.ebay_old_price_usd,
             change.ebay_new_price_usd),
        )
        self.conn.commit()

    # --- SyncLog ---

    def save_sync_log(self, log: SyncLog) -> int:
        cur = self.conn.execute(
            """INSERT INTO sync_logs
               (run_at, items_checked, sold_out_count, price_updated_count,
                newly_listed_count, errors, duration_sec)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               RETURNING id""",
            (log.run_at.isoformat(), log.items_checked, log.sold_out_count,
             log.price_updated_count, log.newly_listed_count,
             log.errors, log.duration_sec),
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def get_recent_sync_logs(self, limit: int = 10) -> list[SyncLog]:
        rows = self.conn.execute(
            "SELECT * FROM sync_logs ORDER BY run_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_sync_log(r) for r in rows]

    # --- Stats ---

    def count_by_ebay_status(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT ebay_status, COUNT(*) as cnt FROM tracked_items GROUP BY ebay_status"
        ).fetchall()
        return {r["ebay_status"]: r["cnt"] for r in rows}

    # --- Helpers ---

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> TrackedItem:
        return TrackedItem(
            id=row["id"],
            mercari_id=row["mercari_id"],
            title=row["title"],
            mercari_price_jpy=row["mercari_price_jpy"],
            mercari_url=row["mercari_url"],
            mercari_status=row["mercari_status"],
            image_url=row["image_url"],
            condition=row["condition"],
            ebay_listing_id=row["ebay_listing_id"],
            ebay_price_usd=row["ebay_price_usd"],
            ebay_status=row["ebay_status"],
            last_checked_at=datetime.fromisoformat(row["last_checked_at"])
            if row["last_checked_at"] else datetime.now(),
            listed_at=datetime.fromisoformat(row["listed_at"])
            if row["listed_at"] else None,
            notes=row["notes"],
        )

    @staticmethod
    def _row_to_sync_log(row: sqlite3.Row) -> SyncLog:
        return SyncLog(
            id=row["id"],
            run_at=datetime.fromisoformat(row["run_at"]),
            items_checked=row["items_checked"],
            sold_out_count=row["sold_out_count"],
            price_updated_count=row["price_updated_count"],
            newly_listed_count=row["newly_listed_count"],
            errors=row["errors"],
            duration_sec=row["duration_sec"],
        )
