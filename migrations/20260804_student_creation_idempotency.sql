CREATE TABLE IF NOT EXISTS student_creation_requests (
    token VARCHAR(64) PRIMARY KEY,
    institute_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    student_id BIGINT NULL,
    created_at VARCHAR(32) NOT NULL,
    completed_at VARCHAR(32) NULL,
    UNIQUE KEY uq_student_creation_fingerprint (institute_id, request_fingerprint),
    INDEX idx_student_creation_institute_user (institute_id, user_id, created_at),
    INDEX idx_student_creation_student (student_id)
);
