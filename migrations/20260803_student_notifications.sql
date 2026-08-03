CREATE TABLE IF NOT EXISTS notifications (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    notification_type VARCHAR(40) NOT NULL,
    title VARCHAR(160) NOT NULL,
    message TEXT NOT NULL,
    icon VARCHAR(60) NOT NULL,
    color VARCHAR(20) NOT NULL,
    action_label VARCHAR(80) NULL,
    action_url VARCHAR(500) NULL,
    audience_type VARCHAR(30) NOT NULL DEFAULT 'all_students',
    priority INT NOT NULL DEFAULT 50,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_notifications_institute_active_schedule (institute_id, is_active, starts_at, ends_at, priority),
    CONSTRAINT fk_notifications_institute FOREIGN KEY (institute_id) REFERENCES institutes(id),
    CONSTRAINT fk_notifications_creator FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notification_targets (
    id BIGINT NOT NULL AUTO_INCREMENT,
    notification_id BIGINT NOT NULL,
    target_type VARCHAR(20) NOT NULL,
    target_id BIGINT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_notification_target (notification_id, target_type, target_id),
    KEY ix_notification_targets_lookup (target_type, target_id),
    CONSTRAINT fk_notification_targets_notification FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notification_receipts (
    id BIGINT NOT NULL AUTO_INCREMENT,
    notification_id BIGINT NOT NULL,
    student_id INT NOT NULL,
    institute_id BIGINT NOT NULL,
    first_viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    view_count INT NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_notification_receipt (notification_id, student_id),
    KEY ix_notification_receipts_tenant_student (institute_id, student_id),
    CONSTRAINT fk_notification_receipts_notification FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
