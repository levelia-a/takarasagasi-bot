# 宝探しBot

Python 3.12以上・discord.py・MySQL 8以上を使うDiscord Botです。
LIA残高との連携は未実装です。参加費と報酬は仮想の値として表示・記録します。

## 構成

```text
main.py             起動・DB接続の初期化・コマンド同期
config.py           環境変数と接続設定
consts/             難易度・初期設定・Discord ID
commands/           /takara・/takara_admin
views/              ボタン・モーダル・Discordへの表示
services/           業務処理・トランザクション管理
services/db_service.py  MySQL接続プール・接続の取得と解放
repositories/       渡されたカーソルでSQLを実行
database/tables.py   手動実行用のテーブル定義SQL
tests/              ゲームルール・MySQL結合テスト
```

依存方向は `commands/views → services → repositories` です。
サービスとレポジトリのメソッドは `@staticmethod` で定義し、
`await SettingsService.get_all()` や `await SettingsRepository.get_all_settings(cursor)` のように
クラス名から直接呼び出します。インスタンスの生成や受け渡しは不要です。
`DbService` はプロセス内で1つの接続プールを共有し、接続の取得・解放を管理します。
起動時に `await DbService.connect(config.database)`、終了時に `await DbService.close()` を呼びます。
1プロセス・1イベントループで1つのBotを動かす構成です。
設定変更用のロックは `SettingsService` で共有します。
各ゲームの進行状態とロックは `Exploration` インスタンスに保持し、Viewも画面ごとに生成します。
各サービスが接続を取得し、設定更新＋管理ログ保存などの処理単位で
`begin / commit / rollback` を実行します。レポジトリは同じ接続のカーソルを受け取り、SQLを実行して結果を返します。
初期設定の補完・型変換・結果の組み立てはサービスの役割です。
単独の読み取りや単一INSERTはautocommitを使い、明示的なトランザクションを開始しません。

レポジトリの関数名は `操作_対象_条件` のsnake_caseで統一します。
`get`・`insert`・`update`・`upsert`・`delete` を区別し、対象テーブルやデータを名前に含めます。
条件で絞る場合は `by_user_id` など、集計単位は `grouped_by_difficulty` などで表します。
固定の取得件数やロックの有無も、`latest_10`・`for_update` として明記します。
例：`get_all_settings`、`upsert_setting_by_key`、`insert_admin_log`。
結果保存は既存行を上書きしないため、`insert_statistics_record_if_session_id_not_exists` としています。

各ディレクトリは `__init__.py` を置かない暗黙の名前空間パッケージとして扱います。
この仕組みはPython 3.3以降で利用できますが、このBotの動作要件はPython 3.12以上です。
プロジェクトのルートディレクトリで、以下の起動・テストコマンドを実行してください。

## セットアップ

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

宝探しBot専用のMySQLデータベースを用意し、RailwayのMySQLターミナルで
`database/tables.py` の `TABLES_SQL` 内のSQLを手動実行してください。
作成するテーブルは `settings`・`statistics`・`user_progress`・`user_progress_events`・`unlock_notifications`・`active_explorations`・`admin_logs` の7つです。`user_progress` はユーザーごとの初級・中級の探索回数を保存します。`user_progress_events` はDB確定結果が不明な再試行でも二重加算しないため、探索単位のIDを冪等性キーとして保持します。正常完了直後には削除しません。`unlock_notifications` は解放判定には使わず、Discordへの解放通知が実際に表示された後で通知済みとして記録します。`active_explorations` はユーザーIDを主キーにした5分期限の開始枠で、複数Botプロセスが一時的に重なっても同じユーザーの同時進行を防ぎます。難易度の解放状態そのものは保存せず、現在の探索回数と現在の解放条件を比較して判定します。
その後、`.env` に接続情報を設定してください。
他BotのDBには接続しないでください。`settings` など汎用名のテーブルを使用します。

| 変数 | 内容 |
| --- | --- |
| `DISCORD_TOKEN` | Botトークン（必須） |
| `GUILD_ID` | コマンドを登録するサーバー。省略時は `consts/discord.py` の値 |
| `MYSQL_URL` | `mysql://user:password@host:port/database`。指定時は個別設定より優先 |
| `MYSQLHOST` / `MYSQLPORT` | MySQL接続先。ポートの既定値は3306 |
| `MYSQLUSER` / `MYSQLPASSWORD` | MySQL認証情報 |
| `MYSQL_DATABASE` | 専用のデータベース名 |

`MYSQL_URL` を使わない場合、`MYSQLHOST`・`MYSQLUSER`・`MYSQL_DATABASE` は必須です。
従来の `DISCORD_GUILD_ID`・`MYSQL_HOST`・`MYSQL_PORT`・`MYSQL_USER`・`MYSQL_PASSWORD` も使用できますが、個別設定では上表の名前を優先します。
URLのユーザー名やパスワードに記号がある場合はパーセントエンコードしてください。
SSLなどのURLクエリ指定には対応していません。TLS必須の接続先は接続設定の追加が必要です。

```sh
python -X pycache_prefix=.cache/pycache main.py
```

