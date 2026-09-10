# リポジトリ構造

```
froger1985/
├── docs/                          # プロジェクト全体の永続ドキュメント
│   ├── product-requirements.md    # プロダクト要求定義書
│   ├── architecture.md            # アーキテクチャ概要
│   ├── functional-design.md       # 機能設計書
│   ├── repository-structure.md    # このファイル
│   ├── development-guidelines.md  # 開発ガイドライン
│   └── glossary.md                # 用語集
│
├── .steering/                     # Claude へのタスク指示（ステアリング）
│   └── 20260506-fetch-mercari-likes/
│       ├── requirements.md        # このタスクの要件
│       ├── design.md              # このタスクの設計
│       └── tasklist.md            # このタスクの進捗
│
└── sourcing-tool/                 # メインアプリケーション
    ├── src/
    │   ├── __init__.py
    │   ├── main.py                # CLI エントリーポイント（click）
    │   ├── config.py              # config.yaml を読み込む
    │   │
    │   ├── scrapers/
    │   │   ├── __init__.py
    │   │   ├── base.py            # BaseScraper 抽象クラス
    │   │   ├── mercari.py         # メルカリ キーワード検索（匿名）
    │   │   ├── mercari_likes.py   # メルカリ いいね取得（Playwright）★新規
    │   │   ├── hardoff.py         # ハードオフ キーワード検索
    │   │   ├── yahoo_auction.py   # ヤフオク キーワード検索
    │   │   └── ebay.py            # eBay 落札価格検索
    │   │
    │   ├── analysis/
    │   │   ├── __init__.py
    │   │   └── profit_calculator.py  # eBay出品価格・利益計算
    │   │
    │   ├── db/
    │   │   ├── __init__.py
    │   │   ├── database.py        # SQLite 操作（sqlite3直接使用）
    │   │   └── models.py          # データモデル（dataclass）
    │   │
    │   ├── alerts/
    │   │   ├── __init__.py
    │   │   └── notifier.py        # Slack/LINE 通知
    │   │
    │   └── utils/
    │       ├── __init__.py
    │       └── currency.py        # USD/JPY レート取得・変換
    │
    ├── data/                      # 実行時生成ファイル（.gitignore 対象）
    │   ├── sourcing.db            # SQLite データベース
    │   ├── mercari_session.json   # Playwright セッション ★新規（git除外）
    │   └── discovery_*.json       # 過去の実行結果
    │
    ├── config.yaml                # スクレイピング・手数料・送料の設定
    ├── requirements.txt           # Python 依存パッケージ
    ├── .env.example               # 環境変数サンプル
    ├── .gitignore
    └── SETUP_GUIDE.md
```

## 重要なファイルの役割

| ファイル | 役割 |
|---|---|
| `src/main.py` | すべての CLI コマンドのエントリーポイント |
| `src/scrapers/mercari_likes.py` | Playwright でメルカリいいね一覧を取得する（今回新規追加） |
| `src/db/database.py` | DB への CRUD 操作をすべて集約 |
| `src/db/models.py` | アプリ全体で使う dataclass データモデル |
| `config.yaml` | 手数料率・送料・スクレイピング設定（コードに定数を書かない） |
| `data/mercari_session.json` | Playwright のブラウザセッション（パスワード同等、git 管理外） |

## .gitignore の方針

以下は git 管理対象外とする：
- `data/sourcing.db`（実行データ）
- `data/mercari_session.json`（認証セッション）
- `data/discovery_*.json`（実行ログ）
- `.env`（シークレット）
- `__pycache__/`、`.pytest_cache/` 等
