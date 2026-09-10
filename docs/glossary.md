# 用語集

## ビジネス用語

| 用語 | 説明 |
|---|---|
| **いいね（likes）** | メルカリでユーザーが気に入った商品に付けるお気に入りマーク。このシステムではいいねした商品を仕入れ候補として扱う |
| **仕入れ価格** | メルカリでの商品購入価格（円） |
| **eBay出品価格** | 仕入れ価格に国際送料・各種手数料を加えて設定するeBayでの販売価格 |
| **国際送料** | 日本からeBay購入者（主に海外）へ発送する際の送料。カテゴリ・商品サイズにより異なる |
| **eBay手数料（FVF）** | eBay の Final Value Fee。落札価格の約13.25% |
| **決済手数料** | PayPal 等の決済サービス手数料 |
| **ウォッチリスト** | scan パイプラインで検索するキーワードのリスト |

## 技術用語

| 用語 | 説明 |
|---|---|
| **scan パイプライン** | キーワードでメルカリ/ハードオフ/ヤフオクを検索し、eBay価格調査・利益計算・通知まで行う既存パイプライン |
| **likes パイプライン** | メルカリのいいね商品を取得して DB に保存する新規パイプライン |
| **BaseScraper** | キーワード検索スクレイパーの基底クラス。`search(keyword, category)` を抽象メソッドとして定義 |
| **MercariLikesScraper** | Playwright でメルカリのいいね一覧を取得する独立クラス。BaseScraper を継承しない |
| **Playwright** | Microsoft 製のブラウザ自動化ライブラリ。Chromium を制御してメルカリにログインし、いいねページの API レスポンスを傍受する |
| **ネットワーク傍受** | Playwright の `page.on("response")` を使い、ブラウザが受け取る API レスポンスを Python 側でキャプチャする手法 |
| **セッションファイル** | Playwright がブラウザのログイン状態（Cookie・localStorage）を保存するファイル（`data/mercari_session.json`）。再起動後もログイン不要にするために使用 |
| **SourceListing** | 仕入れ候補商品を表す dataclass。scan/likes 両パイプラインで共通して使用 |
| **upsert** | INSERT または UPDATE の合成語。`source_id` が既存なら更新、なければ挿入する操作 |
| **source** | 商品の取得元を示す文字列。例: `"mercari"`（キーワード検索）、`"mercari_likes"`（いいね取得）、`"hardoff"` 等 |
| **source_id** | 各ソースサイト上での商品ID。`source` と組み合わせて一意に商品を識別する |
| **category** | 商品カテゴリ。`"game"`（ゲーム機・ソフト）、`"audio"`（オーディオ機器）、`"unknown"`（いいね経由で未分類） |
| **status** | SourceListing のライフサイクル状態。`"new"` → `"analyzed"` → `"alerted"` / `"purchased"` / `"skipped"` |
| **DPoP** | Demonstrating Proof-of-Possession。OAuth 2.0 の拡張仕様。メルカリ内部 API の認証に関連するが、Playwright 方式では考慮不要 |
| **JWT** | JSON Web Token。メルカリの内部 API リクエストに使われる署名付きトークン。Playwright 方式では考慮不要 |

## ソースコード内の略語

| 略語 | 正式名 |
|---|---|
| `jpy` | Japanese Yen（日本円） |
| `usd` | US Dollar（米ドル） |
| `FVF` | Final Value Fee（eBay落札手数料） |
| `EMS` | Express Mail Service（国際スピード郵便） |
| `cfg` | configuration（設定） |
| `db` | database（データベース） |
