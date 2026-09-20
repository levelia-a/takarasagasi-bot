"""新規MySQLデータベースの初期化。既存データは上書きしない。"""

from pathlib import Path

from consts.treasure import DEFAULT_SETTINGS


async def initialize_database(database):
    sql = (Path(__file__).resolve().parents[1] / "src/sql/createTable.sql").read_text()
    async with database.transaction() as cursor:
        for statement in sql.split(";"):
            if statement.strip():
                await cursor.execute(statement)
        for key, value in DEFAULT_SETTINGS.items():
            await cursor.execute(
                "INSERT INTO settings (`key`, value) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE `key` = `key`",
                (key, str(value)),
            )
