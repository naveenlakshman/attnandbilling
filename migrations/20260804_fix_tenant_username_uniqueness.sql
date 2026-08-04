-- Replace the legacy global username constraint with tenant-scoped uniqueness.
-- Usernames may repeat across institutes, but not inside the same institute.

SET @create_tenant_username_index = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND INDEX_NAME = 'uq_users_institute_username'
    ),
    'SELECT 1',
    'CREATE UNIQUE INDEX uq_users_institute_username ON users(institute_id, username)'
);
PREPARE tenant_username_stmt FROM @create_tenant_username_index;
EXECUTE tenant_username_stmt;
DEALLOCATE PREPARE tenant_username_stmt;

SET @drop_global_username_index = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND INDEX_NAME = 'idx_users_username'
    ),
    'DROP INDEX idx_users_username ON users',
    'SELECT 1'
);
PREPARE global_username_stmt FROM @drop_global_username_index;
EXECUTE global_username_stmt;
DEALLOCATE PREPARE global_username_stmt;
