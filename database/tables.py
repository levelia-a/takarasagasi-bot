"""RailwayのMySQLターミナルで手動実行するテーブル定義。

TABLES_SQL 内のSQLを、宝探しBot専用のデータベースで実行してください。
このファイルは定義のみです。Bot起動時にSQLを実行する処理はありません。
settings の未登録項目には consts/treasure.py の初期値を使用します。
"""

TABLES_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    `key` VARCHAR(64) PRIMARY KEY,
    value VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS statistics (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    session_id CHAR(36) NOT NULL UNIQUE,
    user_id BIGINT UNSIGNED NOT NULL,
    user_name VARCHAR(255) NOT NULL,
    difficulty VARCHAR(32) NOT NULL,
    start_price DECIMAL(65, 0) NOT NULL,
    success_count INT UNSIGNED NOT NULL,
    final_reward DECIMAL(65, 0) NOT NULL,
    result VARCHAR(32) NOT NULL,
    failure_point INT UNSIGNED NULL,
    is_test BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_statistics_test_difficulty (is_test, difficulty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS admin_logs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    admin_id BIGINT UNSIGNED NOT NULL,
    admin_name VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    detail TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
