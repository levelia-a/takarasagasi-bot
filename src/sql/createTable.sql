-- 新規DB用。正本 database/tables.py の TABLES_SQL と同じ定義。

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
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_statistics_test_difficulty (is_test, difficulty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 難易度解放システム：ユーザーごとの探索回数を永続化する。
CREATE TABLE IF NOT EXISTS user_progress (
    user_id BIGINT UNSIGNED PRIMARY KEY,
    beginner_explorations INT UNSIGNED NOT NULL DEFAULT 0,
    intermediate_explorations INT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
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
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- パーティー機能。既存データを変更しない再実行可能な追加マイグレーション。
CREATE TABLE IF NOT EXISTS party_guild_locks (
    guild_id BIGINT UNSIGNED PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS parties (
    id CHAR(36) PRIMARY KEY,
    guild_id BIGINT UNSIGNED NOT NULL,
    channel_id BIGINT UNSIGNED NOT NULL,
    leader_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_parties_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS party_members (
    guild_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    party_id CHAR(36) NOT NULL,
    joined_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (guild_id, user_id),
    INDEX idx_party_members_party (party_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 確定状態と共有探索の期限。既存パーティーは募集状態のまま引き継ぐ。
CREATE TABLE IF NOT EXISTS party_states (
    party_id CHAR(36) PRIMARY KEY,
    confirmation_id VARCHAR(36) NOT NULL DEFAULT '',
    run_id VARCHAR(36) NOT NULL DEFAULT '',
    expires_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- パーティーから独立したゲーム内ギルド。再実行可能な追加のみの変更。
CREATE TABLE IF NOT EXISTS game_guild_locks (
    server_id BIGINT UNSIGNED PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_guilds (
    id CHAR(36) PRIMARY KEY,
    server_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(32) NOT NULL,
    passphrase_hash CHAR(64) NOT NULL,
    leader_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY uq_game_guild_passphrase (server_id, passphrase_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_guild_members (
    server_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    game_guild_id CHAR(36) NOT NULL,
    server_joined_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (server_id, user_id),
    INDEX idx_game_guild_members_guild (game_guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
