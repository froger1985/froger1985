# アーキテクチャ概要

## システム全体像

```
┌─────────────────────────────────────────────────────┐
│                  CLI (src/main.py)                   │
│   scan | likes | watchlist | status                  │
└────────────────┬───────────────────────┬─────────────┘
                 │                       │
    ┌────────────▼──────────┐  ┌────────▼────────────┐
    │   scan パイプライン    │  │  likes パイプライン  │
    │（キーワード検索→分析） │  │ （いいね取得→保存）  │
    └────────────┬──────────┘  └────────┬────────────┘
                 │                       │
    ┌────────────▼──────────┐  ┌────────▼────────────┐
    │  BaseScraper サブクラス │  │  MercariLikesScraper │
    │  - MercariScraper      │  │  (Playwright)        │
    │  - HardOffScraper      │  └────────┬────────────┘
    │  - YahooAuctionScraper │           │ 認証済みブラウザ
    └────────────┬──────────┘           │ でネットワーク傍受
                 │                      │
    ┌────────────▼──────────────────────▼─────────────┐
    │              src/db/database.py (SQLite)          │
    │  source_listings / analysis_results / watchlist   │
    └───────────────────────────────────────────────────┘
                 │
    ┌────────────▼──────────┐
    │   src/scrapers/ebay.py │  ← scan パイプラインのみ使用
    │   EbayAPI              │
    └────────────┬──────────┘
                 │
    ┌────────────▼──────────┐
    │  profit_calculator.py  │  ← scan パイプラインのみ使用
    └────────────┬──────────┘
                 │
    ┌────────────▼──────────┐
    │  src/alerts/notifier.py│  ← scan パイプラインのみ使用
    └───────────────────────┘
```

## コンポーネント説明

### CLI レイヤー（`src/main.py`）

Click ベースの CLI エントリーポイント。2つの独立したパイプラインを持つ。

| コマンド | 用途 |
|---|---|
| `scan` | キーワードでメルカリ/ハードオフ/ヤフオクを検索し、eBay価格を調べる |
| `likes` | メルカリのいいね商品を取得して DB に保存する（新規） |
| `watchlist` | 検索キーワードを管理する |
| `status` | DB の状態サマリーを表示する |

### スクレイパーレイヤー（`src/scrapers/`）

**`BaseScraper`（`base.py`）**：キーワード検索スクレイパーの基底クラス。
- `search(keyword, category) -> list[SourceListing]` を抽象メソッドとして定義
- httpx.AsyncClient を内包し、レートリミット・UA 設定を管理

**`MercariScraper`、`HardOffScraper`、`YahooAuctionScraper`**：`BaseScraper` サブクラス。匿名 HTTP リクエストでキーワード検索を実行。

**`MercariLikesScraper`**（新規）：`BaseScraper` を継承**しない**独立クラス。
- キーワード検索ではなく「認証済みユーザーのいいね一覧取得」が責務
- Playwright でブラウザを操作し、メルカリのいいねページが内部的に呼び出す API のレスポンスを傍受
- セッションを `data/mercari_session.json` にファイル保存し、再起動後もログイン不要

**`EbayAPI`（`ebay.py`）**：eBay の落札済み商品を検索し、平均売却価格を返す。

### 分析レイヤー（`src/analysis/`）

**`profit_calculator.py`**：出品価格の計算を担当。
```
eBay落札平均価格(JPY) - 仕入れ価格 - 国際送料 - eBay手数料 - 決済手数料 = 利益
```
カテゴリ（game/audio）と商品タイトルに基づいて送料を推定する。

### データレイヤー（`src/db/`）

**`database.py`**：sqlite3 直接使用（ORM なし）。`DB_PATH` は `config.py` から取得。

**`models.py`**：dataclass ベースのデータモデル。

| モデル | 用途 |
|---|---|
| `SourceListing` | 仕入れ候補商品（scan/likes 共通） |
| `EbaySold` | eBay 落札実績 |
| `AnalysisResult` | 利益分析結果（scan パイプラインのみ） |
| `WatchlistItem` | 検索キーワード（scan パイプラインのみ） |

`SourceListing.category` は scan では `"game"/"audio"`、likes では `"unknown"` を使用。

### アラートレイヤー（`src/alerts/`）

Slack / LINE への通知送信。scan パイプラインのみが利用する。likes パイプラインでは使用しない。

### ユーティリティ（`src/utils/`）

**`currency.py`**：外部 API から USD/JPY レートを取得・変換する。

### 設定（`src/config.py`、`config.yaml`）

`config.yaml` からスクレイピング設定・送料設定・利益計算パラメータを読み込み、`CONFIG` dict として全モジュールに提供する。

---

## 技術スタック

| 役割 | ライブラリ |
|---|---|
| CLI フレームワーク | click |
| 非同期 HTTP クライアント | httpx (asyncio) |
| ブラウザ自動化 | playwright (Chromium) |
| データベース | sqlite3（標準ライブラリ） |
| 設定ファイル | PyYAML |
| 通貨レート取得 | httpx（外部 API） |

---

## データフロー

### scan パイプライン

```
config.yaml の watchlist キーワード
  → BaseScraper.search() で各サイトを並列スクレイプ
  → source_listings テーブルに upsert（重複スキップ）
  → EbayAPI で落札価格取得 → ebay_sold テーブルに保存
  → calculate_profit() で利益計算 → analysis_results テーブルに保存
  → 閾値超えなら send_alert() で Slack/LINE 通知
```

### likes パイプライン（新規）

```
MercariLikesScraper.fetch_all_likes()
  → Playwright でブラウザ起動（セッション読み込み or 手動ログイン）
  → jp.mercari.com/mypage/likes へ遷移
  → スクロールしながらネットワークレスポンスを傍受
  → source_listings テーブルに upsert（source="mercari_likes", category="unknown"）
  → コンソールに一覧出力
```

---

## 設計上の決定事項

### `MercariLikesScraper` は `BaseScraper` を継承しない

`BaseScraper` の抽象メソッド `search(keyword, category)` は「キーワード検索」を前提とする。いいね取得は「ユーザー認証済みの全件取得」であり、責務が根本的に異なる。無理に継承するとインタフェースが嘘になるため、独立クラスとした。

### Playwright を選んだ理由

メルカリのいいね API は JWT 署名付きの認証が必要であり、これをリバースエンジニアリングすると Mercari のサービス変更のたびに壊れるリスクが高い。Playwright で実際のブラウザを動かすことで、Mercari のフロントエンドが認証を処理し、我々はレスポンスを傍受するだけでよい。

### ORM を使わない

既存コードが sqlite3 直接使用で統一されているため、ORM は導入しない。シンプルさを維持する。
