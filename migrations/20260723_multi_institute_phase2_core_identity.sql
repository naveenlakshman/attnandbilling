-- Phase 2: platform administration and tenant-owned branches/users.
-- Additive and safe to re-run.

SET @p2_branch_institute_column = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'branches'
          AND COLUMN_NAME = 'institute_id'
    ),
    'SELECT 1',
    'ALTER TABLE branches ADD COLUMN institute_id BIGINT NULL AFTER id'
);
PREPARE p2_stmt FROM @p2_branch_institute_column;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_user_institute_column = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'institute_id'
    ),
    'SELECT 1',
    'ALTER TABLE users ADD COLUMN institute_id BIGINT NULL AFTER id'
);
PREPARE p2_stmt FROM @p2_user_institute_column;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_user_platform_role_column = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'platform_role'
    ),
    'SELECT 1',
    'ALTER TABLE users ADD COLUMN platform_role VARCHAR(40) NULL AFTER role'
);
PREPARE p2_stmt FROM @p2_user_platform_role_column;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

UPDATE branches SET institute_id = 1 WHERE institute_id IS NULL;
UPDATE users SET institute_id = 1 WHERE institute_id IS NULL;

-- The original system owner becomes the first platform owner. This is
-- deterministic on the existing database and can be reassigned later.
UPDATE users
SET platform_role = 'platform_owner'
WHERE id = (
    SELECT owner_id FROM (
        SELECT MIN(id) AS owner_id
        FROM users
        WHERE role = 'admin' AND is_active = 1
    ) AS first_owner
)
  AND platform_role IS NULL;

SET @p2_branch_institute_not_null = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'branches'
          AND COLUMN_NAME = 'institute_id'
          AND IS_NULLABLE = 'YES'
    ),
    'ALTER TABLE branches MODIFY institute_id BIGINT NOT NULL',
    'SELECT 1'
);
PREPARE p2_stmt FROM @p2_branch_institute_not_null;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_user_institute_not_null = IF(
    EXISTS(
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'institute_id'
          AND IS_NULLABLE = 'YES'
    ),
    'ALTER TABLE users MODIFY institute_id BIGINT NOT NULL',
    'SELECT 1'
);
PREPARE p2_stmt FROM @p2_user_institute_not_null;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_branch_fk = IF(
    EXISTS(
        SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = 'branches'
          AND CONSTRAINT_NAME = 'fk_branches_institute'
    ),
    'SELECT 1',
    'ALTER TABLE branches ADD CONSTRAINT fk_branches_institute FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE RESTRICT'
);
PREPARE p2_stmt FROM @p2_branch_fk;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_user_fk = IF(
    EXISTS(
        SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND CONSTRAINT_NAME = 'fk_users_institute'
    ),
    'SELECT 1',
    'ALTER TABLE users ADD CONSTRAINT fk_users_institute FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE RESTRICT'
);
PREPARE p2_stmt FROM @p2_user_fk;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_branch_code_unique = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'branches'
          AND INDEX_NAME = 'uq_branches_institute_code'
    ),
    'SELECT 1',
    'CREATE UNIQUE INDEX uq_branches_institute_code ON branches(institute_id, branch_code)'
);
PREPARE p2_stmt FROM @p2_branch_code_unique;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_branch_name_unique = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'branches'
          AND INDEX_NAME = 'uq_branches_institute_name'
    ),
    'SELECT 1',
    'CREATE UNIQUE INDEX uq_branches_institute_name ON branches(institute_id, branch_name)'
);
PREPARE p2_stmt FROM @p2_branch_name_unique;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_user_username_unique = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND INDEX_NAME = 'uq_users_institute_username'
    ),
    'SELECT 1',
    'CREATE UNIQUE INDEX uq_users_institute_username ON users(institute_id, username)'
);
PREPARE p2_stmt FROM @p2_user_username_unique;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_branch_active_index = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'branches'
          AND INDEX_NAME = 'idx_branches_institute_active'
    ),
    'SELECT 1',
    'CREATE INDEX idx_branches_institute_active ON branches(institute_id, is_active)'
);
PREPARE p2_stmt FROM @p2_branch_active_index;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;

SET @p2_user_active_index = IF(
    EXISTS(
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND INDEX_NAME = 'idx_users_institute_active'
    ),
    'SELECT 1',
    'CREATE INDEX idx_users_institute_active ON users(institute_id, is_active)'
);
PREPARE p2_stmt FROM @p2_user_active_index;
EXECUTE p2_stmt;
DEALLOCATE PREPARE p2_stmt;
