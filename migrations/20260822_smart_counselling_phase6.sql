-- Smart Counselling Phase 6: immutable deterministic recommendation runs.
-- Apply after the Phase 2, Phase 3, Phase 4, and Phase 5 migrations.

CREATE TABLE recommendation_runs (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    counselling_session_id BIGINT NOT NULL,
    lead_id INT NOT NULL,
    assessment_id BIGINT NOT NULL,
    assessment_version VARCHAR(64) NOT NULL,
    engine_version VARCHAR(64) NOT NULL,
    status ENUM('PENDING','COMPLETED','FAILED') NOT NULL,
    outcome_status VARCHAR(32) NULL,
    prospect_snapshot_json JSON NOT NULL,
    created_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    PRIMARY KEY(id),
    KEY idx_sc_rec_runs_tenant_session_created(institute_id,counselling_session_id,status,created_at),
    KEY idx_sc_rec_runs_tenant_assessment(institute_id,assessment_id,created_at),
    CONSTRAINT fk_sc_rec_run_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_rec_run_session FOREIGN KEY(counselling_session_id) REFERENCES counselling_sessions(id),
    CONSTRAINT fk_sc_rec_run_lead FOREIGN KEY(lead_id) REFERENCES leads(id),
    CONSTRAINT fk_sc_rec_run_assessment FOREIGN KEY(assessment_id) REFERENCES counselling_assessments(id),
    CONSTRAINT fk_sc_rec_run_actor FOREIGN KEY(created_by_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recommendation_results (
    id BIGINT NOT NULL AUTO_INCREMENT,
    recommendation_run_id BIGINT NOT NULL,
    institute_id BIGINT NOT NULL,
    course_id INT NOT NULL,
    course_name_snapshot VARCHAR(255) NOT NULL,
    course_category_snapshot VARCHAR(255) NULL,
    course_profile_updated_at DATETIME NULL,
    result_rank INT NULL,
    raw_score DECIMAL(12,6) NULL,
    normalized_score SMALLINT NULL,
    match_label VARCHAR(32) NULL,
    eligibility_status ENUM('ELIGIBLE','INELIGIBLE') NOT NULL,
    matched_factors_json JSON NOT NULL,
    unmatched_factors_json JSON NOT NULL,
    ineligibility_reasons_json JSON NOT NULL,
    skill_chips_json JSON NOT NULL,
    explanation TEXT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY(id),
    UNIQUE KEY uq_sc_rec_result_run_course(recommendation_run_id,course_id),
    KEY idx_sc_rec_results_run_rank(recommendation_run_id,eligibility_status,result_rank),
    KEY idx_sc_rec_results_tenant_course(institute_id,course_id,recommendation_run_id),
    CONSTRAINT fk_sc_rec_result_run FOREIGN KEY(recommendation_run_id) REFERENCES recommendation_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_sc_rec_result_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_rec_result_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Destructive rollback; use only after confirming Phase 6 history is disposable:
-- DROP TABLE recommendation_results;
-- DROP TABLE recommendation_runs;
