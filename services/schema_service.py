"""起動時に、難易度解放と冪等性に必要なMySQLスキーマを検証する。"""

import re

from services.db_service import DbService


class SchemaService:
    REQUIRED_TABLES = {
        "game_guild_locks", "game_guilds", "game_guild_members",
        "settings",
        "statistics",
        "user_progress",
        "user_progress_events",
        "unlock_notifications",
        "active_explorations",
        "admin_logs",
        "party_guild_locks",
        "parties",
        "party_members",
        "party_states",
    }
    REQUIRED_COLUMNS = {
        "game_guild_locks": {"server_id": "bigint unsigned"},
        "game_guilds": {
            "id": "char(36)", "server_id": "bigint unsigned", "name": "varchar(32)",
            "passphrase_hash": "char(64)", "leader_id": "bigint unsigned",
        },
        "game_guild_members": {
            "server_id": "bigint unsigned", "user_id": "bigint unsigned",
            "game_guild_id": "char(36)", "server_joined_at": "varchar(40)",
        },
        "party_states": {
            "party_id": "char(36)", "confirmation_id": "varchar(36)",
            "run_id": "varchar(36)", "expires_at": "datetime",
        },
        "party_guild_locks": {"guild_id": "bigint unsigned"},
        "parties": {
            "id": "char(36)", "guild_id": "bigint unsigned",
            "channel_id": "bigint unsigned", "leader_id": "bigint unsigned",
            "created_at": "datetime(6)",
        },
        "party_members": {
            "guild_id": "bigint unsigned", "user_id": "bigint unsigned",
            "party_id": "char(36)", "joined_at": "datetime(6)",
        },
        "settings": {"key": "varchar(64)", "value": "varchar(255)"},
        "statistics": {
            "id": "bigint unsigned",
            "session_id": "char(36)",
            "user_id": "bigint unsigned",
            "user_name": "varchar(255)",
            "difficulty": "varchar(32)",
            "start_price": "decimal(65,0)",
            "success_count": "int unsigned",
            "final_reward": "decimal(65,0)",
            "result": "varchar(32)",
            "failure_point": "int unsigned",
            "is_test": "tinyint",
            "created_at": "datetime",
        },
        "user_progress": {
            "user_id": "bigint unsigned",
            "beginner_explorations": "int unsigned",
            "intermediate_explorations": "int unsigned",
        },
        "user_progress_events": {
            "exploration_id": "varchar(80)",
            "user_id": "bigint unsigned",
            "created_at": "datetime",
        },
        "unlock_notifications": {
            "user_id": "bigint unsigned",
            "difficulty": "varchar(32)",
            "created_at": "datetime",
        },
        "active_explorations": {
            "user_id": "bigint unsigned",
            "session_id": "char(36)",
            "expires_at": "datetime",
        },
        "admin_logs": {
            "id": "bigint unsigned",
            "admin_id": "bigint unsigned",
            "admin_name": "varchar(255)",
            "action": "varchar(255)",
            "detail": "text",
            "created_at": "datetime",
        },
    }
    REQUIRED_PRIMARY_KEYS = {
        "game_guild_locks": {"server_id"},
        "game_guilds": {"id"},
        "game_guild_members": {"server_id", "user_id"},
        "party_states": {"party_id"},
        "party_guild_locks": {"guild_id"},
        "parties": {"id"},
        "party_members": {"guild_id", "user_id"},
        "settings": {"key"},
        "statistics": {"id"},
        "user_progress": {"user_id"},
        "user_progress_events": {"exploration_id"},
        "unlock_notifications": {"user_id", "difficulty"},
        "active_explorations": {"user_id"},
        "admin_logs": {"id"},
    }
    REQUIRED_UNIQUE_KEYS = {
        "game_guilds": ("server_id", "passphrase_hash"),
        "statistics": ("session_id",),
        "active_explorations": ("session_id",),
    }
    REQUIRED_DEFAULTS = {
        ("parties", "created_at"): "current_timestamp(6)",
        ("party_members", "joined_at"): "current_timestamp(6)",
        ("user_progress", "beginner_explorations"): "0",
        ("user_progress", "intermediate_explorations"): "0",
        ("statistics", "is_test"): "0",
        **{
            (table, "created_at"): "current_timestamp"
            for table in (
                "statistics",
                "user_progress_events",
                "unlock_notifications",
                "admin_logs",
            )
        },
    }

    @staticmethod
    def validate_column(table, name, row, expected_type):
        # 整数の表示幅はMySQL 8のバージョンによって有無が異なり、保存範囲には影響しない。
        column_type = re.sub(
            r"\b(tinyint|int|bigint)\(\d+\)", r"\1", row["COLUMN_TYPE"].lower()
        )
        nullable = "YES" if (table, name) == ("statistics", "failure_point") else "NO"
        if column_type != expected_type or row["IS_NULLABLE"] != nullable:
            raise RuntimeError(
                f"DBスキーマが不正です。{table}.{name} の型またはNULL許容が想定と異なります。"
            )
        expected_default = SchemaService.REQUIRED_DEFAULTS.get((table, name))
        if expected_default is not None:
            actual = str(row["COLUMN_DEFAULT"]).lower().removesuffix("()")
            if actual != expected_default:
                raise RuntimeError(
                    f"DBスキーマが不正です。{table}.{name} のDEFAULTが想定と異なります。"
                )
        if table in ("statistics", "admin_logs") and name == "id":
            if "auto_increment" not in row["EXTRA"].lower():
                raise RuntimeError(
                    f"DBスキーマが不正です。{table}.id にAUTO_INCREMENTがありません。"
                )

    @staticmethod
    async def validate_required_tables():
        """不足テーブル・重要列・主キー・InnoDB不一致なら起動前に停止する。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("""SELECT TABLE_NAME, ENGINE
                   FROM INFORMATION_SCHEMA.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()""")
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
                    """SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA
                       FROM INFORMATION_SCHEMA.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
                    (table,),
                )
                columns = {row["COLUMN_NAME"]: row for row in await cursor.fetchall()}
                missing_columns = sorted(required_columns.keys() - columns.keys())
                if missing_columns:
                    raise RuntimeError(
                        f"DBスキーマが不正です。{table} の不足列: "
                        + ", ".join(missing_columns)
                    )

                for name, expected_type in required_columns.items():
                    SchemaService.validate_column(
                        table, name, columns[name], expected_type
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

            for table, expected in SchemaService.REQUIRED_UNIQUE_KEYS.items():
                await cursor.execute(
                    """SELECT INDEX_NAME, COLUMN_NAME, SUB_PART
                       FROM INFORMATION_SCHEMA.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND NON_UNIQUE = 0
                       ORDER BY INDEX_NAME, SEQ_IN_INDEX""",
                    (table,),
                )
                indexes = {}
                for row in await cursor.fetchall():
                    indexes.setdefault(row["INDEX_NAME"], []).append(
                        (row["COLUMN_NAME"], row["SUB_PART"])
                    )
                if [(name, None) for name in expected] not in indexes.values():
                    raise RuntimeError(
                        f"DBスキーマが不正です。{table} に {', '.join(expected)} の完全なUNIQUE制約がありません。"
                    )
