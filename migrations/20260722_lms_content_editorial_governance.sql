CREATE TABLE IF NOT EXISTS lms_content_revisions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    content_id BIGINT NOT NULL,
    master_topic_id BIGINT NULL,
    revision_no INT NOT NULL,
    action_type VARCHAR(32) NOT NULL,
    approval_status VARCHAR(32) NOT NULL DEFAULT 'approved',
    snapshot_json LONGTEXT NOT NULL,
    change_note VARCHAR(500) NULL,
    created_by BIGINT NULL,
    created_at VARCHAR(32) NOT NULL,
    reviewed_by BIGINT NULL,
    reviewed_at VARCHAR(32) NULL,
    review_note VARCHAR(500) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_lms_content_revision_number (content_id, revision_no),
    KEY idx_lms_content_revision_topic (master_topic_id, created_at),
    KEY idx_lms_content_revision_approval (approval_status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
