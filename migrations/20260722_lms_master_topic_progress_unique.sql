-- Deduplicate master-topic progress and enforce one row per student/program/topic.
-- MySQL 8; idempotent after the unique index has been created.

DROP TEMPORARY TABLE IF EXISTS tmp_lms_master_topic_progress_rollup;

CREATE TEMPORARY TABLE tmp_lms_master_topic_progress_rollup AS
SELECT
    student_id,
    program_id,
    master_topic_id,
    MIN(id) AS keep_id,
    MAX(CASE WHEN is_completed = 1 THEN 1 ELSE 0 END) AS merged_is_completed,
    MAX(completed_at) AS merged_completed_at,
    MIN(created_at) AS merged_created_at,
    MAX(updated_at) AS merged_updated_at
FROM lms_master_topic_progress
GROUP BY student_id, program_id, master_topic_id;

UPDATE lms_master_topic_progress progress
JOIN tmp_lms_master_topic_progress_rollup rollup
  ON rollup.keep_id = progress.id
SET
    progress.is_completed = rollup.merged_is_completed,
    progress.completed_at = CASE
        WHEN rollup.merged_is_completed = 1 THEN rollup.merged_completed_at
        ELSE NULL
    END,
    progress.created_at = rollup.merged_created_at,
    progress.updated_at = rollup.merged_updated_at;

DELETE progress
FROM lms_master_topic_progress progress
JOIN tmp_lms_master_topic_progress_rollup rollup
  ON rollup.student_id = progress.student_id
 AND rollup.program_id = progress.program_id
 AND rollup.master_topic_id = progress.master_topic_id
WHERE progress.id <> rollup.keep_id;

DROP TEMPORARY TABLE tmp_lms_master_topic_progress_rollup;

SET @progress_unique_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'lms_master_topic_progress'
      AND INDEX_NAME = 'uq_lms_master_topic_progress_student_program_topic'
);

SET @progress_unique_sql = IF(
    @progress_unique_exists = 0,
    'CREATE UNIQUE INDEX uq_lms_master_topic_progress_student_program_topic ON lms_master_topic_progress (student_id, program_id, master_topic_id)',
    'SELECT ''uq_lms_master_topic_progress_student_program_topic already exists'''
);

PREPARE progress_unique_statement FROM @progress_unique_sql;
EXECUTE progress_unique_statement;
DEALLOCATE PREPARE progress_unique_statement;
