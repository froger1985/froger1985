#!/usr/bin/env python3
"""
eBay Sold Listings Analyzer — Prototype
========================================
eBayの売却済みデータをスクレイピングし、
日本発のニッチ商品の傾向を分析するツール。

使い方:
  python ebay_sold_analyzer.py --keywords "japanese anime figure,japanese vintage toy"
  python ebay_sold_analyzer.py --discover   # 自動発掘モード
  python ebay_sold_analyzer.py --file keywords.txt  # ファイルからキーワード読み込み
"""

import argparse
import csv
import json
import re
import time
import random
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode

try:
    import httpx
except ImportError:
    print("httpx が必要です: pip install httpx")
    sys.exit(1)

try:
    from selectolax.parser import HTMLParser
except ImportError:
    HTMLParser = None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("selectolax または beautifulsoup4 が必要です:")
        print("  pip install selectolax")
        print("  または pip install beautifulsoup4")
        sys.exit(1)


# =====================================================
# Data Models
# =====================================================

@dataclass
class SoldItem:
    """eBayで売れた商品1件"""
    title: str
    price_usd: float
    sold_date: str
    shipping_usd: Optional[float] = None
    seller: Optional[str] = None
    seller_location: Optional[str] = None
    item_url: Optional[str] = None
    condition: Optional[str] = None
    keyword: str = ""


@dataclass
class KeywordAnalysis:
    """キーワードごとの分析結果"""
    keyword: str
    total_sold: int = 0
    avg_price_usd: float = 0.0
    min_price_usd: float = 0.0
    max_price_usd: float = 0.0
    median_price_usd: float = 0.0
    unique_sellers: int = 0
    japan_sellers: int = 0
    non_japan_sellers: int = 0
    suspected_japan_sellers: int = 0  # 偽装セラー
    competition_score: str = ""  # low / medium / high
    items: list = field(default_factory=list)


# =====================================================
# eBay Scraper
# =====================================================

# 日本関連を示すキーワード（発送元偽装の検出用）
JAPAN_INDICATORS = [
    "japan", "japanese", "jp", "jpy",
    "tokyo", "osaka", "kyoto",
    "anime", "manga", "otaku",
    "kawaii", "san-x", "sanrio",
    "nintendo", "sega", "capcom", "bandai", "takara", "tomy",
    "from japan", "ship from japan", "made in japan",
    "japan import", "japan exclusive", "japan only",
    "japan version", "japanese version",
]

# eBayスクレイピング用のUser-Agentローテーション
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]


def build_ebay_sold_url(keyword: str, page: int = 1, min_price: float = None, max_price: float = None) -> str:
    """eBay売却済み検索URLを組み立てる"""
    params = {
        "_nkw": keyword,
        "LH_Complete": "1",  # 完了したオークション
        "LH_Sold": "1",     # 売れたもののみ
        "_sop": "13",        # 新しい順にソート
        "_ipg": "60",        # 1ページ60件
    }
    if page > 1:
        params["_pgn"] = str(page)
    if min_price is not None:
        params["_udlo"] = str(min_price)
    if max_price is not None:
        params["_udhi"] = str(max_price)

    base_url = "https://www.ebay.com/sch/i.html"
    return f"{base_url}?{urlencode(params)}"


def get_http_client() -> httpx.Client:
    """HTTPクライアントを作成"""
    return httpx.Client(
        headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
        follow_redirects=True,
        timeout=30.0,
    )


