# 機能設計書

## likes パイプライン（Step 1 実装対象）

### コマンドインタフェース

```
python -m src.main likes [OPTIONS]

Options:
  --save / --no-save  DB に保存するか（デフォルト: --save）
  --limit INTEGER     最大取得件数（デフォルト: 0 = 全件）
  --help              ヘルプを表示
```

**実行例：**
```bash
# 全件取得して DB 保存
python -m src.main likes

# DB 保存なしで一覧確認のみ
python -m src.main likes --no-save

# 最初の20件のみ
python -m src.main likes --limit 20
```

---

### MercariLikesScraper の仕様

#### セッション管理

| 条件 | 動作 |
|---|---|
| `data/mercari_session.json` が存在しない | ブラウザを headed（画面あり）で起動し、ユーザーが手動ログイン後にエンターキーを押すまで待機 |
| セッションファイルが存在する | ブラウザにセッションを読み込み、ログインなしで直接いいねページへ遷移 |
| セッションが期限切れ（ログインページへリダイレクトされた場合） | ユーザーに再ログインを促し、完了後にエンターキーを押すまで待機 |

セッション取得後は常に `data/mercari_session.json` に上書き保存する。

#### ネットワーク傍受

Playwright の `page.on("response", handler)` を使い、以下のパターンにマッチするレスポンスを収集する：

```
api.mercari.jp でいいねデータを含む URL
（例: api.mercari.jp/v2/me/likes, api.mercari.jp/v2/me/favorites 等）
```

実際の URL パターンは初回実行時の devtools で確認し、マッチャーを調整する。

#### ページネーション（スクロール方式）

メルカリのいいねページは仮想スクロールで動作する。スクロールするたびに次のページの API リクエストが自動発火する。

```
while True:
    1. ページ最下部までスクロール
    2. 新しい API レスポンスを待機（タイムアウト: 3秒）
    3. レスポンスが取得できた → 商品を蓄積、続行
    4. タイムアウトした（= 最終ページ）→ ループ終了
    5. limit 指定あり かつ 取得数 >= limit → ループ終了
```

#### `_parse_item()` の仕様

API レスポンスの JSON から `SourceListing` を生成する。

| SourceListing フィールド | API レスポンスのキー（推定） | 備考 |
|---|---|---|
| `source` | - | 固定値: `"mercari_likes"` |
| `source_id` | `item.id` | メルカリの商品ID |
| `category` | - | 固定値: `"unknown"`（いいね商品はカテゴリ不明） |
| `title` | `item.name` | 商品名 |
| `price_jpy` | `item.price` | 価格（int, 円） |
| `url` | - | `https://jp.mercari.com/item/{item.id}` で構築 |
| `image_url` | `item.thumbnails[0]` または `item.thumbnail` | サムネイル |
| `condition` | `item.item_condition.name` | 商品の状態 |

API レスポンスの実際の構造は `mercari.py` の実装を参考にする。フィールドが存在しない場合はデフォルト値（空文字等）を使用し、例外を出さない。

---

### DB 保存仕様

`database.py` の既存メソッド `upsert_listing()` を使用する。

- `UNIQUE(source, source_id)` 制約により重複は自動でスキップされる
- 既存レコードは UPDATE される（タイトル・価格変更に追従）
- `status` は `"new"` で保存（scan パイプラインで後続処理可能）

---

### コンソール出力仕様

```
メルカリいいね商品一覧 (N件)

 No.  タイトル（最大50文字）                    価格(円)  コンディション
----  -----------------------------------------  --------  --------------
   1  Nintendo Switch ニンテンドースイッチ 本体     28,000  目立った傷や汚れなし
   2  SONY ウォークマン NW-A100TPS                 15,800  やや傷や汚れあり
  ...

合計: N件 | 新規保存: M件 | スキップ(重複): K件
```

---

## scan パイプライン（既存・変更なし）

### コマンドインタフェース

```
python -m src.main scan [OPTIONS]

Options:
  -s, --source TEXT    スクレイプ対象（hardoff/yahoo/mercari）複数指定可
  -c, --category TEXT  カテゴリフィルター（game/audio）
  --dry-run            分析のみ、アラート送信なし
```

### パイプライン処理

1. **スクレイプ**: ウォッチリストの各キーワードを全ソースで並列検索
2. **保存**: `source_listings` にupsert
3. **eBay価格調査**: 新規商品に対して eBay 落札価格を取得
4. **利益計算**: `calculate_profit()` で利益・推奨判定
5. **アラート**: `recommendation == "buy"` なら Slack/LINE に通知

### 価格計算式

```
eBay出品価格(JPY) = eBay落札平均(USD) × USD/JPY レート
利益 = eBay出品価格(JPY) - 仕入れ価格 - 国際送料 - eBay手数料 - 決済手数料
```

---

## watchlist コマンド（既存・変更なし）

scan パイプラインで使用するキーワードを管理する。

```bash
python -m src.main watchlist add game "ゲームボーイ"
python -m src.main watchlist add audio "アンプ" --max-price 5000
python -m src.main watchlist list
python -m src.main watchlist import config.yaml
```

---

## status コマンド（既存・変更なし）

DB のサマリーを表示する。

```bash
python -m src.main status
```

出力：
- 合計リスト数、未分析数、アラート済み数
- トップ10の買い推奨商品（利益順）
