-- 確定状態と共有探索の期限。既存パーティーは募集状態のまま引き継ぐ。
CREATE TABLE IF NOT EXISTS party_states (
    party_id CHAR(36) PRIMARY KEY,
    confirmation_id VARCHAR(36) NOT NULL DEFAULT '',
    run_id VARCHAR(36) NOT NULL DEFAULT '',
    expires_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
