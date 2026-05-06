# 開発ガイドライン

## セットアップ

```bash
cd sourcing-tool
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# .env を編集して eBay API キー等を設定
```

## コーディング規約

### Python バージョン・スタイル

- Python 3.11 以上を対象とする
- 型アノテーションを必ず付ける（`from __future__ import annotations` を各ファイル先頭に）
- フォーマッタ: black（設定なし、デフォルト）
- 行長: 100文字

### 非同期処理

- I/O を伴う処理は `async/await` で書く
- `asyncio.gather()` で並列実行できる処理は並列化する
- CLI コマンドのエントリーポイントは `asyncio.run()` で呼び出す

### 設定値

コードに定数を直接書かない。すべて `config.yaml` に定義し、`CONFIG` dict 経由で参照する。

```python
# Good
shipping = CONFIG["shipping"]["game_ems_jpy"]

# Bad
shipping = 2500
```

### エラーハンドリング

- スクレイパーの個別エラーはログに記録してスキップし、パイプライン全体を止めない
- DB 操作のエラーは呼び出し元まで伝播させる
- ユーザー向けのエラーメッセージは `click.echo()` で出力する

### ログ

```python
logger = logging.getLogger(__name__)
logger.info("...")   # 通常の進捗
logger.warning("...") # 問題だが続行可能
logger.error("...")  # エラー
```

`logging.basicConfig` は `main.py` でのみ設定する。

## ディレクトリ・ファイル構成ルール

- 新しいスクレイパーは `src/scrapers/` に追加する
- DB スキーマ変更は `database.py` の `_SCHEMA` 定数を編集する
- 新しい CLI コマンドは `main.py` の `cli` グループに追加する

## git 運用

### ブランチ命名

```
claude/<タスク名>-<ID>   # Claude が作業するブランチ
feature/<機能名>          # 人間が作業するブランチ
```

### コミットメッセージ形式

```
<type>: <日本語で簡潔に説明>

<詳細（任意）>
```

type の例：`feat`（新機能）、`fix`（バグ修正）、`docs`（ドキュメント）、`refactor`（リファクタ）

### 秘密情報の管理

以下は絶対に git にコミットしない：
- `.env`（API キー、トークン）
- `data/mercari_session.json`（ブラウザセッション）
- `data/sourcing.db`（個人データ）

## テスト方針

現時点では自動テストなし。手動動作確認を以下の手順で行う：

```bash
# いいね取得の動作確認
python -m src.main likes --no-save

# DB 保存確認
python -m src.main likes --save
python -m src.main status

# scan パイプライン（既存機能の回帰確認）
python -m src.main scan --dry-run
```

## 依存パッケージの追加

`requirements.txt` に追加し、バージョンは `>=X.Y.Z` 形式で指定する。
新しい playwright ブラウザが必要な場合は `playwright install <browser>` を `SETUP_GUIDE.md` に記載する。
