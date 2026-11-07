-- Smart Counselling Phase 4: prospect identity continuity and versioned assessment.
-- Apply manually after Phase 2 and Phase 3. Additive only.

ALTER TABLE counselling_sessions
    ADD COLUMN identity_mobile_normalized VARCHAR(13) NULL AFTER verified_mobile_normalized;

UPDATE counselling_sessions
SET identity_mobile_normalized = verified_mobile_normalized
WHERE identity_mobile_normalized IS NULL AND verified_mobile_normalized IS NOT NULL;

CREATE TABLE counselling_assessments (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    counselling_session_id BIGINT NOT NULL,
    lead_id INT NOT NULL,
    assessment_version VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS',
    started_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sc_assessment_session UNIQUE (counselling_session_id),
    CONSTRAINT fk_sc_assessment_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_assessment_session FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
    CONSTRAINT fk_sc_assessment_lead FOREIGN KEY (lead_id) REFERENCES leads(id),
    CONSTRAINT chk_sc_assessment_status CHECK (status IN ('IN_PROGRESS','COMPLETED')),
    INDEX idx_sc_assessment_tenant_status (institute_id, status, updated_at),
    INDEX idx_sc_assessment_tenant_lead (institute_id, lead_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE counselling_lead_creation_requests (
    counselling_session_id BIGINT NOT NULL,
    institute_id BIGINT NOT NULL,
    lead_id INT NULL,
    created_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    PRIMARY KEY (counselling_session_id),
    CONSTRAINT uq_sc_lead_creation_lead UNIQUE (lead_id),
    CONSTRAINT fk_sc_lead_creation_session FOREIGN KEY (counselling_session_id) REFERENCES counselling_sessions(id),
    CONSTRAINT fk_sc_lead_creation_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_lead_creation_lead FOREIGN KEY (lead_id) REFERENCES leads(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE counselling_assessment_answers (
    id BIGINT NOT NULL AUTO_INCREMENT,
    assessment_id BIGINT NOT NULL,
    question_key VARCHAR(64) NOT NULL,
    answer_value JSON NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sc_answer_question UNIQUE (assessment_id, question_key),
    CONSTRAINT fk_sc_answer_assessment FOREIGN KEY (assessment_id)
        REFERENCES counselling_assessments(id) ON DELETE CASCADE,
    INDEX idx_sc_answer_assessment (assessment_id, question_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Emergency rollback (destructive; back up first and require explicit approval):
-- DROP TABLE counselling_lead_creation_requests;
-- DROP TABLE counselling_assessment_answers;
-- DROP TABLE counselling_assessments;
-- ALTER TABLE counselling_sessions DROP COLUMN identity_mobile_normalized;
