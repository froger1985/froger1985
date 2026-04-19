# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

日本ニッチ商品のeBay無在庫輸出を自動化するツール群。メルカリ・ヤフオク・HardOffで仕入れ候補を発見し、eBayの売却実績と突き合わせて利益計算・通知を行う。目標: 1日1時間の作業で月10万円。

---

## ツール構成

| コンポーネント | 概要 |
|---|---|
| `sourcing-tool/ebay_sold_analyzer.py` | スタンドアロン版。SerpAPI経由でeBay売却済みデータを収集・集計してCSV出力 |
| `sourcing-tool/src/` | パッケージ版。スクレイパー・DB・利益計算・通知をフル自動化するパイプライン |
| `Code.gs` | Google Apps Script。WebアプリとしてGmailドラフトを生成する |
| `index.html` | GTMテスト用ページ（GTM-NG5LV9LH） |

---

## sourcing-tool コマンド

セットアップ（初回のみ）:
```bash
cd sourcing-tool
pip install -r requirements.txt
cp .env.example .env   # .env を編集して SERPAPI_KEY を設定
```

### スタンドアロン版（ebay_sold_analyzer.py）

```bash
# 70キーワードで全体探索（API約70回消費）
python ebay_sold_analyzer.py --discover --pages 1 --output data/full_discovery.csv

# 指定キーワードで検索
python ebay_sold_analyzer.py --keywords "parappa rapper,smart doll" --pages 1 --output data/test.csv
```

### パッケージ版（src/main.py）

```bash
# ウォッチリストに追加
python -m src.main watchlist add game "parappa rapper figure"
python -m src.main watchlist add audio "sony walkman"

# YAMLからまとめてインポート
python -m src.main watchlist import keywords.yaml

# ウォッチリスト確認
python -m src.main watchlist list

# スキャン実行（通知なしのテスト）
python -m src.main scan --dry-run

# 本番スキャン（Slack/LINEに通知が飛ぶ）
python -m src.main scan

# ソースを絞って実行
python -m src.main scan --source mercari --source yahoo

# DB内の状態確認
python -m src.main status
```

---

## アーキテクチャ（パッケージ版）

パイプラインは `src/main.py` の `run_pipeline()` が制御する。

```
run_pipeline()
  ├── 1. 仕入れ先スクレイピング（並列 asyncio.gather）
  │     MercariScraper / YahooAuctionScraper / HardOffScraper
  │     → src/scrapers/base.py の BaseScraper を継承
  │
  ├── 2. DB保存・重複排除
  │     SQLite（data/sourcing.db）
  │     src/db/database.py + src/db/models.py（SourceListing, WatchlistItem）
  │
  ├── 3. eBay売却価格チェック
  │     src/scrapers/ebay.py（EbayAPI）
  │
  ├── 4. 利益計算
  │     src/analysis/profit_calculator.py
  │     設定値は config.yaml（eBay手数料13.25%、最低利益率30%など）
  │
  └── 5. 通知（recommendation == "buy" のみ）
        src/alerts/notifier.py（Slack / LINE Notify / console）
```

**新スクレイパーを追加する場合**: `BaseScraper` を継承し、`search(keyword, category) -> list[SourceListing]` を実装して `src/main.py` の `SCRAPERS` 辞書に登録する。

---

## 環境変数（sourcing-tool/.env）

| 変数 | 必須 | 用途 |
|---|---|---|
| `SERPAPI_KEY` | 必須 | eBayデータ取得（無料100回/月） |
| `SLACK_WEBHOOK_URL` | 任意 | 買い推奨アラート通知 |
| `LINE_NOTIFY_TOKEN` | 任意 | 同上 |
| `EBAY_CLIENT_ID/SECRET` | 任意 | 将来の拡張用 |
| `EXCHANGE_RATE_API_KEY` | 任意 | 未設定時は固定レートを使用 |

---

## 利益計算ロジック

`config.yaml` の値を参照:
- eBay手数料: 13.25%
- 決済手数料: 2.9% + $0.30
- 最低利益率: 30%（`min_profit_rate`）
- 最低販売実績: 90日で3件（`min_ebay_sold_count`）

recommendation は `"buy"` / `"watch"` / `"skip"` の3値。

---

## データ出力

- スタンドアロン版: `sourcing-tool/data/` 以下に `*_summary.csv`（キーワード集計）と `*_items.csv`（全商品リスト）
- パッケージ版: `sourcing-tool/data/sourcing.db`（SQLite）

過去の探索結果は `data/discovery_YYYYMMDD_HHMMSS.*` 形式で蓄積している。
