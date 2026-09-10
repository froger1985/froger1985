# タスクリスト：メルカリいいね商品リスト取得

## ステータス凡例
- [ ] 未着手
- [x] 完了

---

## Phase 1: ドキュメント整備

- [x] `docs/product-requirements.md` 作成・承認
- [x] `docs/architecture.md` 作成・承認
- [x] `docs/functional-design.md` 作成・承認
- [x] `docs/repository-structure.md` 作成・承認
- [x] `docs/development-guidelines.md` 作成・承認
- [x] `docs/glossary.md` 作成・承認
- [x] `.steering/20260506-fetch-mercari-likes/requirements.md` 作成
- [x] `.steering/20260506-fetch-mercari-likes/design.md` 作成
- [x] `.steering/20260506-fetch-mercari-likes/tasklist.md` 作成（このファイル）

## Phase 2: 実装

- [ ] `requirements.txt` に `playwright>=1.40.0` を追加
- [ ] `sourcing-tool/.gitignore` に `data/mercari_session.json` を追加
- [ ] `src/scrapers/mercari_likes.py` を新規作成
  - [ ] `MercariLikesScraper` クラス
  - [ ] セッション読み込み・保存
  - [ ] ログイン状態チェック
  - [ ] ネットワーク傍受
  - [ ] スクロールループ
  - [ ] `_parse_item()` メソッド
- [ ] `src/main.py` に `likes` コマンドと `run_likes_pipeline()` を追加

## Phase 3: 動作確認

- [ ] `pip install -r requirements.txt` + `playwright install chromium` が成功する
- [ ] `python -m src.main likes --no-save` を実行し、ブラウザが起動する
- [ ] ログイン後にいいね商品一覧がコンソールに表示される
- [ ] `python -m src.main likes --save` 後に `status` コマンドでリスト数が増える
- [ ] 2回目実行でログインなしで動作する

## Phase 4: コミット・プッシュ

- [ ] 全変更を `claude/fetch-mercari-likes-IFQ70` ブランチにコミット・プッシュ
