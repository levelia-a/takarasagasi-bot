"""python -m scripts.migrate_sqlite takara.db [--apply]"""

import argparse
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from config import DatabaseConfig
from consts.treasure import DEFAULT_SETTINGS
from database.connection import Database
from database.schema import initialize_database
from repositories.migration_repository import MigrationRepository
from services.settings_service import validate_settings


def read_source(path, legacy_history_mode=None):
    path = Path(path).resolve(strict=True)
    # 読み取り専用。旧Botを停止し、バックアップしたファイルを指定する。
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        def columns(table):
            return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}

        def rows(table):
            return [
                dict(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")
            ]

        settings = DEFAULT_SETTINGS.copy()
        legacy_table = "settings_old" if "settings_old" in tables else "settings"
        if legacy_table in tables and {
            "difficulty",
            "price",
            "success_rate",
            "max_exploration",
        } <= columns(legacy_table):
            for row in connection.execute(f"SELECT * FROM {legacy_table}"):
                key = row["difficulty"]
                for suffix, column in [
                    ("price", "price"),
                    ("rate", "success_rate"),
                    ("max", "max_exploration"),
                ]:
                    if f"{key}_{suffix}" in settings:
                        settings[f"{key}_{suffix}"] = row[column]
        if "operation" in tables:
            operation = connection.execute(
                "SELECT enabled, test_mode FROM operation WHERE id = 1"
            ).fetchone()
            if operation:
                settings.update(
                    operation=operation["enabled"], test_mode=operation["test_mode"]
                )
        # 新形式を優先し、古い価格で上書きしない。
        if "settings" in tables and {"key", "value"} <= columns("settings"):
            for row in connection.execute("SELECT key, value FROM settings"):
                if row["key"] in settings:
                    settings[row["key"]] = (
                        row["value"] if row["key"] == "test_mode" else int(row["value"])
                    )
        validate_settings(settings)
        history = rows("history") if "history" in tables else []
        modern = (
            rows("statistics")
            if "statistics" in tables and "user_id" in columns("statistics")
            else []
        )
        if history and modern:
            raise ValueError(
                "history と statistics の両方に個別履歴があります。重複を確認してから移行してください。"
            )
        records = modern or history
        for record in records:
            if "is_test" not in record:
                if legacy_history_mode is None:
                    raise ValueError(
                        "旧履歴にテスト判定がありません。--legacy-history-mode normal または test を明示してください。"
                    )
                record["is_test"] = int(legacy_history_mode == "test")
            record["source_table"] = "statistics" if modern else "history"
        logs = rows("admin_logs") if "admin_logs" in tables else []
        payload = {"settings": settings, "records": records, "logs": logs}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return payload, digest
    finally:
        connection.close()


async def migrate(args):
    payload, digest = read_source(args.source, args.legacy_history_mode)
    counts = {
        "settings": len(payload["settings"]),
        "history": len(payload["records"]),
        "admin_logs": len(payload["logs"]),
    }
    print(json.dumps(counts, ensure_ascii=False))
    if not args.apply:
        print(
            "確認のみ。MySQLへの接続・書き込みは行っていません。実行時は --apply を追加してください。"
        )
        return
    database = Database(DatabaseConfig.from_env())
    try:
        await database.connect()
        await initialize_database(database)
        imported = await MigrationRepository(database).import_source(payload, digest)
        print(
            "移行完了。" if imported else "同じデータは移行済みです。変更していません。"
        )
    finally:
        await database.close()


def main():
    parser = argparse.ArgumentParser(
        description="SQLiteの設定・履歴を空のMySQL DBへ移す。既定は確認のみ。"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--legacy-history-mode", choices=["normal", "test"])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(migrate(args))
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
