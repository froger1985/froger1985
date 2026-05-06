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

- [ ] `src/db/models.py` に `description`, `extra_images`, `stock_state` を追加
- [ ] `src/db/database.py` にカラムマイグレーションと `update_listing_details()` を追加
- [ ] `src/scrapers/mercari_item.py` を新規作成
- [ ] `src/main.py` に `fetch-details` コマンドを追加

## Phase 3: 動作確認

- [ ] `python -m src.main fetch-details --limit 3` で3件処理されること
- [ ] DB の `condition`, `description`, `stock_state` に値が入ること
- [ ] 2回目実行でスキップされること

## Phase 4: コミット・プッシュ

- [ ] `claude/fetch-mercari-likes-IFQ70` ブランチにプッシュ