`-X pycache_prefix=.cache/pycache` により、キャッシュをプロジェクト直下の
`.cache/pycache/` にまとめます。内部には元のパスに対応した階層が作られますが、
各ソースフォルダーには `__pycache__` を作りません。`.cache/` はGit管理対象外です。
このオプションを付けずにPythonを実行すると、通常の `__pycache__` が再び作られます。
同じターミナルで常に集約したい場合は、プロジェクトのルートで
`export PYTHONPYCACHEPREFIX="$PWD/.cache/pycache"` を実行すれば、`python main.py` でも同じ保存先になります。
設定はPython起動前に必要なため、Botが読み込む `.env` には記載しません。
参照: [Pythonのキャッシュ保存先設定](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONPYCACHEPREFIX)。

起動時はMySQLへ接続した直後に必須7テーブルの存在に加え、難易度解放で重要な列・PRIMARY KEY・InnoDBを検査し、不一致があれば起動を中止します。テーブル作成・変更・データ移行は行いません。
`settings` は空の状態でも使用できます。未登録項目は `consts/treasure.py` の初期値を使い、管理画面で変更した項目をDBに保存します。
Bot用DBユーザーには専用DBの `SELECT / INSERT / UPDATE / DELETE` 権限が必要です。
テーブルを手動作成するユーザーには別途 `CREATE` 権限が必要です。
サーバーへのコマンド同期も起動時に行います。定義変更後は再起動してください。
Botの招待には `bot` と `applications.commands` スコープ、および投稿先でメッセージ送信・埋め込みリンク権限が必要です。

## 操作

- `/takara`：公開パネルから難易度を選択。ゲーム画面は本人にだけ表示します。
- `/takara_admin`：Discordの管理者権限が必要。価格・確率・回数・難易度解放条件・運営状態・テストモードの変更、統計・履歴・管理ログの確認、テスト履歴の削除ができます。
- 成功するたびに報酬は参加費の2倍、4倍…になります。失敗は0、引き返しと最大回数到達で確定します。
- 初期設定は初級 `1000 / 60% / 5回`、中級 `5000 / 50% / 7回`、上級 `10000 / 40% / 10回` です。初級を10回探索すると中級、中級を20回探索すると上級に挑戦できます。成功・失敗に関係なく通常プレイの探索判定ごとに1回加算し、テストモードは進捗に含めません。同じ探索の保存を再試行しても進捗は二重加算しません。難易度解放進捗はこの機能の導入後から全員0回で記録を開始し、過去履歴からの移行は行いません。同一ユーザーは同時に複数の宝探しを開始できません。解放判定と解放通知は保存済みの探索回数と現在の管理者設定を比較するため、必要回数を引き上げて探索回数が条件未満になった場合は再び挑戦できなくなります。
- 価格・成功率・最大回数・テスト判定は開始時に固定します。管理変更は次のゲームから適用されます。運営OFFは新規開始を停止します。
- 探索回数は1〜215、最大報酬は65桁以内です。最大回数1の場合も最初の成功で完走します。
- 同じゲームの結果は重複保存しません。通常統計からテスト結果を除外します。
- 操作期限は5分です。途中のゲームはメモリ上だけに保持し、タイムアウト・再起動時は精算も結果保存も行いません。入口パネルは再起動後も使用できます。
- 時刻はMySQLセッションのJSTで記録します。

## 検証

```sh
python -X pycache_prefix=.cache/pycache -m unittest discover -s tests -v
```

MySQL結合テストには、使い捨ての空のDBを指定します。本番DBを指定しないでください。
テスト内でのみ `database/tables.py` のSQLを実行し、終了後に作成したテーブルを削除します。
テスト用DBユーザーには `CREATE / DROP / SELECT / INSERT / UPDATE / DELETE` 権限が必要です。

```sh
TAKARA_TEST_MYSQL_URL='mysql://user:password@127.0.0.1:3306/takara_test' \
  python -X pycache_prefix=.cache/pycache -m unittest discover -s tests -v
```

## Railway

Pythonサービスと、このBot専用のMySQLサービス／DBを用意します。
Bot側に `DISCORD_TOKEN`、`GUILD_ID`、`MYSQLHOST`・`MYSQLPORT`・`MYSQLUSER`・`MYSQLPASSWORD`・`MYSQL_DATABASE` の参照を設定します。
`GUILD_ID` は省略可能です。MySQL接続には個別設定の代わりに `MYSQL_URL` も使用できます（指定時は優先）。
`railway.json` の起動コマンドは `python -X pycache_prefix=.cache/pycache main.py` です。HTTPポートは不要です。
ビルドは `requirements.txt`、Pythonの指定は `.python-version` を使用します。
デプロイ前に必ず `database/tables.py` のSQLを先に実行し、7テーブルが正しい定義で存在することを確認してからBotコードを更新してください。スキーマ未更新なら起動時検査でBotが停止し、不足テーブル名をログの例外で確認できます。
コマンド同期は起動時に行うため、別途コマンド登録用のデプロイ処理は不要です。

起動しない場合はRailwayのBuild Logsで依存関係の導入、Deploy Logsで必須変数・MySQL接続・テーブル権限・Discord認証・コマンド同期を確認してください。

実装参照: [discord.py](https://discordpy.readthedocs.io/en/stable/ext/commands/api.html)、[aiomysql](https://github.com/aio-libs/aiomysql)。


## CI

Pull RequestではGitHub ActionsがPython 3.12とMySQL 8を起動し、通常の単体テストとMySQL結合テストをまとめて実行します。ローカルでMySQL URLを用意できない場合でも、PR上ではDB関連テストをskipせず確認します。
