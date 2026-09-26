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
