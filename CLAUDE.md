# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Personal eBay export resale tool. Scrapes Mercari Japan for sourcing candidates (keyword search and liked items), analyzes eBay sold prices, calculates profit, and sends alerts. All active code lives in `sourcing-tool/`.

The root also contains `ebay_sold_analyzer.py` (standalone legacy script run by GitHub Actions weekly) and `index.html`/`main.js`/`Code.gs` (unrelated Google Apps Script project).

## Commands

All commands must be run from `sourcing-tool/`:

```bash
cd sourcing-tool

# First-time setup
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then fill in SERPAPI_KEY

# Fetch Mercari liked items (opens browser on first run for login)
python -m src.main likes --no-save    # preview only
python -m src.main likes --save       # save to DB

# Keyword-based sourcing pipeline (scrape → eBay check → profit analysis → alert)
python -m src.main scan
python -m src.main scan --source mercari --category game --dry-run

# Watchlist management
python -m src.main watchlist add game "ゲームボーイ"
python -m src.main watchlist list
python -m src.main watchlist import config.yaml

# DB status summary
python -m src.main status
```

## Architecture

### Two independent pipelines

**`scan` pipeline** — keyword-driven, fully automated:
`watchlist keywords → BaseScraper.search() → source_listings DB → EbayAPI → profit_calculator → alerts`

**`likes` pipeline** — authenticated Mercari scraping:
`MercariLikesScraper (Playwright) → intercepts /v1/likedProducts API → source_listings DB`

Both pipelines write to the same `source_listings` table. The `source` column distinguishes them (`"mercari"`, `"hardoff"`, `"yahoo_auction"` vs `"mercari_likes"`).

### Key design decisions

**`MercariLikesScraper` does not extend `BaseScraper`** — `BaseScraper` is built around `search(keyword, category)`. Liked items have no keyword and require user authentication, so `MercariLikesScraper` is a standalone class with `fetch_all_likes()`.

**Playwright runs headed (visible browser)** — headless mode triggers Mercari's bot detection. The browser session is saved to `data/mercari_session.json` after first login so subsequent runs are automatic.

**Mercari `/v1/likedProducts` API quirks** — responses nest product data under a `"product"` key with non-standard field names: `originId` (not `id`), `displayName` (not `name`), `price` as a string. This differs from the search API used by `MercariScraper`. The response also includes `stockState` (e.g. `PRODUCT_STOCK_STATE_OUT_OF_STOCK`) and `thumbnail` (single low-res image). Condition, description, and full-size images are **not** available from this endpoint — they must be fetched from individual item pages (`https://jp.mercari.com/item/{originId}`).

**`config.yaml` is the source of truth for all numeric constants** — fee rates, shipping estimates, profit thresholds, rate limits. Never hardcode these in source files.

**DB schema is managed via `_SCHEMA` in `database.py`** — `CREATE TABLE IF NOT EXISTS` on every startup; no migration framework. Adding columns requires both the schema string and any new methods in `Database`.

**Windows encoding** — `config.yaml` is UTF-8. `open()` calls must use `encoding="utf-8"` explicitly (Windows defaults to cp932).

### Data models (`src/db/models.py`)

- `SourceListing` — sourced item from any channel. `(source, source_id)` is the unique key. `category` is `"game"`, `"audio"`, or `"unknown"` (likes items). `status` lifecycle: `new → analyzed → alerted/purchased/skipped`.
- `AnalysisResult` — profit calculation output, linked to `SourceListing`.
- `EbaySold` — raw eBay sold price records used to compute averages.
- `WatchlistItem` — keywords for the scan pipeline.

### Environment variables (`.env`)

- `SERPAPI_KEY` — required for `EbayAPI` (eBay sold price lookup via SerpAPI)
- `SLACK_WEBHOOK_URL`, `LINE_NOTIFY_TOKEN` — optional alert channels
- `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` — reserved for future eBay listing API

### GitHub Actions

`.github/workflows/ebay-analysis.yml` runs `ebay_sold_analyzer.py` (the legacy standalone script, **not** `src/main.py`) on a weekly schedule and commits results CSV to `sourcing-tool/data/`. This workflow is independent of the `sourcing-tool/src/` codebase.

## Planned pipeline (end-to-end)

```
likes (done) → fetch-details → calculate eBay price → eBay listing → sold-out removal
```

- **fetch-details** (Step 2, next): fetch condition, description, full images from each item's Mercari page via `__NEXT_DATA__` JSON embedded in the HTML. Items with `stockState=PRODUCT_STOCK_STATE_OUT_OF_STOCK` are stored but skipped for listing.
- **sold-out removal**: when a liked item goes out of stock, remove its eBay listing. Deferred until eBay listing is implemented.

## Navigation

Steering documents for in-progress tasks: `.steering/<date>-<task>/` (requirements, design, tasklist).
Permanent architecture docs: `docs/`.
