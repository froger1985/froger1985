# タスク設計：メルカリ商品詳細取得（Step 2）

## ファイル変更一覧

| ファイル | 操作 | 内容 |
|---|---|---|
| `src/db/models.py` | 変更 | `SourceListing` に `description`, `extra_images`, `stock_state` を追加 |
| `src/db/database.py` | 変更 | カラムマイグレーション、`update_listing_details()` 追加、`_row_to_listing()` 更新 |
| `src/scrapers/mercari_item.py` | 新規 | httpx で商品ページ取得・`__NEXT_DATA__` パース |
| `src/main.py` | 変更 | `fetch-details` コマンド追加 |

## DB スキーマ変更

`source_listings` テーブルに 3 カラムを追加：

```sql
ALTER TABLE source_listings ADD COLUMN description TEXT DEFAULT '';
ALTER TABLE source_listings ADD COLUMN extra_images TEXT DEFAULT '';  -- JSON 配列
ALTER TABLE source_listings ADD COLUMN stock_state TEXT DEFAULT '';
```

既存 DB との互換性のため、起動時に `PRAGMA table_info` で存在チェックしてから ADD COLUMN する。

## `SourceListing` モデル変更

```python
description: str = ""
extra_images: str = ""   # JSON 文字列 '["url1","url2"]'
stock_state: str = ""    # "on_sale", "sold_out", "trading", etc.
```

## `mercari_item.py` 設計

```python
class MercariItemFetcher:
    async def fetch_details(self, item_id: str) -> dict | None:
        """商品ページを httpx で取得し __NEXT_DATA__ をパースして返す。"""

    def _extract_from_next_data(self, data: dict) -> dict:
        """__NEXT_DATA__ JSON から必要フィールドを抽出する。"""
        # 試行するパス:
        # data["props"]["pageProps"]["item"]
        # data["props"]["pageProps"]["product"]
        # → 見つかった dict から:
        #   condition: item["itemCondition"]["name"] or item["condition"]["name"]
        #   description: item["description"] or item["itemDescription"]
        #   images: [p["imageUrl"] or p["url"] for p in item["photos"] or item["thumbnails"]]
        #   stock_state: item["status"] or item["itemStatus"]
```

### httpx リクエスト

```python
headers = {
    "User-Agent": CONFIG["scraping"]["user_agent"],
    "Accept-Language": "ja-JP,ja;q=0.9",
}
resp = await client.get(f"https://jp.mercari.com/item/{item_id}", headers=headers)
```

`__NEXT_DATA__` の抽出：
```python
import re, json
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
data = json.loads(match.group(1))
```

## `fetch-details` コマンド設計

```python
@cli.command("fetch-details")
@click.option("--limit", default=0, type=int, help="最大処理件数（0=全件）")
@click.option("--source", default="mercari_likes", help="対象ソース")
def fetch_details(limit: int, source: str):
    """商品詳細（コンディション・説明・画像）を取得してDBを更新する。"""
```

処理フロー：
1. DB から `stock_state = ''` の `source_listings` を取得（未処理のみ）
2. `MercariItemFetcher` でバッチ取得
3. `db.update_listing_details()` で更新
4. 進捗をコンソールに表示（`N/M 件完了`）
