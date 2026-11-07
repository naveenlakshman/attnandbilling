-- Smart Counselling Phase 2: additive session lifecycle and audit foundation.
-- MySQL 8 / Cloud SQL migration. Apply manually after backup and schema review.
-- This migration does not create OTP, assessment, recommendation, LMS, or follow-up tables.

CREATE TABLE counselling_sessions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    branch_id INT NOT NULL,
    lead_id INT NULL,
    counsellor_user_id INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'IDENTIFICATION_PENDING',
    mobile_verified TINYINT(1) NOT NULL DEFAULT 0,
    verification_method VARCHAR(32) NULL,
    primary_interested_course_id INT NULL,
    secondary_interested_course_id INT NULL,
    outcome VARCHAR(50) NULL,
    outcome_reason VARCHAR(255) NULL,
    next_action VARCHAR(100) NULL,
    next_followup_date DATE NULL,
    staff_notes TEXT NULL,
    abandon_reason VARCHAR(255) NULL,
    started_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    abandoned_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT chk_counselling_sessions_status CHECK (
        status IN (
            'STARTED', 'IDENTIFICATION_PENDING', 'IDENTIFIED', 'IN_PROGRESS',
            'OUTCOME_PENDING', 'COMPLETED', 'ABANDONED'
        )
    ),
    CONSTRAINT chk_counselling_sessions_mobile_verified CHECK (mobile_verified IN (0, 1)),
    CONSTRAINT fk_counselling_sessions_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_counselling_sessions_branch FOREIGN KEY (branch_id) REFERENCES branches(id),
    CONSTRAINT fk_counselling_sessions_lead FOREIGN KEY (lead_id) REFERENCES leads(id),
    CONSTRAINT fk_counselling_sessions_counsellor FOREIGN KEY (counsellor_user_id) REFERENCES users(id),
    CONSTRAINT fk_counselling_sessions_primary_course FOREIGN KEY (primary_interested_course_id) REFERENCES courses(id),
    CONSTRAINT fk_counselling_sessions_secondary_course FOREIGN KEY (secondary_interested_course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_counselling_sessions_tenant_status_started
    ON counselling_sessions (institute_id, status, started_at);
CREATE INDEX idx_counselling_sessions_tenant_branch_status
    ON counselling_sessions (institute_id, branch_id, status, started_at);
CREATE INDEX idx_counselling_sessions_tenant_counsellor_open
    ON counselling_sessions (institute_id, counsellor_user_id, status, updated_at);
CREATE INDEX idx_counselling_sessions_tenant_lead_history
    ON counselling_sessions (institute_id, lead_id, started_at);

CREATE TABLE counselling_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    counselling_session_id BIGINT NOT NULL,
    lead_id INT NULL,
    actor_user_id INT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    metadata_json JSON NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_counselling_events_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_counselling_events_session FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
    CONSTRAINT fk_counselling_events_lead FOREIGN KEY (lead_id) REFERENCES leads(id),
    CONSTRAINT fk_counselling_events_actor FOREIGN KEY (actor_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_counselling_events_tenant_session_created
    ON counselling_events (institute_id, counselling_session_id, created_at);
CREATE INDEX idx_counselling_events_tenant_actor_created
    ON counselling_events (institute_id, actor_user_id, created_at);

-- Emergency rollback (destructive; take a backup first):
-- DROP TABLE counselling_events;
-- DROP TABLE counselling_sessions;
