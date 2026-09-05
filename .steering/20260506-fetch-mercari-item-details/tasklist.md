# タスクリスト：メルカリ商品詳細取得（Step 2）

## ステータス凡例
- [ ] 未着手
- [x] 完了

---

## Phase 1: ドキュメント

- [x] `.steering/20260506-fetch-mercari-item-details/requirements.md`
- [x] `.steering/20260506-fetch-mercari-item-details/design.md`
- [x] `.steering/20260506-fetch-mercari-item-details/tasklist.md`

## Phase 2: 実装

- [x] `src/db/models.py` に `description`, `extra_images`, `stock_state` を追加
- [x] `src/db/database.py` にカラムマイグレーションと `update_listing_details()` を追加
- [x] `src/scrapers/mercari_item.py` を新規作成（Playwright + APIインターセプト方式）
- [x] `src/main.py` に `fetch-details` コマンドを追加

## Phase 3: 動作確認

- [x] `python -m src.main fetch-details --limit 3` で3件処理されること
- [x] DB の `condition`, `description`, `stock_state` に値が入ること（全48件完了）
- [x] 2回目実行でスキップされること（stock_state/condition 両方セット済みでヒットしない）

## Phase 4: コミット・プッシュ

- [x] `claude/fetch-mercari-likes-IFQ70` ブランチにプッシュ

## 実装メモ

- MercariのアイテムページはRSC(React Server Components)を使用しており `__NEXT_DATA__` にデータがない
- Playwright でアイテムページを開き `api.mercari.jp` のレスポンスを傍受することで解決
- APIフィールドはsnake_case: `item_condition.name`, `item_status`
- `get_listings_without_details`: `stock_state = '' OR condition = ''` で再取得対象を判定
