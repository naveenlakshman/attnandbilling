-- Support assignment dashboard and review-queue queries that count only the
-- latest attempt and group/filter it by review status.
-- This migration is idempotent for MySQL 8.

SET @index_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'lms_assignment_submissions'
      AND INDEX_NAME = 'idx_lms_asn_assignment_latest_review'
);

SET @index_sql = IF(
    @index_exists = 0,
    'CREATE INDEX idx_lms_asn_assignment_latest_review ON lms_assignment_submissions (assignment_id, is_latest, review_status)',
    'SELECT ''idx_lms_asn_assignment_latest_review already exists'''
);

PREPARE phase3_index_statement FROM @index_sql;
EXECUTE phase3_index_statement;
DEALLOCATE PREPARE phase3_index_statement;
