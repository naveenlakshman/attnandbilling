-- Phase 9: platform onboarding, subscriptions, quotas, and lifecycle enforcement.
-- Additive, production-safe, and safe to re-run.

CREATE TABLE IF NOT EXISTS subscription_plans (
    id BIGINT NOT NULL AUTO_INCREMENT,
    code VARCHAR(60) NOT NULL,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(500) NULL,
    branch_limit INTEGER NULL,
    staff_limit INTEGER NULL,
    student_limit INTEGER NULL,
    storage_limit_bytes BIGINT NULL,
    features_json JSON NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_subscription_plans_code (code),
    KEY idx_subscription_plans_active (is_active, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_subscriptions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    plan_id BIGINT NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    starts_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trial_ends_at DATETIME NULL,
    grace_ends_at DATETIME NULL,
    suspended_at DATETIME NULL,
    suspension_reason VARCHAR(500) NULL,
    branch_limit_override INTEGER NULL,
    staff_limit_override INTEGER NULL,
    student_limit_override INTEGER NULL,
    storage_limit_bytes_override BIGINT NULL,
    feature_overrides_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_subscriptions_institute (institute_id),
    KEY idx_institute_subscriptions_status (status, grace_ends_at),
    CONSTRAINT fk_institute_subscriptions_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE,
    CONSTRAINT fk_institute_subscriptions_plan
        FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS institute_onboarding (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'draft',
    current_step INTEGER NOT NULL DEFAULT 1,
    checklist_json JSON NULL,
    created_by INTEGER NULL,
    completed_by INTEGER NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    completed_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_institute_onboarding_institute (institute_id),
    KEY idx_institute_onboarding_status (status, updated_at),
    CONSTRAINT fk_institute_onboarding_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE,
    CONSTRAINT fk_institute_onboarding_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_institute_onboarding_completed_by
        FOREIGN KEY (completed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_storage_objects (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    object_path VARCHAR(700) NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    content_type VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_tenant_storage_object_path (object_path),
    KEY idx_tenant_storage_objects_usage (institute_id, size_bytes),
    CONSTRAINT fk_tenant_storage_objects_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO subscription_plans (
    code, name, description, branch_limit, staff_limit, student_limit,
    storage_limit_bytes, features_json, is_active, sort_order, updated_at
) VALUES
    (
        'starter', 'Starter', 'For a small institute beginning with the platform.',
        1, 5, 250, 1073741824,
        JSON_OBJECT(
            'crm', TRUE, 'students', TRUE, 'finance', TRUE,
            'attendance', TRUE, 'reports', TRUE, 'lms', TRUE,
            'certificates', FALSE, 'integrations', FALSE
        ),
        1, 10, CURRENT_TIMESTAMP
    ),
    (
        'growth', 'Growth', 'For a growing institute with multiple teams and branches.',
        5, 30, 2500, 10737418240,
        JSON_OBJECT(
            'crm', TRUE, 'students', TRUE, 'finance', TRUE,
            'attendance', TRUE, 'reports', TRUE, 'lms', TRUE,
            'certificates', TRUE, 'integrations', TRUE,
            'smart_counselling', TRUE
        ),
        1, 20, CURRENT_TIMESTAMP
    ),
    (
        'enterprise', 'Enterprise', 'Unlimited platform plan for contracted institutes.',
        NULL, NULL, NULL, NULL,
        JSON_OBJECT(
            'crm', TRUE, 'students', TRUE, 'finance', TRUE,
            'attendance', TRUE, 'reports', TRUE, 'lms', TRUE,
            'certificates', TRUE, 'integrations', TRUE,
            'smart_counselling', TRUE
        ),
        1, 30, CURRENT_TIMESTAMP
    )
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    description = VALUES(description),
    branch_limit = VALUES(branch_limit),
    staff_limit = VALUES(staff_limit),
    student_limit = VALUES(student_limit),
    storage_limit_bytes = VALUES(storage_limit_bytes),
    features_json = VALUES(features_json),
    is_active = VALUES(is_active),
    sort_order = VALUES(sort_order),
    updated_at = CURRENT_TIMESTAMP;

-- Preserve behavior for every institute that existed before Phase 9.
INSERT INTO institute_subscriptions (
    institute_id, plan_id, status, starts_at, created_at, updated_at
)
SELECT i.id, p.id, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM institutes i
JOIN subscription_plans p ON p.code = 'enterprise'
LEFT JOIN institute_subscriptions s ON s.institute_id = i.id
WHERE s.id IS NULL;

