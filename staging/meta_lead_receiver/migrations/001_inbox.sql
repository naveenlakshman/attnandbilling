CREATE TABLE IF NOT EXISTS notifications (
    lead_id VARCHAR(40) NOT NULL,
    page_id VARCHAR(40) NOT NULL,
    form_id VARCHAR(40) NOT NULL,
    ad_id VARCHAR(40) NULL,
    submitted_at DATETIME(6) NULL,
    state ENUM('PENDING','PROCESSING','RETRY','DONE','DEAD') NOT NULL,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    available_at DATETIME(6) NOT NULL,
    lease_until DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    last_error_code VARCHAR(32) NULL,
    result_field_names_json JSON NULL,
    result_answer_count INT UNSIGNED NULL,
    result_values_sha256 CHAR(64) NULL,
    completed_at DATETIME(6) NULL,
    PRIMARY KEY (lead_id),
    KEY ix_notifications_ready (state, available_at, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS audit (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    happened_at DATETIME(6) NOT NULL,
    action VARCHAR(40) NOT NULL,
    counts_json JSON NOT NULL,
    PRIMARY KEY (id),
    KEY ix_audit_time (happened_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
