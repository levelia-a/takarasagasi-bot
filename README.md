# 宝探しBot

Python 3.12以上・discord.py・MySQL 8以上を使うDiscord Botです。
LIA残高との連携は未実装です。参加費と報酬は仮想の値として表示・記録します。

## 構成

```text
main.py             起動・依存関係の組み立て・コマンド同期
config.py           環境変数と接続設定
consts/             難易度・初期設定・Discord ID
commands/           /takara・/takara_admin
views/              ボタン・モーダル・Discordへの表示
services/           抽選・報酬計算・管理設定の検証
repositories/       MySQLへの読み書き（SQL）
database/           接続プール・テーブル初期化
src/sql/            新規DB定義・再実行可能な初期マイグレーション
scripts/            SQLiteからの移行ツール
tests/              ゲームルール・移行・MySQL結合テスト
```

依存方向は `commands/views → services → repositories → database` です。
`bot.py` は以前の起動コマンドとの互換用です。
各ディレクトリは `__init__.py` を置かない暗黙の名前空間パッケージとして扱います。
この仕組みはPython 3.3以降で利用できますが、このBotの動作要件はPython 3.12以上です。
プロジェクトのルートディレクトリで、以下の起動・移行・テストコマンドを実行してください。

## セットアップ

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

宝探しBot専用のMySQLデータベースを用意し、`.env` を設定してください。
他BotのDBには接続しないでください。`settings` など汎用名のテーブルを使用します。

| 変数 | 内容 |
| --- | --- |
| `DISCORD_TOKEN` | Botトークン（必須） |
| `DISCORD_GUILD_ID` | コマンドを登録するサーバー。省略時は `consts/discord.py` の値 |
| `MYSQL_URL` | `mysql://user:password@host:port/database`。指定時は個別設定より優先 |
| `MYSQL_HOST` / `MYSQL_PORT` | MySQL接続先。ポートの既定値は3306 |
| `MYSQL_USER` / `MYSQL_PASSWORD` | MySQL認証情報 |
| `MYSQL_DATABASE` | 専用のデータベース名 |

`MYSQL_URL` を使わない場合、HOST・USER・DATABASEは必須です。
URLのユーザー名やパスワードに記号がある場合はパーセントエンコードしてください。
SSLなどのURLクエリ指定には対応していません。TLS必須の接続先は接続設定の追加が必要です。

```sh
python main.py
```

起動時にMySQLへ接続し、不足テーブルと初期設定を作成します。既存設定は上書きしません。
DBユーザーには専用DBの `CREATE / SELECT / INSERT / UPDATE / DELETE` 権限が必要です。
サーバーへのコマンド同期も起動時に行います。定義変更後は再起動してください。
Botの招待には `bot` と `applications.commands` スコープ、および投稿先でメッセージ送信・埋め込みリンク権限が必要です。

## 操作

- `/takara`：公開パネルから難易度を選択。ゲーム画面は本人にだけ表示します。
- `/takara_admin`：Discordの管理者権限が必要。価格・確率・回数・運営状態・テストモードの変更、統計・履歴・管理ログの確認、テスト履歴の削除ができます。
- 成功するたびに報酬は参加費の2倍、4倍…になります。失敗は0、引き返しと最大回数到達で確定します。
- 初期設定は初級 `1000 / 60% / 5回`、中級 `5000 / 50% / 7回`、上級 `10000 / 40% / 10回` です。
- 価格・成功率・最大回数・テスト判定は開始時に固定します。管理変更は次のゲームから適用されます。運営OFFは新規開始を停止します。
- 探索回数は1〜215、最大報酬は65桁以内です。最大回数1の場合も最初の成功で完走します。
- 同じゲームの結果は重複保存しません。通常統計からテスト結果を除外します。
- 操作期限は5分です。途中のゲームはメモリ上だけに保持し、タイムアウト・再起動時は精算も結果保存も行いません。入口パネルは再起動後も使用できます。
- 時刻はMySQLセッションのJSTで記録します。旧履歴の日時はそのまま移します。

## SQLiteからの移行

旧Botを停止してSQLiteのバックアップを取ってください。元の `takara.db` は移行ツールから変更しません。
移行先は空の専用DBに限定します。テーブルと初期設定だけ作成済みのDBでも実行できます。

```sh
# 確認のみ。MySQLには接続しません。
python -m scripts.migrate_sqlite takara.db --legacy-history-mode test

# .envで指定したMySQLへ書き込む
python -m scripts.migrate_sqlite takara.db --legacy-history-mode test --apply
```

`--legacy-history-mode` はテスト判定を持たない旧履歴の分類です。
通常プレイなら `normal`、テストなら `test` を明示してください。混在する場合は分類を整理してから移行します。
既に `is_test` がある履歴は元の分類を使います。
新形式の `settings` を優先し、旧 `settings_old` / `operation` は不足分の補完にだけ使います。
旧形式の集計専用 `statistics` は移しません。移行した個別履歴から集計し直します。
新旧両方の個別履歴がある場合や、移行先に別の履歴・管理ログがある場合は停止します。
同じ内容の再実行はスキップします。移行中のエラーはデータ変更をロールバックします。

## 検証

```sh
python -m unittest discover -s tests -v
```

MySQL結合テストには、使い捨ての空のDBを指定します。本番DBを指定しないでください。

```sh
TAKARA_TEST_MYSQL_URL='mysql://user:password@127.0.0.1:3306/takara_test' \
  python -m unittest discover -s tests -v
```

## Railway

Pythonサービスと、このBot専用のMySQLサービス／DBを用意します。
Bot側に `DISCORD_TOKEN`、必要に応じて `DISCORD_GUILD_ID`、MySQLの `MYSQL_URL` 参照を設定します。
`railway.json` の起動コマンドは `python main.py` です。HTTPポートは不要です。
ビルドは `requirements.txt`、Pythonの指定は `.python-version` を使用します。
DB移行とコマンド同期は起動時に行うため、別途コマンド登録用のデプロイ処理は不要です。

起動しない場合はRailwayのBuild Logsで依存関係の導入、Deploy Logsで必須変数・MySQL接続・テーブル権限・Discord認証・コマンド同期を確認してください。
`src/sql/20260920_initialize_mysql.sql` は新規MySQLへの初期移行です。`createTable.sql` と同じ定義で、再実行しても既存データを上書きしません。
既存の別形式MySQLテーブルを自動修復するものではありません。

実装参照: [discord.py](https://discordpy.readthedocs.io/en/stable/ext/commands/api.html)、[aiomysql](https://github.com/aio-libs/aiomysql)。
