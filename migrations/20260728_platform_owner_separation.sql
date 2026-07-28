-- Dedicated platform identities and audited, time-limited tenant support sessions.

CREATE TABLE IF NOT EXISTS platform_accounts (
    id BIGINT NOT NULL AUTO_INCREMENT,
    full_name VARCHAR(255) NOT NULL,
    username VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(40) NOT NULL DEFAULT 'platform_owner',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    last_login_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_platform_accounts_username (username),
    KEY idx_platform_accounts_active_role (is_active, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS platform_support_sessions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    platform_account_id BIGINT NOT NULL,
    institute_id BIGINT NOT NULL,
    support_user_id INTEGER NULL,
    reason VARCHAR(500) NOT NULL,
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    last_activity_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME NULL,
    end_reason VARCHAR(120) NULL,
    request_ip VARCHAR(64) NULL,
    user_agent VARCHAR(500) NULL,
    PRIMARY KEY (id),
    KEY idx_platform_support_active (platform_account_id, ended_at, expires_at),
    KEY idx_platform_support_institute (institute_id, started_at),
    CONSTRAINT fk_platform_support_account
        FOREIGN KEY (platform_account_id) REFERENCES platform_accounts(id) ON DELETE RESTRICT,
    CONSTRAINT fk_platform_support_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE RESTRICT,
    CONSTRAINT fk_platform_support_user
        FOREIGN KEY (support_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO platform_accounts (
    full_name, username, password_hash, role, is_active,
    last_login_at, created_at, updated_at
)
SELECT u.full_name, u.username, u.password_hash, 'platform_owner', u.is_active,
       NULL, COALESCE(u.created_at, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP
FROM users u
WHERE u.platform_role = 'platform_owner'
ON DUPLICATE KEY UPDATE
    full_name = VALUES(full_name),
    password_hash = VALUES(password_hash),
    role = 'platform_owner',
    is_active = VALUES(is_active),
    updated_at = CURRENT_TIMESTAMP;

UPDATE institute_memberships im
JOIN users u ON u.id = im.user_id
SET im.is_active = 0, im.updated_at = CURRENT_TIMESTAMP
WHERE u.platform_role = 'platform_owner';

UPDATE users
SET is_active = 0, updated_at = CURRENT_TIMESTAMP
WHERE platform_role = 'platform_owner';
