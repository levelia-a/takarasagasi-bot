"""起動時に、難易度解放と冪等性に必要なMySQLスキーマを検証する。"""

from services.db_service import DbService


class SchemaService:
    REQUIRED_TABLES = {
        "settings",
        "statistics",
        "user_progress",
        "user_progress_events",
        "unlock_notifications",
        "active_explorations",
        "admin_logs",
    }
    REQUIRED_COLUMNS = {
        "user_progress": {"user_id", "beginner_explorations", "intermediate_explorations"},
        "user_progress_events": {"exploration_id", "user_id", "created_at"},
        "unlock_notifications": {"user_id", "difficulty", "created_at"},
        "active_explorations": {"user_id", "session_id", "expires_at"},
    }
    REQUIRED_PRIMARY_KEYS = {
        "user_progress": {"user_id"},
        "user_progress_events": {"exploration_id"},
        "unlock_notifications": {"user_id", "difficulty"},
        "active_explorations": {"user_id"},
    }

    @staticmethod
    async def validate_required_tables():
        """不足テーブル・重要列・主キー・InnoDB不一致なら起動前に停止する。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                """SELECT TABLE_NAME, ENGINE
                   FROM INFORMATION_SCHEMA.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()"""
            )
            table_rows = await cursor.fetchall()
            engines = {row["TABLE_NAME"]: row["ENGINE"] for row in table_rows}

            missing = sorted(SchemaService.REQUIRED_TABLES - engines.keys())
            if missing:
                raise RuntimeError(
                    "DBスキーマが未更新です。database/tables.py の TABLES_SQL を先に実行してください。"
                    f" 不足テーブル: {', '.join(missing)}"
                )

            wrong_engines = sorted(
                name
                for name in SchemaService.REQUIRED_TABLES
                if (engines.get(name) or "").upper() != "INNODB"
            )
            if wrong_engines:
                raise RuntimeError(
                    "DBスキーマが不正です。InnoDBではないテーブル: "
                    + ", ".join(wrong_engines)
                )

            for table, required_columns in SchemaService.REQUIRED_COLUMNS.items():
                await cursor.execute(
                    """SELECT COLUMN_NAME, IS_NULLABLE
                       FROM INFORMATION_SCHEMA.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
                    (table,),
                )
                columns = {row["COLUMN_NAME"]: row for row in await cursor.fetchall()}
                missing_columns = sorted(required_columns - columns.keys())
                if missing_columns:
                    raise RuntimeError(
                        f"DBスキーマが不正です。{table} の不足列: "
                        + ", ".join(missing_columns)
                    )

                await cursor.execute(
                    """SELECT COLUMN_NAME
                       FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                       WHERE TABLE_SCHEMA = DATABASE()
                         AND TABLE_NAME = %s
                         AND CONSTRAINT_NAME = 'PRIMARY'
                       ORDER BY ORDINAL_POSITION""",
                    (table,),
                )
                primary = {row["COLUMN_NAME"] for row in await cursor.fetchall()}
                expected = SchemaService.REQUIRED_PRIMARY_KEYS[table]
                if primary != expected:
                    raise RuntimeError(
                        f"DBスキーマが不正です。{table} のPRIMARY KEYが想定と異なります。"
                    )
