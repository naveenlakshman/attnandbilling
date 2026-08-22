-- Smart Counselling Phase 3: verified mobile identity and OTP challenges.
-- Apply manually after the Phase 2 migration. This file is intentionally additive.

ALTER TABLE counselling_sessions
    ADD COLUMN verified_mobile_normalized VARCHAR(13) NULL AFTER verification_method;

ALTER TABLE counselling_sessions
    ADD COLUMN identification_status VARCHAR(48) NULL AFTER verified_mobile_normalized;

CREATE TABLE counselling_otp_challenges (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    counselling_session_id BIGINT NOT NULL,
    mobile_normalized VARCHAR(13) NOT NULL,
    otp_hash CHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    send_sequence INT NOT NULL DEFAULT 1,
    expires_at DATETIME NOT NULL,
    resend_available_at DATETIME NOT NULL,
    verified_at DATETIME NULL,
    invalidated_at DATETIME NULL,
    delivery_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    provider_message_id VARCHAR(191) NULL,
    created_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_sc_otp_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_otp_session FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
    CONSTRAINT fk_sc_otp_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CONSTRAINT chk_sc_otp_status CHECK (status IN ('PENDING','VERIFIED','EXPIRED','LOCKED','INVALIDATED')),
    CONSTRAINT chk_sc_otp_delivery CHECK (delivery_status IN ('PENDING','SENT','FAILED')),
    INDEX idx_sc_otp_tenant_session_created (institute_id, counselling_session_id, created_at),
    INDEX idx_sc_otp_tenant_mobile_created (institute_id, mobile_normalized, created_at),
    INDEX idx_sc_otp_tenant_creator_created (institute_id, created_by_user_id, created_at),
    INDEX idx_sc_otp_tenant_status_expiry (institute_id, status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_sc_sessions_tenant_verified_mobile
    ON counselling_sessions(institute_id, verified_mobile_normalized);

-- Emergency rollback (destructive; execute only with explicit approval):
-- DROP TABLE counselling_otp_challenges;
-- ALTER TABLE counselling_sessions DROP COLUMN verified_mobile_normalized;
-- ALTER TABLE counselling_sessions DROP COLUMN identification_status;
