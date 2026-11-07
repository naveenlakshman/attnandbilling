-- Smart Counselling Phase 5: tenant-scoped course intelligence.
-- Additive only. Apply after Phase 2, Phase 3, and Phase 4 migrations.

CREATE TABLE course_profiles (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    course_id INT NOT NULL,
    short_description TEXT NULL,
    detailed_description LONGTEXT NULL,
    course_purpose TEXT NULL,
    minimum_education_level VARCHAR(40) NULL,
    preferred_background TEXT NULL,
    target_audience TEXT NULL,
    hard_eligibility_text TEXT NULL,
    starting_skill_level VARCHAR(40) NULL,
    certification_title VARCHAR(255) NULL,
    certification_issuing_body VARCHAR(255) NULL,
    certification_included TINYINT(1) NOT NULL DEFAULT 0,
    external_exam_required TINYINT(1) NOT NULL DEFAULT 0,
    certification_details TEXT NULL,
    recommendation_enabled TINYINT(1) NOT NULL DEFAULT 0,
    created_by_user_id INT NOT NULL,
    updated_by_user_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_sc_course_profile_tenant_course (institute_id, course_id),
    KEY idx_sc_course_profiles_tenant_enabled (institute_id, recommendation_enabled, course_id),
    CONSTRAINT fk_sc_course_profile_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_profile_course FOREIGN KEY (course_id) REFERENCES courses(id),
    CONSTRAINT fk_sc_course_profile_created_by FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CONSTRAINT fk_sc_course_profile_updated_by FOREIGN KEY (updated_by_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_supported_goals (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL, goal_code VARCHAR(64) NOT NULL,
    match_strength VARCHAR(16) NOT NULL DEFAULT 'SUPPORTED', is_primary TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY(id), UNIQUE KEY uq_sc_course_goal(institute_id,course_id,goal_code),
    KEY idx_sc_course_goals_lookup(institute_id,goal_code,course_id),
    CONSTRAINT fk_sc_course_goal_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_goal_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_supported_interests (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL, interest_code VARCHAR(64) NOT NULL,
    match_strength VARCHAR(16) NOT NULL DEFAULT 'SUPPORTED', is_primary TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY(id), UNIQUE KEY uq_sc_course_interest(institute_id,course_id,interest_code),
    KEY idx_sc_course_interests_lookup(institute_id,interest_code,course_id),
    CONSTRAINT fk_sc_course_interest_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_interest_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_education_suitability (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL, education_code VARCHAR(64) NOT NULL,
    suitability_type ENUM('ALLOWED','PREFERRED') NOT NULL,
    PRIMARY KEY(id), UNIQUE KEY uq_sc_course_education(institute_id,course_id,education_code,suitability_type),
    KEY idx_sc_course_education_lookup(institute_id,course_id,suitability_type),
    CONSTRAINT fk_sc_course_education_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_education_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_skill_requirements (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL, skill_dimension VARCHAR(32) NOT NULL, minimum_level VARCHAR(32) NOT NULL,
    PRIMARY KEY(id), UNIQUE KEY uq_sc_course_requirement(institute_id,course_id,skill_dimension),
    KEY idx_sc_course_requirements_lookup(institute_id,course_id),
    CONSTRAINT fk_sc_course_requirement_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_requirement_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_skills_taught (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL, skill_code VARCHAR(64) NOT NULL, is_primary TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY(id), UNIQUE KEY uq_sc_course_skill(institute_id,course_id,skill_code),
    KEY idx_sc_course_skills_lookup(institute_id,skill_code,course_id),
    CONSTRAINT fk_sc_course_skill_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_skill_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_profile_items (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL,
    item_type ENUM('LEARNING_OUTCOME','CAREER_OUTCOME','JOB_ROLE') NOT NULL,
    item_text TEXT NOT NULL, display_order INT NOT NULL DEFAULT 0,
    PRIMARY KEY(id), UNIQUE KEY uq_sc_course_profile_item(institute_id,course_id,item_type,item_text(191)),
    KEY idx_sc_course_items_lookup(institute_id,course_id,item_type,display_order),
    CONSTRAINT fk_sc_course_item_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_item_course FOREIGN KEY(course_id) REFERENCES courses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE course_profile_events (
    id BIGINT NOT NULL AUTO_INCREMENT, institute_id BIGINT NOT NULL,
    course_id INT NOT NULL, actor_user_id INT NOT NULL,
    event_type VARCHAR(64) NOT NULL, changed_fields_json JSON NULL, created_at DATETIME NOT NULL,
    PRIMARY KEY(id), KEY idx_sc_course_profile_events(institute_id,course_id,created_at),
    CONSTRAINT fk_sc_course_event_institute FOREIGN KEY(institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_sc_course_event_course FOREIGN KEY(course_id) REFERENCES courses(id),
    CONSTRAINT fk_sc_course_event_actor FOREIGN KEY(actor_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rollback (destructive; only after confirming no Phase 5 data is needed):
-- DROP TABLE course_profile_events, course_profile_items, course_skills_taught,
--   course_skill_requirements, course_education_suitability,
--   course_supported_interests, course_supported_goals, course_profiles;
