#!/usr/bin/env python3
"""
eBay Sold Listings Analyzer — SerpAPI版
========================================
SerpAPIを使ってeBayの売却済みデータを取得し、
日本発のニッチ商品の傾向を分析するツール。

事前準備:
  1. https://serpapi.com/ で無料アカウント作成
  2. APIキーを取得
  3. .env ファイルに SERPAPI_KEY=your_key を記入

使い方:
  python ebay_sold_analyzer.py --keywords "japanese anime figure,japanese vintage toy"
  python ebay_sold_analyzer.py --discover   # 自動発掘モード
  python ebay_sold_analyzer.py --file keywords.txt  # ファイルからキーワード読み込み
"""

import argparse
import csv
import json
import os
import re
import time
import random
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    print("httpx が必要です: pip install httpx")
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
# SerpAPI Client
# =====================================================

SERPAPI_BASE_URL = "https://serpapi.com/search"


def load_api_key() -> str:
    """APIキーを .env ファイルまたは環境変数から読み込む"""
    # 環境変数を先にチェック
    key = os.environ.get("SERPAPI_KEY", "")
    if key:
        return key

    # .env ファイルから読み込み
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "SERPAPI_KEY":
                return v.strip()

    return ""


def fetch_ebay_sold_serpapi(keyword: str, api_key: str, page: int = 1) -> dict:
    """SerpAPIでeBay売却済みデータを取得"""
    params = {
        "engine": "ebay",
        "ebay_domain": "ebay.com",
        "_nkw": keyword,
        "LH_Complete": "1",
        "LH_Sold": "1",
        "_sop": "13",       # 新しい順
        "_ipg": "60",       # 1ページ60件
        "api_key": api_key,
    }
    if page > 1:
        params["_pgn"] = str(page)

    url = f"{SERPAPI_BASE_URL}?{urlencode(params)}"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        if response.status_code != 200:
            print(f"  ⚠️  SerpAPI HTTP {response.status_code}")
            return {}
        return response.json()


def parse_serpapi_results(data: dict, keyword: str) -> list[SoldItem]:
    """SerpAPIのJSONレスポンスからSoldItemリストを作成"""
    items = []
    organic = data.get("organic_results", [])

    for result in organic:
        title = result.get("title", "")
        if not title:
            continue

        # 価格の取得
        price_info = result.get("price", {})
        if isinstance(price_info, dict):
            raw = price_info.get("raw", "")
            extracted = price_info.get("extracted", None)
        else:
            raw = str(price_info) if price_info else ""
            extracted = None

        # extracted がない場合はrawからパース
        if extracted is not None:
            price = float(extracted)
        else:
            price = parse_price(raw)

        if price is None or price <= 0:
            continue

        # 送料
        shipping_info = result.get("shipping", "")
        shipping = None
        if isinstance(shipping_info, str):
            if "free" in shipping_info.lower():
                shipping = 0.0
            else:
                shipping = parse_price(shipping_info)

        # セラー情報
        seller_info = result.get("seller_info", {})
        if isinstance(seller_info, dict):
            seller = seller_info.get("name", "")
        else:
            seller = str(seller_info) if seller_info else ""

        # 場所 — SerpAPIでは item_location に入っていることが多い
        location = result.get("item_location", "")
        if not location:
            # extensions にある場合もある
            for ext in result.get("extensions", []):
                if isinstance(ext, str) and ("from" in ext.lower() or "japan" in ext.lower()):
                    location = ext
                    break

        # 売却日
        sold_date = ""
        for ext in result.get("extensions", []):
            if isinstance(ext, str) and "sold" in ext.lower():
                sold_date = ext
                break

        # 商品状態
        condition = result.get("condition", "")

        # URL
        item_url = result.get("link", "")

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


