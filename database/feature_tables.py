"""難易度解放機能で追加された安全なCREATE IF NOT EXISTSだけを起動時に適用する。"""

from services.db_service import DbService

FEATURE_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS user_progress (
        user_id BIGINT UNSIGNED PRIMARY KEY,
        beginner_explorations INT UNSIGNED NOT NULL DEFAULT 0,
        intermediate_explorations INT UNSIGNED NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS user_progress_events (
        exploration_id VARCHAR(80) PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user_progress_events_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS unlock_notifications (
        user_id BIGINT UNSIGNED NOT NULL,
        difficulty VARCHAR(32) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, difficulty)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
)


async def ensure_difficulty_unlock_tables():
    """既存データを変更せず、難易度解放用テーブルが無い場合だけ作成する。"""
    async with DbService.get_connection() as connection, connection.cursor() as cursor:
        for statement in FEATURE_TABLES_SQL:
            await cursor.execute(statement)
