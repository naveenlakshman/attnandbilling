-- Phase 9: optional assignment grading, deadlines, rubrics, and completion rules.
-- Existing rows retain accept/reject grading and accepted-submission completion.

ALTER TABLE lms_assignments
    ADD COLUMN due_at DATETIME NULL,
    ADD COLUMN max_score DECIMAL(10,2) NULL,
    ADD COLUMN passing_score DECIMAL(10,2) NULL,
    ADD COLUMN grading_mode VARCHAR(32) NOT NULL DEFAULT 'accept_reject',
    ADD COLUMN rubric_id BIGINT NULL,
    ADD COLUMN completion_rule VARCHAR(48) NOT NULL DEFAULT 'accepted_submission',
    ADD COLUMN allow_late_submission TINYINT(1) NOT NULL DEFAULT 1,
    ADD COLUMN max_attempts INT NULL,
    ADD COLUMN is_required TINYINT(1) NOT NULL DEFAULT 1;

ALTER TABLE lms_assignment_submissions
    ADD COLUMN score DECIMAL(10,2) NULL,
    ADD COLUMN is_late TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN graded_at DATETIME NULL,
    ADD COLUMN internal_reviewer_notes TEXT NULL;

CREATE TABLE lms_rubrics (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_by BIGINT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    KEY idx_lms_rubrics_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE lms_rubric_criteria (
    id BIGINT NOT NULL AUTO_INCREMENT,
    rubric_id BIGINT NOT NULL,
    criterion_name VARCHAR(200) NOT NULL,
    description TEXT NULL,
    max_score DECIMAL(10,2) NOT NULL,
    display_order INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_lms_rubric_criteria_rubric (rubric_id, display_order, id),
    CONSTRAINT fk_lms_rubric_criteria_rubric
        FOREIGN KEY (rubric_id) REFERENCES lms_rubrics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE lms_submission_rubric_scores (
    id BIGINT NOT NULL AUTO_INCREMENT,
    submission_id BIGINT NOT NULL,
    criterion_id BIGINT NOT NULL,
    score DECIMAL(10,2) NOT NULL,
    comment TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_lms_submission_rubric_criterion (submission_id, criterion_id),
    KEY idx_lms_submission_rubric_submission (submission_id),
    CONSTRAINT fk_lms_submission_rubric_criterion
        FOREIGN KEY (criterion_id) REFERENCES lms_rubric_criteria(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