def parse_price(price_text: str) -> Optional[float]:
    """価格テキストからUSD金額を抽出"""
    if not price_text:
        return None
    match = re.search(r'\$?([\d,]+\.?\d*)', price_text.replace(',', ''))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def scrape_ebay_sold(keyword: str, api_key: str, max_pages: int = 2, delay_range: tuple = (1, 3)) -> list[SoldItem]:
    """SerpAPI経由でeBayの売却済みリストを取得"""
    all_items = []

    for page in range(1, max_pages + 1):
        print(f"  📡 Fetching: {keyword} (page {page}/{max_pages})...")

        data = fetch_ebay_sold_serpapi(keyword, api_key, page=page)

        # エラーチェック
        if not data:
            print(f"  ⚠️  No response for '{keyword}' page {page}")
            break

        error = data.get("error")
        if error:
            print(f"  ❌ SerpAPI error: {error}")
            break

        items = parse_serpapi_results(data, keyword)
        if not items:
            print(f"  ℹ️  No more results for '{keyword}' at page {page}")
            break

        all_items.extend(items)
        print(f"  ✅ Found {len(items)} sold items (total: {len(all_items)})")

        # レート制限: ランダム遅延
        if page < max_pages:
            delay = random.uniform(*delay_range)
            print(f"  ⏳ Waiting {delay:.1f}s...")
            time.sleep(delay)

    return all_items


# =====================================================
# Analysis
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


def is_japan_related(text: str) -> bool:
    """テキストに日本関連のキーワードが含まれるか"""
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in JAPAN_INDICATORS)


def detect_suspected_japan_seller(item: SoldItem) -> bool:
    """発送元を偽装している可能性のある日本セラーを検出"""
    location = (item.seller_location or "").lower()
    if "japan" in location:
        return False
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
        description="eBay売却済みデータを分析してニッチな日本商品を発掘する（SerpAPI版）"
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
        "--api-key",
        type=str, default="",
        help="SerpAPI APIキー（省略時は .env または環境変数から読み込み）"
    )
    parser.add_argument(
        "--delay-min",
        type=float, default=1.0,
        help="リクエスト間の最小遅延秒数 (default: 1.0)"
    )
    parser.add_argument(
        "--delay-max",
        type=float, default=3.0,
        help="リクエスト間の最大遅延秒数 (default: 3.0)"
    )

    args = parser.parse_args()

    # APIキー取得
    api_key = args.api_key or load_api_key()
    if not api_key:
        print("❌ SerpAPI のAPIキーが必要です。")
        print()
        print("設定方法（いずれか1つ）:")
        print("  1. .env ファイルに SERPAPI_KEY=your_key を記入")
        print("  2. 環境変数: export SERPAPI_KEY=your_key  (Mac/Linux)")
        print("     または:  set SERPAPI_KEY=your_key       (Windows)")
        print("  3. コマンド引数: --api-key your_key")
        print()
        print("APIキーの取得方法:")
        print("  1. https://serpapi.com/ にアクセス")
        print("  2. 「Register」でアカウント作成（無料）")
        print("  3. ダッシュボードで「API Key」をコピー")
        print("  ※ 無料プランで月100検索まで使えます")
        sys.exit(1)

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

    print(f"\n🔍 eBay Sold Listings Analyzer (SerpAPI)")
    print(f"   Keywords: {len(keywords)}件")
    print(f"   Pages per keyword: {args.pages}")
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
        items = scrape_ebay_sold(keyword, api_key, max_pages=args.pages, delay_range=delay_range)
        analysis = analyze_keyword(keyword, items)
        all_analyses.append(analysis)
        print_analysis(analysis)

        # キーワード間の遅延
        if i < len(keywords):
            delay = random.uniform(args.delay_min + 1, args.delay_max + 1)
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
        -a.total_sold,
        a.japan_sellers + a.suspected_japan_sellers,
    ))

    if promising:
        print(f"\n🏆 有望なキーワード (売れているが競合が少ない):\n")
        for a in promising[:15]:
            print(f"  {a.competition_score:12s} | sold:{a.total_sold:3d} | avg:${a.avg_price_usd:7.2f} | "
                  f"sellers:{a.unique_sellers:2d} (JP:{a.japan_sellers}+疑{a.suspected_japan_sellers}) | {a.keyword}")
    else:
        print("\n  ⚠️  売却データが見つかりませんでした。")
        print("  キーワードを変えて再試行してください。")

    # API使用量の注意
    total_requests = sum(min(args.pages, 2) for _ in keywords)  # 概算
    print(f"\n📊 API使用量（概算）: 約{total_requests}リクエスト")
    print(f"   ※ 無料プランの上限: 100リクエスト/月")

    print(f"\n✅ Done! Results saved to {args.output}")


if __name__ == "__main__":
    main()