def parse_price(price_text: str) -> Optional[float]:
    """価格テキストからUSD金額を抽出"""
    if not price_text:
        return None
    # $XX.XX のパターン
    match = re.search(r'\$?([\d,]+\.?\d*)', price_text.replace(',', ''))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def parse_sold_items_selectolax(html: str, keyword: str) -> list[SoldItem]:
    """selectolaxでeBay売却済みページをパース"""
    tree = HTMLParser(html)
    items = []

    # eBayの検索結果はs-item クラスのli要素
    for node in tree.css("li.s-item"):
        # タイトル
        title_node = node.css_first("div.s-item__title span[role='heading']")
        if not title_node:
            title_node = node.css_first("div.s-item__title span")
        if not title_node:
            title_node = node.css_first("h3.s-item__title")
        title = title_node.text(strip=True) if title_node else ""

        # "Shop on eBay" などのプロモーション行をスキップ
        if not title or "shop on ebay" in title.lower():
            continue

        # 価格
        price_node = node.css_first("span.s-item__price")
        price_text = price_node.text(strip=True) if price_node else ""
        price = parse_price(price_text)
        if price is None:
            continue

        # 送料
        shipping_node = node.css_first("span.s-item__shipping")
        shipping_text = shipping_node.text(strip=True) if shipping_node else ""
        shipping = None
        if "free" in shipping_text.lower():
            shipping = 0.0
        else:
            shipping = parse_price(shipping_text)

        # 売却日
        sold_node = node.css_first("span.POSITIVE")
        if not sold_node:
            sold_node = node.css_first("span.s-item__ended-date")
        sold_date = sold_node.text(strip=True) if sold_node else ""

        # URL
        link_node = node.css_first("a.s-item__link")
        item_url = link_node.attributes.get("href", "") if link_node else ""

        # セラー情報
        seller_node = node.css_first("span.s-item__seller-info-text")
        seller = seller_node.text(strip=True) if seller_node else ""

        # 商品状態
        condition_node = node.css_first("span.SECONDARY_INFO")
        condition = condition_node.text(strip=True) if condition_node else ""

        # セラーの場所
        location_node = node.css_first("span.s-item__location")
        location = location_node.text(strip=True) if location_node else ""

        items.append(SoldItem(
            title=title,
            price_usd=price,
            sold_date=sold_date,
            shipping_usd=shipping,
            seller=seller,
            seller_location=location,
            item_url=item_url,
            condition=condition,
            keyword=keyword,
        ))

    return items


