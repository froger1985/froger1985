# タスク要件：メルカリ商品詳細取得（Step 2）

## 目的

likes パイプラインで DB に保存した商品（`source="mercari_likes"`）は
タイトル・価格・サムネイル画像しか持っていない。
eBay 出品に必要なコンディション・説明文・複数画像を取得して DB を更新する。

## 機能要件

1. `python -m src.main fetch-details` で全件処理できること
2. `--limit N` オプションでテスト実行できること
3. 各商品の Mercari ページ（公開・ログイン不要）から以下を取得すること：
   - コンディション（例：「目立った傷や汚れなし」）
   - 説明文
   - 画像 URL リスト（複数）
   - 在庫状態（on_sale / sold_out など）
4. 取得結果を `source_listings` テーブルの各レコードに上書き保存すること
5. 取得済み（`stock_state` が空でない）商品はスキップすること（再実行に対応）
6. リクエスト間に `config.yaml` の `request_delay_sec` の間隔を設けること

## 非機能要件

- ログイン不要（商品ページは公開）
- httpx を使って HTML を取得し、`__NEXT_DATA__` JSON をパース
- 取得失敗した商品はスキップしてログに記録、処理を継続する
- 既存 DB との互換性を保つ（新カラム追加はマイグレーション方式）

## 受け入れ条件

- [ ] `python -m src.main fetch-details --limit 3` で3件の詳細が取得・更新される
- [ ] `python -m src.main fetch-details` 実行後、DB の商品に condition が入っている
- [ ] 2回目以降の実行で取得済み商品がスキップされる
- [ ] 途中で失敗した商品があっても処理が止まらない
