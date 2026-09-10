# タスク設計：メルカリいいね商品リスト取得

## アプローチ

Playwright でブラウザを起動し、`jp.mercari.com/mypage/likes` ページが内部的に発行する API リクエストのレスポンスを傍受して商品データを取得する。

## ファイル変更一覧

| ファイル | 操作 | 内容 |
|---|---|---|
| `src/scrapers/mercari_likes.py` | **新規作成** | Playwright いいね取得スクレイパー |
| `src/main.py` | **変更** | `likes` CLIコマンド追加 |
| `requirements.txt` | **変更** | `playwright>=1.40.0` 追加 |
| `.gitignore` | **変更** | `data/mercari_session.json` 追加 |

## `mercari_likes.py` 設計

```python
class MercariLikesScraper:
    SESSION_FILE = Path("data/mercari_session.json")
    LIKES_PAGE = "https://jp.mercari.com/mypage/likes"
    SCROLL_PAUSE = 2.0   # スクロール後の待機秒数
    API_TIMEOUT = 5000   # API レスポンス待機 ms
```

### 主要メソッド

**`fetch_all_likes(limit=0) -> list[SourceListing]`**
- 公開インタフェース
- Playwright コンテキスト管理、セッション読み込み、ページ遷移を統括
- スクロールループを実行して全件収集

**`_load_session(context)`**
- セッションファイルが存在すれば `context.storage_state()` から読み込む

**`_save_session(context)`**
- `context.storage_state()` を JSON で保存

**`_is_logged_in(page) -> bool`**
- ログインページにリダイレクトされていないかを確認
- ログインページの URL または要素の存在で判断

**`_collect_items(page, limit) -> list[dict]`**
- `page.on("response", handler)` で API レスポンスを傍受
- ページ最下部までスクロール → 新アイテム追加 → 変化なくなるまで繰り返す

**`_parse_item(item: dict) -> SourceListing | None`**
- API レスポンスの item オブジェクトを SourceListing に変換
- 必須フィールドが欠如している場合は None を返す

### セッション管理フロー

```
1. data/mercari_session.json が存在する?
   Yes → browser_context に読み込む
   No  → 空のコンテキストで起動

2. jp.mercari.com/mypage/likes へ遷移

3. ログインページにリダイレクトされた?
   Yes → "ブラウザでログインしてください。完了後 Enter を押してください" と表示
         input() で待機
   No  → そのまま続行

4. アイテム収集

5. data/mercari_session.json に保存
```

### ネットワーク傍受パターン

```python
async def handler(response):
    url = response.url
    if ("api.mercari.jp" in url and
        ("likes" in url or "favorites" in url) and
        response.status == 200):
        try:
            data = await response.json()
            # data["items"] を蓄積
        except Exception:
            pass
```

実際の URL パターンは初回実行時に確認し、必要に応じてパターンを調整する。

### スクロールループ

```python
prev_count = 0
while True:
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(SCROLL_PAUSE * 1000)

    if len(collected) == prev_count:
        break  # 新しいアイテムが増えなくなった = 最終ページ
    if limit > 0 and len(collected) >= limit:
        break

    prev_count = len(collected)
```

## `main.py` への追加

```python
@cli.command()
@click.option("--save/--no-save", default=True)
@click.option("--limit", default=0, type=int)
def likes(save: bool, limit: int):
    """メルカリのいいね商品リストを取得する。"""
    asyncio.run(run_likes_pipeline(save=save, limit=limit))


async def run_likes_pipeline(save: bool, limit: int):
    from src.scrapers.mercari_likes import MercariLikesScraper
    scraper = MercariLikesScraper()
    listings = await scraper.fetch_all_likes(limit=limit)

    db = Database(DB_PATH) if save else None
    new_count = skip_count = 0

    for listing in listings:
        if save and db:
            if not db.listing_exists(listing.source, listing.source_id):
                db.upsert_listing(listing)
                new_count += 1
            else:
                skip_count += 1

    _print_likes_table(listings)
    if save:
        click.echo(f"\n合計: {len(listings)}件 | 新規保存: {new_count}件 | スキップ: {skip_count}件")
    if db:
        db.close()
```

## 考慮事項

- Playwright は `headed=True`（画面あり）で起動する。headless ではメルカリの CloudFlare 検出を回避しにくい
- `data/` ディレクトリが存在しない場合は `mkdir(parents=True, exist_ok=True)` で作成する
- API の実際のレスポンス構造は `mercari.py` の `_parse_item` を参考にしつつ、いいねページ特有の構造に合わせて調整する
