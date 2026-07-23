CREATE TABLE IF NOT EXISTS institutes (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    short_name VARCHAR(120) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
    locale VARCHAR(20) NOT NULL DEFAULT 'en-IN',
    currency_code CHAR(3) NOT NULL DEFAULT 'INR',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institutes_slug (slug),
    KEY idx_institutes_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_domains (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    hostname VARCHAR(255) NOT NULL,
    domain_type VARCHAR(20) NOT NULL DEFAULT 'platform',
    is_primary TINYINT(1) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    verified_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_domains_hostname (hostname),
    KEY idx_institute_domains_institute (institute_id, status),
    CONSTRAINT fk_institute_domains_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_branding (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    short_name VARCHAR(120) NULL,
    tagline VARCHAR(255) NULL,
    logo_path VARCHAR(500) NULL,
    favicon_path VARCHAR(500) NULL,
    primary_color CHAR(7) NOT NULL DEFAULT '#2563EB',
    secondary_color CHAR(7) NOT NULL DEFAULT '#16A34A',
    address TEXT NULL,
    phone VARCHAR(50) NULL,
    email VARCHAR(255) NULL,
    website VARCHAR(500) NULL,
    registration_number VARCHAR(120) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_branding_institute (institute_id),
    CONSTRAINT fk_institute_branding_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_settings (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    invoice_prefix VARCHAR(30) NOT NULL DEFAULT 'INV',
    receipt_prefix VARCHAR(30) NOT NULL DEFAULT 'RCP',
    student_prefix VARCHAR(30) NOT NULL DEFAULT 'STU',
    certificate_prefix VARCHAR(30) NOT NULL DEFAULT 'CERT',
    date_format VARCHAR(40) NOT NULL DEFAULT 'DD-MMM-YYYY',
    settings_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_settings_institute (institute_id),
    CONSTRAINT fk_institute_settings_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_integrations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    integration_type VARCHAR(50) NOT NULL,
    provider VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'inactive',
    secret_reference VARCHAR(500) NULL,
    configuration_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_integration_type (institute_id, integration_type),
    CONSTRAINT fk_institute_integrations_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_memberships (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    user_id INTEGER NOT NULL,
    membership_role VARCHAR(40) NOT NULL DEFAULT 'staff',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_membership_user (institute_id, user_id),
    KEY idx_institute_memberships_user (user_id, is_active),
    CONSTRAINT fk_institute_memberships_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE,
    CONSTRAINT fk_institute_memberships_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_migration_runs (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NULL,
    migration_key VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL,
    checkpoint_json JSON NULL,
    started_by INTEGER NULL,
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    error_message TEXT NULL,
    PRIMARY KEY (id),
    KEY idx_tenant_migration_runs_lookup (institute_id, migration_key, started_at),
    CONSTRAINT fk_tenant_migration_runs_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE SET NULL,
    CONSTRAINT fk_tenant_migration_runs_user
        FOREIGN KEY (started_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_security_audit (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NULL,
    user_id INTEGER NULL,
    student_id INTEGER NULL,
    event_type VARCHAR(80) NOT NULL,
    request_host VARCHAR(255) NULL,
    request_path VARCHAR(1000) NULL,
    details_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_tenant_security_audit_institute (institute_id, created_at),
    KEY idx_tenant_security_audit_event (event_type, created_at),
    CONSTRAINT fk_tenant_security_audit_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE SET NULL,
    CONSTRAINT fk_tenant_security_audit_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_tenant_security_audit_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @phase1_activity_column_sql = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'activity_logs'
          AND COLUMN_NAME = 'institute_id'
    ),
    'SELECT 1',
    'ALTER TABLE activity_logs ADD COLUMN institute_id BIGINT NULL AFTER id'
);
PREPARE phase1_activity_column_stmt FROM @phase1_activity_column_sql;
EXECUTE phase1_activity_column_stmt;
DEALLOCATE PREPARE phase1_activity_column_stmt;
SET @phase1_activity_index_sql = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'activity_logs'
          AND INDEX_NAME = 'idx_activity_logs_institute_created'
    ),
    'SELECT 1',
    'CREATE INDEX idx_activity_logs_institute_created ON activity_logs(institute_id, created_at)'
);
PREPARE phase1_activity_index_stmt FROM @phase1_activity_index_sql;
EXECUTE phase1_activity_index_stmt;
DEALLOCATE PREPARE phase1_activity_index_stmt;
SET @phase1_activity_fk_sql = IF(
    EXISTS(
        SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = 'activity_logs'
          AND CONSTRAINT_NAME = 'fk_activity_logs_institute'
    ),
    'SELECT 1',
    'ALTER TABLE activity_logs ADD CONSTRAINT fk_activity_logs_institute FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE SET NULL'
);
PREPARE phase1_activity_fk_stmt FROM @phase1_activity_fk_sql;
EXECUTE phase1_activity_fk_stmt;
DEALLOCATE PREPARE phase1_activity_fk_stmt;

INSERT INTO institutes (
    id, name, short_name, slug, status, timezone, locale, currency_code, created_at, updated_at
) VALUES (
    1, 'Global IT Education', 'Global IT', 'global-it-education', 'active',
    'Asia/Kolkata', 'en-IN', 'INR', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
) ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    short_name = VALUES(short_name),
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO institute_domains (
    institute_id, hostname, domain_type, is_primary, status, verified_at, created_at
) VALUES
    (1, 'www.globaliterp.com', 'custom', 1, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    (1, 'globaliterp.com', 'custom', 0, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE
    institute_id = VALUES(institute_id),
    status = 'active',
    verified_at = COALESCE(verified_at, CURRENT_TIMESTAMP);

INSERT INTO institute_branding (
    institute_id, display_name, short_name, tagline, logo_path, address, phone,
    email, website, registration_number, created_at, updated_at
)
SELECT
    1, company_name, company_short_name, tagline, logo_filename, address, phone,
    email, website, reg_number, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM company_profile
WHERE id = 1
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    short_name = VALUES(short_name),
    tagline = VALUES(tagline),
    logo_path = VALUES(logo_path),
    address = VALUES(address),
    phone = VALUES(phone),
    email = VALUES(email),
    website = VALUES(website),
    registration_number = VALUES(registration_number),
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO institute_settings (
    institute_id, invoice_prefix, receipt_prefix, student_prefix,
    certificate_prefix, date_format, created_at, updated_at
) VALUES (1, 'GIT/B', 'GIT', 'STU', 'GIT', 'DD-MMM-YYYY', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;

INSERT INTO institute_memberships (
    institute_id, user_id, membership_role, is_active, created_at, updated_at
)
SELECT
    1, id,
    CASE WHEN role = 'admin' THEN 'institute_admin' ELSE role END,
    is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM users
ON DUPLICATE KEY UPDATE
    membership_role = VALUES(membership_role),
    is_active = VALUES(is_active),
    updated_at = CURRENT_TIMESTAMP;

UPDATE activity_logs SET institute_id = 1 WHERE institute_id IS NULL;
