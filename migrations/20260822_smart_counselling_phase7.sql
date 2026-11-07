-- Smart Counselling Phase 7: expressed course interest, separate from recommendation score.
-- Apply after Phase 2 through Phase 6 migrations.

CREATE TABLE counselling_course_interests (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    counselling_session_id BIGINT NOT NULL,
    lead_id INT NOT NULL,
    recommendation_run_id BIGINT NOT NULL,
    course_id INT NOT NULL,
    interest_level ENUM('INTERESTED','HIGHLY_INTERESTED','NOT_INTERESTED') NOT NULL,
    is_primary TINYINT(1) NOT NULL DEFAULT 0,
    primary_session_id BIGINT GENERATED ALWAYS AS (CASE WHEN is_primary=1 THEN counselling_session_id ELSE NULL END) STORED,
    created_by_user_id INT NOT NULL,
    updated_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY(id),
    UNIQUE KEY uq_sc_course_interest_session_course(counselling_session_id,course_id),
    UNIQUE KEY uq_sc_course_interest_one_primary(primary_session_id),
    KEY idx_sc_course_interest_tenant_session(institute_id,counselling_session_id,updated_at),
    KEY idx_sc_course_interest_tenant_lead(institute_id,lead_id,updated_at),
    CONSTRAINT fk_sc_session_interest_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_session_interest_session FOREIGN KEY(counselling_session_id) REFERENCES counselling_sessions(id),
    CONSTRAINT fk_sc_session_interest_lead FOREIGN KEY(lead_id) REFERENCES leads(id),
    CONSTRAINT fk_sc_session_interest_run FOREIGN KEY(recommendation_run_id) REFERENCES recommendation_runs(id),
    CONSTRAINT fk_sc_session_interest_course FOREIGN KEY(course_id) REFERENCES courses(id),
    CONSTRAINT fk_sc_session_interest_created_by FOREIGN KEY(created_by_user_id) REFERENCES users(id),
    CONSTRAINT fk_sc_session_interest_updated_by FOREIGN KEY(updated_by_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Destructive rollback only after confirming Phase 7 interest data is disposable:
-- DROP TABLE counselling_course_interests;
