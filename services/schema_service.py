"""起動時に必要なMySQLテーブルが揃っているか検証する。"""

from services.db_service import DbService


class SchemaService:
    REQUIRED_TABLES = {
        "settings",
        "statistics",
        "user_progress",
        "user_progress_events",
        "unlock_notifications",
        "admin_logs",
    }

    @staticmethod
    async def validate_required_tables():
        """不足テーブルがあればゲーム開始前に明示的なエラーで停止する。"""
        async with (
            DbService.get_connection() as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SHOW TABLES")
            rows = await cursor.fetchall()

        existing = {next(iter(row.values())) for row in rows}
        missing = sorted(SchemaService.REQUIRED_TABLES - existing)
        if missing:
            names = ", ".join(missing)
            raise RuntimeError(
                "DBスキーマが未更新です。database/tables.py の TABLES_SQL を先に実行してください。"
                f" 不足テーブル: {names}"
            )
