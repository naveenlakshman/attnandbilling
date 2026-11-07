SET @student_password_changed_at_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'students'
      AND COLUMN_NAME = 'password_changed_at'
);

SET @student_password_changed_at_sql = IF(
    @student_password_changed_at_exists = 0,
    'ALTER TABLE students ADD COLUMN password_changed_at DATETIME NULL AFTER password_hash',
    'SELECT 1'
);

PREPARE student_password_changed_at_stmt FROM @student_password_changed_at_sql;
EXECUTE student_password_changed_at_stmt;
DEALLOCATE PREPARE student_password_changed_at_stmt;
