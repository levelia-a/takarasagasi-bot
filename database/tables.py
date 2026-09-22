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

-- 難易度解放システム：ユーザーごとの探索回数を永続化する。
CREATE TABLE IF NOT EXISTS user_progress (
    user_id BIGINT UNSIGNED PRIMARY KEY,
    beginner_explorations INT UNSIGNED NOT NULL DEFAULT 0,
    intermediate_explorations INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 同じ探索の再試行で進捗を二重加算しないための記録。
CREATE TABLE IF NOT EXISTS user_progress_events (
    exploration_id VARCHAR(80) PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_progress_events_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 解放判定そのものではなく、Discordへ同じ解放通知を繰り返さないための状態。
CREATE TABLE IF NOT EXISTS unlock_notifications (
    user_id BIGINT UNSIGNED NOT NULL,
    difficulty VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, difficulty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 同一ユーザーが複数プロセスから同時に宝探しを開始するのを防ぐ。
CREATE TABLE IF NOT EXISTS active_explorations (
    user_id BIGINT UNSIGNED PRIMARY KEY,
    session_id CHAR(36) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    INDEX idx_active_explorations_expires (expires_at)
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