def parse_sold_items_bs4(html: str, keyword: str) -> list[SoldItem]:
    """BeautifulSoupでeBay売却済みページをパース"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for li in soup.select("li.s-item"):
        # タイトル
        title_el = li.select_one("div.s-item__title span[role='heading']")
        if not title_el:
            title_el = li.select_one("div.s-item__title span")
        if not title_el:
            title_el = li.select_one("h3.s-item__title")
        title = title_el.get_text(strip=True) if title_el else ""

        if not title or "shop on ebay" in title.lower():
            continue

        # 価格
        price_el = li.select_one("span.s-item__price")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = parse_price(price_text)
        if price is None:
            continue

        # 送料
        shipping_el = li.select_one("span.s-item__shipping")
        shipping_text = shipping_el.get_text(strip=True) if shipping_el else ""
        shipping = None
        if "free" in shipping_text.lower():
            shipping = 0.0
        else:
            shipping = parse_price(shipping_text)

        # 売却日
        sold_el = li.select_one("span.POSITIVE")
        if not sold_el:
            sold_el = li.select_one("span.s-item__ended-date")
        sold_date = sold_el.get_text(strip=True) if sold_el else ""

        # URL
        link_el = li.select_one("a.s-item__link")
        item_url = link_el.get("href", "") if link_el else ""

        # セラー
        seller_el = li.select_one("span.s-item__seller-info-text")
        seller = seller_el.get_text(strip=True) if seller_el else ""

        # 状態
        condition_el = li.select_one("span.SECONDARY_INFO")
        condition = condition_el.get_text(strip=True) if condition_el else ""

        # 場所
        location_el = li.select_one("span.s-item__location")
        location = location_el.get_text(strip=True) if location_el else ""

        items.append(SoldItem(
            title=title,
            price_usd=price,
            sold_date=sold_date,
            shipping_usd=shipping,
            seller=seller,
            seller_location=location,
            item_url=item_url,
            condition=condition,
            keyword=keyword,
        ))

    return items


def parse_sold_items(html: str, keyword: str) -> list[SoldItem]:
    """利用可能なパーサーで売却済みアイテムをパース"""
    if HTMLParser is not None:
        return parse_sold_items_selectolax(html, keyword)
    else:
        return parse_sold_items_bs4(html, keyword)


def scrape_ebay_sold(keyword: str, max_pages: int = 2, delay_range: tuple = (2, 5)) -> list[SoldItem]:
    """eBayの売却済みリストをスクレイピング"""
    all_items = []
    client = get_http_client()

    for page in range(1, max_pages + 1):
        url = build_ebay_sold_url(keyword, page=page)
        print(f"  📡 Fetching: {keyword} (page {page}/{max_pages})...")

        try:
            response = client.get(url)
            if response.status_code != 200:
                print(f"  ⚠️  HTTP {response.status_code} for {keyword} page {page}")
                break

            items = parse_sold_items(response.text, keyword)
            if not items:
                print(f"  ℹ️  No more results for '{keyword}' at page {page}")
                break

            all_items.extend(items)
            print(f"  ✅ Found {len(items)} sold items (total: {len(all_items)})")

        except httpx.HTTPError as e:
            print(f"  ❌ Error fetching {keyword}: {e}")
            break

        # レート制限: ランダム遅延
        if page < max_pages:
            delay = random.uniform(*delay_range)
            print(f"  ⏳ Waiting {delay:.1f}s...")
            time.sleep(delay)

    client.close()
    return all_items


# =====================================================
# Analysis
# =====================================================

def is_japan_related(text: str) -> bool:
    """テキストに日本関連のキーワードが含まれるか"""
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in JAPAN_INDICATORS)


def detect_suspected_japan_seller(item: SoldItem) -> bool:
    """発送元を偽装している可能性のある日本セラーを検出"""
    location = (item.seller_location or "").lower()
    # 明示的に日本と書いてあるなら偽装ではない
    if "japan" in location:
        return False
    # 日本以外の発送元だが、タイトルが日本商品っぽい場合
    if location and "japan" not in location:
        if is_japan_related(item.title):
            return True
    return False


def analyze_keyword(keyword: str, items: list[SoldItem]) -> KeywordAnalysis:
    """キーワードごとの分析を行う"""
    analysis = KeywordAnalysis(keyword=keyword, items=items)

    if not items:
        return analysis

    prices = [item.price_usd for item in items]
    prices.sort()

    analysis.total_sold = len(items)
    analysis.avg_price_usd = sum(prices) / len(prices)
    analysis.min_price_usd = prices[0]
    analysis.max_price_usd = prices[-1]
    analysis.median_price_usd = prices[len(prices) // 2]

    # セラー分析
    sellers = set()
    japan_sellers = set()
    suspected_japan = set()

    for item in items:
        seller_id = item.seller or item.title[:30]
        sellers.add(seller_id)

        location = (item.seller_location or "").lower()
        if "japan" in location:
            japan_sellers.add(seller_id)
        elif detect_suspected_japan_seller(item):
            suspected_japan.add(seller_id)

    analysis.unique_sellers = len(sellers)
    analysis.japan_sellers = len(japan_sellers)
    analysis.suspected_japan_sellers = len(suspected_japan)
    analysis.non_japan_sellers = len(sellers) - len(japan_sellers) - len(suspected_japan)

    # 競合スコア
    total_jp_sellers = len(japan_sellers) + len(suspected_japan)
    if total_jp_sellers <= 2:
        analysis.competition_score = "LOW 🟢"
    elif total_jp_sellers <= 5:
        analysis.competition_score = "MEDIUM 🟡"
    else:
        analysis.competition_score = "HIGH 🔴"

    return analysis


# =====================================================
# Discovery Mode — 自動発掘キーワード
# =====================================================

DISCOVERY_KEYWORDS = [
    # === Tier 1: 高利益率・低競合 ===

    # アニメ制作セル画・原画 (Production Cel / Genga)
    "anime production cel",
    "anime cel japan",
    "anime genga",
    "anime douga",
    "sailor moon cel",
    "dragon ball cel",
    "studio ghibli cel",
    "naruto production art",
    "gundam cel",
    "anime cel art original",

    # ソフビ・怪獣ビニールフィギュア
    "sofubi japan",
    "kaiju sofubi",
    "bullmark sofubi",
    "popy sofubi",
    "marusan sofubi",
    "medicom sofubi",
    "vintage kaiju vinyl japan",
    "designer sofubi",
    "ultraman sofubi vintage",
    "godzilla sofubi japan",

    # 日本限定フィギュア
    "japan exclusive figure",
    "japan limited edition figure",
    "japan only merchandise",
    "japanese prize figure",
    "ichiban kuji japan",
    "japan lottery prize figure",

    # === Tier 2: ニッチ・前回成功パターン ===

    # ゲーム関連グッズ（本体以外）
    "parappa rapper merchandise",
    "parappa rapper figure",
    "um jammer lammy",
    "game soundtrack vinyl japan",
    "japanese game artbook",
    "video game figure japan exclusive",
    "popee performer",

    # Smart Doll / BJD
    "smart doll danny choo",
    "smart doll retired",
    "smart doll body",
    "japanese ball jointed doll",

    # 伝統ゲーム
    "japanese mahjong set",
    "riichi mahjong tiles",
    "nintendo hanafuda",
    "japanese hanafuda cards",

    # アニメ・マンガ関連
    "tokyo mew mew japan",
    "anime shikishi japan",
    "anime tapestry japan",
    "japanese doujinshi",
    "anime reproduction art",

    # === Tier 3: 拡張候補 ===

    # シティポップ・音楽
    "japanese city pop vinyl",
    "japan vinyl record",
    "japanese laserdisc anime",

    # 文房具・雑貨
    "japanese stationery",
    "japanese fountain pen",
    "japanese washi tape",

    # 調理器具
    "japanese knife chef",
    "nambu ironware japan",

    # アイドル
    "japanese idol goods",
    "jpop merchandise",
]


# =====================================================
# Output
# =====================================================

def print_analysis(analysis: KeywordAnalysis):
    """分析結果を表示"""
    print(f"\n{'='*70}")
    print(f"📊 Keyword: {analysis.keyword}")
    print(f"{'='*70}")
    print(f"  売却数:       {analysis.total_sold}件")
    print(f"  平均価格:     ${analysis.avg_price_usd:.2f}")
    print(f"  価格帯:       ${analysis.min_price_usd:.2f} 〜 ${analysis.max_price_usd:.2f}")
    print(f"  中央値:       ${analysis.median_price_usd:.2f}")
    print(f"  ユニークセラー: {analysis.unique_sellers}人")
    print(f"  日本セラー:    {analysis.japan_sellers}人")
    print(f"  偽装疑い:      {analysis.suspected_japan_sellers}人")
    print(f"  競合レベル:    {analysis.competition_score}")
    print()

    # 高価格帯のサンプル表示
    if analysis.items:
        top_items = sorted(analysis.items, key=lambda x: x.price_usd, reverse=True)[:5]
        print("  💰 Top 5 高額売却:")
        for i, item in enumerate(top_items, 1):
            loc = f" [{item.seller_location}]" if item.seller_location else ""
            print(f"    {i}. ${item.price_usd:.2f}{loc} — {item.title[:70]}")


def save_to_csv(analyses: list[KeywordAnalysis], output_path: str):
    """分析結果をCSVに保存"""
    # サマリーCSV
    summary_path = output_path.replace(".csv", "_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "keyword", "total_sold", "avg_price_usd", "median_price_usd",
            "min_price_usd", "max_price_usd", "unique_sellers",
            "japan_sellers", "suspected_japan_sellers", "competition_score"
        ])
        for a in analyses:
            writer.writerow([
                a.keyword, a.total_sold, f"{a.avg_price_usd:.2f}",
                f"{a.median_price_usd:.2f}", f"{a.min_price_usd:.2f}",
                f"{a.max_price_usd:.2f}", a.unique_sellers,
                a.japan_sellers, a.suspected_japan_sellers, a.competition_score
            ])
    print(f"\n📁 Summary saved: {summary_path}")

    # 全アイテムCSV
    items_path = output_path.replace(".csv", "_items.csv")
    with open(items_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "keyword", "title", "price_usd", "shipping_usd", "sold_date",
            "seller", "seller_location", "condition", "item_url"
        ])
        for a in analyses:
            for item in a.items:
                writer.writerow([
                    item.keyword, item.title, f"{item.price_usd:.2f}",
                    f"{item.shipping_usd:.2f}" if item.shipping_usd is not None else "",
                    item.sold_date, item.seller, item.seller_location,
                    item.condition, item.item_url
                ])
    print(f"📁 Items saved: {items_path}")


def save_to_json(analyses: list[KeywordAnalysis], output_path: str):
    """分析結果をJSONに保存"""
    json_path = output_path.replace(".csv", ".json")
    data = []
    for a in analyses:
        entry = {
            "keyword": a.keyword,
            "total_sold": a.total_sold,
            "avg_price_usd": round(a.avg_price_usd, 2),
            "median_price_usd": round(a.median_price_usd, 2),
            "min_price_usd": round(a.min_price_usd, 2),
            "max_price_usd": round(a.max_price_usd, 2),
            "unique_sellers": a.unique_sellers,
            "japan_sellers": a.japan_sellers,
            "suspected_japan_sellers": a.suspected_japan_sellers,
            "competition_score": a.competition_score,
            "items": [asdict(item) for item in a.items],
        }
        data.append(entry)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"📁 JSON saved: {json_path}")


# =====================================================
# Main
# =====================================================

def main():
    parser = argparse.ArgumentParser(
        description="eBay売却済みデータを分析してニッチな日本商品を発掘する"
    )
    parser.add_argument(
        "--keywords", "-k",
        type=str,
        help="カンマ区切りの検索キーワード (例: 'parappa rapper,smart doll')"
    )
    parser.add_argument(
        "--discover", "-d",
        action="store_true",
        help="自動発掘モード: プリセットキーワードで広く検索"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        help="キーワードファイル (1行1キーワード)"
    )
    parser.add_argument(
        "--pages", "-p",
        type=int, default=2,
        help="各キーワードで取得するページ数 (default: 2)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str, default="data/ebay_analysis.csv",
        help="出力ファイルパス (default: data/ebay_analysis.csv)"
    )
    parser.add_argument(
        "--delay-min",
        type=float, default=2.0,
        help="リクエスト間の最小遅延秒数 (default: 2.0)"
    )
    parser.add_argument(
        "--delay-max",
        type=float, default=5.0,
        help="リクエスト間の最大遅延秒数 (default: 5.0)"
    )

    args = parser.parse_args()

    # キーワード収集
    keywords = []
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    elif args.file:
        kw_path = Path(args.file)
        if not kw_path.exists():
            print(f"❌ File not found: {args.file}")
            sys.exit(1)
        keywords = [line.strip() for line in kw_path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    elif args.discover:
        keywords = DISCOVERY_KEYWORDS
    else:
        print("❌ --keywords, --discover, または --file のいずれかを指定してください")
        parser.print_help()
        sys.exit(1)

    print(f"\n🔍 eBay Sold Listings Analyzer")
    print(f"   Keywords: {len(keywords)}件")
    print(f"   Pages per keyword: {args.pages}")
    print(f"   Delay: {args.delay_min}〜{args.delay_max}s")
    print(f"   Output: {args.output}")
    print()

    # 出力ディレクトリ作成
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # スクレイピング＆分析
    all_analyses = []
    delay_range = (args.delay_min, args.delay_max)

    for i, keyword in enumerate(keywords, 1):
        print(f"\n[{i}/{len(keywords)}] 🔎 Searching: {keyword}")
        items = scrape_ebay_sold(keyword, max_pages=args.pages, delay_range=delay_range)
        analysis = analyze_keyword(keyword, items)
        all_analyses.append(analysis)
        print_analysis(analysis)

        # キーワード間の遅延
        if i < len(keywords):
            delay = random.uniform(args.delay_min + 1, args.delay_max + 2)
            print(f"\n⏳ Next keyword in {delay:.1f}s...")
            time.sleep(delay)

    # 結果保存
    save_to_csv(all_analyses, str(output_path))
    save_to_json(all_analyses, str(output_path))

    # 最終サマリー
    print(f"\n{'='*70}")
    print(f"📊 FINAL SUMMARY")
    print(f"{'='*70}")

    # 競合の少ない有望キーワードをソート
    promising = [a for a in all_analyses if a.total_sold > 0]
    promising.sort(key=lambda a: (
        -a.total_sold,  # 売れている数が多い
        a.japan_sellers + a.suspected_japan_sellers,  # 競合が少ない
    ))

    print(f"\n🏆 有望なキーワード (売れているが競合が少ない):\n")
    for a in promising[:15]:
        jp_total = a.japan_sellers + a.suspected_japan_sellers
        print(f"  {a.competition_score:12s} | sold:{a.total_sold:3d} | avg:${a.avg_price_usd:7.2f} | "
              f"sellers:{a.unique_sellers:2d} (JP:{a.japan_sellers}+疑{a.suspected_japan_sellers}) | {a.keyword}")

    print(f"\n✅ Done! Results saved to {args.output}")


if __name__ == "__main__":
    main()
