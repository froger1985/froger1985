from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
import yaml

from src.alerts.notifier import send_alert
from src.analysis.profit_calculator import calculate_profit
from src.config import CONFIG, DB_PATH
from src.db.database import Database
from src.db.models import SourceListing, WatchlistItem
from src.scrapers.base import BaseScraper
from src.scrapers.ebay import EbayAPI
from src.scrapers.ebay_serpapi import EbaySerpAPI
from src.scrapers.hardoff import HardOffScraper
from src.scrapers.mercari import MercariScraper
from src.scrapers.yahoo_auction import YahooAuctionScraper
from src.utils.currency import get_usd_to_jpy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SCRAPERS: dict[str, type[BaseScraper]] = {
    "hardoff": HardOffScraper,
    "yahoo": YahooAuctionScraper,
    "mercari": MercariScraper,
}

BASE_DIR = Path(__file__).resolve().parent.parent


# --- Pipeline ---

async def run_pipeline(
    sources: list[str] | None = None,
    category: str | None = None,
    dry_run: bool = False,
):
    """Main sourcing pipeline: scrape → check eBay prices → calculate profit → alert."""
    db = Database(DB_PATH)
    # Prefer SerpAPI for sold data; fall back to Browse API if key is missing
    from src.config import EBAY_CLIENT_ID
    serpapi = EbaySerpAPI()
    ebay_browse = EbayAPI() if EBAY_CLIENT_ID else None

    async def _get_ebay_data(title: str) -> dict:
        data = await serpapi.get_average_sold_price(title, limit=60)
        if data["sold_count"] == 0 and ebay_browse:
            data = await ebay_browse.get_average_sold_price(title, limit=30)
        return data

    # Get exchange rate
    rate = await get_usd_to_jpy()
    logger.info("Exchange rate: 1 USD = %.2f JPY", rate)

    # Load watchlist from DB
    watchlist = db.get_watchlist(category)
    if not watchlist:
        logger.warning("Watchlist is empty. Add items with: sourcing-tool watchlist add <category> <keyword>")
        return

    logger.info("Loaded %d watchlist items", len(watchlist))

    # Determine which scrapers to use
    active_sources = sources or list(SCRAPERS.keys())
    scrapers: list[BaseScraper] = []
    for name in active_sources:
        if name in SCRAPERS:
            scrapers.append(SCRAPERS[name]())
        else:
            logger.warning("Unknown source: %s", name)

    if not scrapers:
        logger.error("No valid sources specified")
        return

    # Phase 1: Scrape all sources for all watchlist keywords
    all_listings: list[SourceListing] = []
    for item in watchlist:
        logger.info("Searching for: '%s' (%s)", item.keyword, item.category)
        tasks = [scraper.search(item.keyword, item.category) for scraper in scrapers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Scraper error: %s", result)
                continue
            all_listings.extend(result)

    logger.info("Total items scraped: %d", len(all_listings))

    # Phase 2: Dedup and save to DB
    new_count = 0
    for listing in all_listings:
        if not db.listing_exists(listing.source, listing.source_id):
            listing_id = db.upsert_listing(listing)
            listing.id = listing_id
            new_count += 1

    logger.info("New items: %d (skipped %d duplicates)", new_count, len(all_listings) - new_count)

    # Phase 3: Analyze new listings
    new_listings = db.get_new_listings()
    buy_count = 0
    watch_count = 0

    for listing in new_listings:
        # Check eBay sold prices (SerpAPI preferred, Browse API fallback)
        ebay_data = await _get_ebay_data(listing.title)

        if ebay_data["sold_count"] == 0:
            db.update_listing_status(listing.id, "analyzed")
            continue

        # Save eBay data
        for sold_item in ebay_data.get("items", []):
            db.save_ebay_sold(sold_item)

        # Calculate profit
        analysis = calculate_profit(
            listing=listing,
            ebay_avg_price_usd=ebay_data["avg_price_usd"],
            ebay_sold_count=ebay_data["sold_count"],
            usd_jpy_rate=rate,
        )
        db.save_analysis(analysis)

        if analysis.recommendation == "buy":
            buy_count += 1
            db.update_listing_status(listing.id, "alerted")
            if not dry_run:
                channels = await send_alert(listing, analysis, rate)
                if channels:
                    for ch in channels:
                        db.save_alert(listing.id, ch, "")
        elif analysis.recommendation == "watch":
            watch_count += 1
            db.update_listing_status(listing.id, "analyzed")
        else:
            db.update_listing_status(listing.id, "analyzed")

    # Cleanup
    for scraper in scrapers:
        await scraper.close()
    await serpapi.close()
    if ebay_browse:
        await ebay_browse.close()
    db.close()

    logger.info(
        "Pipeline complete: %d analyzed, %d BUY, %d WATCH",
        len(new_listings), buy_count, watch_count,
    )


# --- CLI ---

@click.group()
def cli():
    """sourcing-tool: Automated eBay sourcing for used games & audio gear."""
    pass


@cli.command()
@click.option("--source", "-s", multiple=True, help="Sources to scrape (hardoff, yahoo, mercari)")
@click.option("--category", "-c", type=click.Choice(["game", "audio"]), help="Filter by category")
@click.option("--dry-run", is_flag=True, help="Analyze only, don't send alerts")
def scan(source: tuple[str, ...], category: str | None, dry_run: bool):
    """Run the sourcing pipeline: scrape → analyze → alert."""
    sources = list(source) if source else None
    asyncio.run(run_pipeline(sources=sources, category=category, dry_run=dry_run))


@cli.group()
def watchlist():
    """Manage the watchlist (keywords to search for)."""
    pass


@watchlist.command("add")
@click.argument("category", type=click.Choice(["game", "audio"]))
@click.argument("keyword")
@click.option("--min-profit", default=0.30, help="Minimum profit rate (default: 0.30)")
@click.option("--max-price", default=None, type=int, help="Max buy price in JPY")
def watchlist_add(category: str, keyword: str, min_profit: float, max_price: int | None):
    """Add a keyword to the watchlist."""
    db = Database(DB_PATH)
    item = WatchlistItem(
        category=category,
        keyword=keyword,
        min_profit_rate=min_profit,
        max_buy_price_jpy=max_price,
    )
    item_id = db.add_watchlist_item(item)
    db.close()
    click.echo(f"Added to watchlist [#{item_id}]: {category} / '{keyword}'")


@watchlist.command("list")
@click.option("--category", "-c", type=click.Choice(["game", "audio"]), help="Filter by category")
def watchlist_list(category: str | None):
    """Show the current watchlist."""
    db = Database(DB_PATH)
    items = db.get_watchlist(category)
    db.close()

    if not items:
        click.echo("Watchlist is empty. Add items with: sourcing-tool watchlist add <category> <keyword>")
        return

    click.echo(f"\n{'ID':>4}  {'Category':<8}  {'Keyword':<40}  {'Min Profit':>10}  {'Max Price':>10}")
    click.echo("-" * 80)
    for item in items:
        max_price = f"¥{item.max_buy_price_jpy:,}" if item.max_buy_price_jpy else "—"
        click.echo(
            f"{item.id:>4}  {item.category:<8}  {item.keyword:<40}  "
            f"{item.min_profit_rate:>9.0%}  {max_price:>10}"
        )
    click.echo()


@watchlist.command("import")
@click.argument("yaml_file", type=click.Path(exists=True))
def watchlist_import(yaml_file: str):
    """Import watchlist from a YAML file."""
    with open(yaml_file) as f:
        data = yaml.safe_load(f)

    db = Database(DB_PATH)
    count = 0
    for category, keywords in data.items():
        if category not in ("game", "audio"):
            click.echo(f"Skipping unknown category: {category}")
            continue
        for entry in keywords:
            if isinstance(entry, str):
                keyword = entry
                opts = {}
            elif isinstance(entry, dict):
                keyword = entry.get("keyword", "")
                opts = entry
            else:
                continue

            if not keyword:
                continue

            item = WatchlistItem(
                category=category,
                keyword=keyword,
                min_profit_rate=opts.get("min_profit_rate", 0.30),
                max_buy_price_jpy=opts.get("max_buy_price_jpy"),
            )
            db.add_watchlist_item(item)
            count += 1

    db.close()
    click.echo(f"Imported {count} items to watchlist")


@cli.command()
def status():
    """Show summary of scraped data and analysis results."""
    db = Database(DB_PATH)

    total = db.conn.execute("SELECT COUNT(*) FROM source_listings").fetchone()[0]
    new = db.conn.execute("SELECT COUNT(*) FROM source_listings WHERE status='new'").fetchone()[0]
    alerted = db.conn.execute("SELECT COUNT(*) FROM source_listings WHERE status='alerted'").fetchone()[0]
    analyses = db.conn.execute("SELECT COUNT(*) FROM analysis_results").fetchone()[0]
    buys = db.conn.execute("SELECT COUNT(*) FROM analysis_results WHERE recommendation='buy'").fetchone()[0]

    click.echo(f"\n📊 Sourcing Tool Status")
    click.echo(f"  Total listings: {total}")
    click.echo(f"  New (unanalyzed): {new}")
    click.echo(f"  Alerted (buy): {alerted}")
    click.echo(f"  Total analyses: {analyses}")
    click.echo(f"  Buy recommendations: {buys}")

    # Top opportunities
    rows = db.conn.execute(
        """SELECT sl.title, sl.source, sl.price_jpy, sl.url,
                  ar.estimated_profit_jpy, ar.profit_rate, ar.ebay_avg_price_usd
           FROM analysis_results ar
           JOIN source_listings sl ON sl.id = ar.source_listing_id
           WHERE ar.recommendation = 'buy'
           ORDER BY ar.estimated_profit_jpy DESC
           LIMIT 10"""
    ).fetchall()

    if rows:
        click.echo(f"\n🏆 Top Opportunities:")
        for r in rows:
            click.echo(
                f"  ¥{r['estimated_profit_jpy']:>6,} ({r['profit_rate']:>5.0%}) "
                f"| ¥{r['price_jpy']:,} → ${r['ebay_avg_price_usd']:.0f} "
                f"| {r['title'][:50]}"
            )
            click.echo(f"    {r['url']}")

    db.close()
    click.echo()


if __name__ == "__main__":
    cli()
