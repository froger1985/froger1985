"""
mercari-ebay: メルカリ「いいね」商品をeBayに自動出品・在庫同期するCLIツール

使い方:
  python main.py import-favorites          # メルカリいいね一覧をeBayに出品
  python main.py add-item <URL or ID>      # 個別商品を追加・出品
  python main.py sync                      # 在庫・価格チェック（1日3回cron実行）
  python main.py status                    # 出品状況ダッシュボード
  python main.py list-items               # 全トラッキング商品を表示
"""
from __future__ import annotations

import asyncio
import logging
import sys

import click

from src.config import DB_PATH
from src.db.database import Database
from src.sync.syncer import Syncer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@click.group()
@click.option("--dry-run", is_flag=True, envvar="DRY_RUN",
              help="実行せずに処理内容をログ表示のみ（API呼び出しなし）")
@click.pass_context
def cli(ctx, dry_run: bool):
    """mercari-ebay: メルカリ→eBay 自動出品・在庫同期ツール"""
    ctx.ensure_object(dict)
    ctx.obj["dry_run"] = dry_run
    if dry_run:
        click.echo("[DRY RUN モード] API呼び出しは行いません")


@cli.command("import-favorites")
@click.option("--pages", default=10, show_default=True,
              help="メルカリお気に入りの最大取得ページ数")
@click.pass_context
def import_favorites(ctx, pages: int):
    """
    メルカリの「いいね」した商品をすべて取得し、eBayに新規出品します。

    事前にMERCARI_SESSION_TOKENを.envに設定してください。
    """
    async def run():
        db = Database(DB_PATH)
        syncer = Syncer(db, dry_run=ctx.obj["dry_run"])
        try:
            count = await syncer.import_favorites(max_pages=pages)
            click.echo(f"新規出品完了: {count}件")
        finally:
            await syncer.close()
            db.close()

    asyncio.run(run())


@cli.command("add-item")
@click.argument("mercari_url_or_id")
@click.pass_context
def add_item(ctx, mercari_url_or_id: str):
    """
    メルカリ商品URLまたはIDを指定して個別にトラッキング・eBay出品します。

    例: python main.py add-item https://jp.mercari.com/item/m12345678
        python main.py add-item m12345678
    """
    async def run():
        db = Database(DB_PATH)
        syncer = Syncer(db, dry_run=ctx.obj["dry_run"])
        try:
            success = await syncer.add_item(mercari_url_or_id)
            if success:
                click.echo(f"追加完了: {mercari_url_or_id}")
            else:
                click.echo(f"追加失敗またはスキップ: {mercari_url_or_id}", err=True)
                sys.exit(1)
        finally:
            await syncer.close()
            db.close()

    asyncio.run(run())


@cli.command("sync")
@click.pass_context
def sync(ctx):
    """
    全アクティブ出品の在庫・価格をメルカリで確認し、eBayに反映します。

    ・メルカリで売り切れ → eBay出品を自動停止
    ・メルカリで価格変動 → eBay価格を自動更新
    ・急変時はLINE/Slackに通知

    このコマンドをGitHub Actionsで1日3回（cron）実行します。
    """
    async def run():
        db = Database(DB_PATH)
        syncer = Syncer(db, dry_run=ctx.obj["dry_run"])
        try:
            log = await syncer.sync()
            click.echo(
                f"Sync完了: チェック={log.items_checked}件 | "
                f"売切れ停止={log.sold_out_count}件 | "
                f"価格更新={log.price_updated_count}件 | "
                f"エラー={log.errors}件 | "
                f"所要時間={log.duration_sec:.1f}秒"
            )
        finally:
            await syncer.close()
            db.close()

    asyncio.run(run())


@cli.command("status")
def status():
    """出品状況のサマリーダッシュボードを表示します。"""
    db = Database(DB_PATH)
    counts = db.count_by_ebay_status()
    total = sum(counts.values())

    click.echo("\n" + "=" * 55)
    click.echo("  mercari-ebay ダッシュボード")
    click.echo("=" * 55)
    click.echo(f"  合計トラッキング商品: {total}件")
    click.echo(f"  eBay出品中 (active) : {counts.get('active', 0)}件")
    click.echo(f"  出品待ち  (pending) : {counts.get('pending', 0)}件")
    click.echo(f"  停止済み  (ended)   : {counts.get('ended', 0)}件")
    click.echo(f"  エラー    (error)   : {counts.get('error', 0)}件")

    # Recent sync logs
    logs = db.get_recent_sync_logs(limit=5)
    if logs:
        click.echo("\n  直近のSync履歴:")
        click.echo(f"  {'日時':<20} {'チェック':>6} {'売切':>4} {'価格更新':>6} {'エラー':>4} {'秒':>5}")
        click.echo("  " + "-" * 50)
        for log in logs:
            click.echo(
                f"  {log.run_at.strftime('%Y-%m-%d %H:%M'):<20} "
                f"{log.items_checked:>6} "
                f"{log.sold_out_count:>4} "
                f"{log.price_updated_count:>6} "
                f"{log.errors:>4} "
                f"{log.duration_sec:>5.1f}"
            )

    db.close()
    click.echo("=" * 55 + "\n")


@cli.command("list-items")
@click.option("--status", "filter_status",
              type=click.Choice(["active", "pending", "ended", "error", "all"]),
              default="active", show_default=True)
@click.option("--limit", default=50, show_default=True)
def list_items(filter_status: str, limit: int):
    """トラッキング中の商品一覧を表示します。"""
    db = Database(DB_PATH)
    all_items = db.get_all_items()

    if filter_status != "all":
        items = [i for i in all_items if i.ebay_status == filter_status]
    else:
        items = all_items

    items = items[:limit]

    if not items:
        click.echo(f"対象商品なし (status={filter_status})")
        db.close()
        return

    click.echo(
        f"\n{'ID':>4}  {'メルカリID':<12}  {'eBay status':<10}  "
        f"{'¥価格':>8}  {'$価格':>7}  タイトル"
    )
    click.echo("-" * 85)
    for item in items:
        click.echo(
            f"{item.id or 0:>4}  {item.mercari_id:<12}  {item.ebay_status:<10}  "
            f"¥{item.mercari_price_jpy:>6,}  ${item.ebay_price_usd:>6.2f}  "
            f"{item.title[:35]}"
        )
    click.echo(f"\n計 {len(items)} 件\n")
    db.close()


if __name__ == "__main__":
    cli()
