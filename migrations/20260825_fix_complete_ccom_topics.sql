-- Repair the complete original CCOM curriculum (program 1).
-- The production audit found imported July 22 records only in Word chapter 5;
-- those records are removed after progress migration, then every CCOM chapter
-- is renumbered sequentially. The separate CCOM-with-AI program is untouched.
-- MySQL 8.0. Run only after the preflight SELECTs at the bottom return the
-- expected IDs and titles. The backup tables make the data correction auditable.

START TRANSACTION;

CREATE TABLE IF NOT EXISTS backup_20260825_ccom_word_topics LIKE lms_master_topics;
INSERT IGNORE INTO backup_20260825_ccom_word_topics
SELECT * FROM lms_master_topics WHERE id IN (1045,1046,1047,1048,1049,1050,1051,1052);

CREATE TABLE IF NOT EXISTS backup_20260825_ccom_word_progress LIKE lms_master_topic_progress;
INSERT IGNORE INTO backup_20260825_ccom_word_progress
SELECT target.*
FROM lms_master_topic_progress target
WHERE target.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
   OR (
       target.master_topic_id IN (351,27,28,30,37)
       AND EXISTS (
           SELECT 1 FROM lms_master_topic_progress source
           WHERE source.student_id = target.student_id
             AND source.program_id = target.program_id
             AND source.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
       )
   );

CREATE TABLE IF NOT EXISTS backup_20260825_ccom_word_batch_progress LIKE lms_batch_topic_progress;
INSERT IGNORE INTO backup_20260825_ccom_word_batch_progress
SELECT target.*
FROM lms_batch_topic_progress target
WHERE target.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
   OR (
       target.master_topic_id IN (351,27,28,30,37)
       AND EXISTS (
           SELECT 1 FROM lms_batch_topic_progress source
           WHERE source.batch_id = target.batch_id
             AND source.program_id = target.program_id
             AND source.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
       )
   );

CREATE TABLE IF NOT EXISTS backup_20260825_ccom_word_last_activity LIKE student_program_last_activity;
INSERT IGNORE INTO backup_20260825_ccom_word_last_activity
SELECT target.*
FROM student_program_last_activity target
WHERE target.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
   OR (
       target.master_topic_id IN (351,27,28,30,37)
       AND EXISTS (
           SELECT 1 FROM student_program_last_activity source
           WHERE source.student_id = target.student_id
             AND source.program_id = target.program_id
             AND source.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
       )
   );

CREATE TABLE IF NOT EXISTS backup_20260825_ccom_word_contents LIKE lms_topic_contents;
INSERT IGNORE INTO backup_20260825_ccom_word_contents
SELECT * FROM lms_topic_contents WHERE master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052);

CREATE TABLE IF NOT EXISTS backup_20260825_ccom_word_bridge LIKE lms_master_topic_bridge;
INSERT IGNORE INTO backup_20260825_ccom_word_bridge
SELECT * FROM lms_master_topic_bridge WHERE master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052);

DROP TEMPORARY TABLE IF EXISTS tmp_ccom_word_topic_map;
CREATE TEMPORARY TABLE tmp_ccom_word_topic_map (
    source_topic_id INT PRIMARY KEY,
    target_topic_id INT NOT NULL
);

-- Map imported completion to the closest original CCOM learning outcome.
INSERT INTO tmp_ccom_word_topic_map (source_topic_id, target_topic_id) VALUES
    (1045, 351), -- Introduction -> original Introduction
    (1046, 351), -- Why Word -> original Introduction
    (1047,  27), -- Uses -> Basic Document Operations
    (1048,  27), -- Keyboard productivity -> Basic Document Operations
    (1049,  28), -- Styles/themes -> Text Formatting
    (1050,  30), -- Headers/footers -> Sections and Page Setup
    (1051,  37), -- Mail merge -> Introduction to Mail Merge
    (1052,  37); -- Document automation -> Introduction to Mail Merge

-- Abort safely if production no longer contains exactly the reviewed records.
SET @source_count = (
    SELECT COUNT(*) FROM lms_master_topics mt
    JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = mt.id
    WHERE mt.master_chapter_id = 5
);
SET @target_count = (
    SELECT COUNT(*) FROM lms_master_topics mt
    JOIN (SELECT DISTINCT target_topic_id FROM tmp_ccom_word_topic_map) m ON m.target_topic_id = mt.id
    WHERE mt.master_chapter_id = 5
);
DROP TEMPORARY TABLE IF EXISTS tmp_ccom_word_guard;
CREATE TEMPORARY TABLE tmp_ccom_word_guard (
    guard_passed INT NOT NULL CHECK (guard_passed = 1)
);
INSERT INTO tmp_ccom_word_guard (guard_passed)
VALUES (IF(@source_count = 8 AND @target_count = 5, 1, 0));
SELECT 'CCOM Word migration guard passed' AS guard_result;

-- Merge student completion into original topics. ON DUPLICATE KEY preserves
-- completion if either the original or imported topic was completed.
INSERT INTO lms_master_topic_progress
    (student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at)
SELECT
    p.student_id,
    p.program_id,
    m.target_topic_id,
    MAX(p.is_completed),
    MAX(CASE WHEN p.is_completed = 1 THEN p.completed_at END),
    MIN(p.created_at),
    MAX(p.updated_at)
FROM lms_master_topic_progress p
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = p.master_topic_id
GROUP BY p.student_id, p.program_id, m.target_topic_id
ON DUPLICATE KEY UPDATE
    is_completed = GREATEST(lms_master_topic_progress.is_completed, VALUES(is_completed)),
    completed_at = CASE
        WHEN GREATEST(lms_master_topic_progress.is_completed, VALUES(is_completed)) = 1
        THEN GREATEST(COALESCE(lms_master_topic_progress.completed_at, '1000-01-01'),
                      COALESCE(VALUES(completed_at), '1000-01-01'))
        ELSE NULL
    END,
    created_at = LEAST(lms_master_topic_progress.created_at, VALUES(created_at)),
    updated_at = GREATEST(lms_master_topic_progress.updated_at, VALUES(updated_at));

DELETE p FROM lms_master_topic_progress p
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = p.master_topic_id;

-- Keep one taught marker for each batch/program/original topic.
DROP TEMPORARY TABLE IF EXISTS tmp_ccom_word_batch_rollup;
CREATE TEMPORARY TABLE tmp_ccom_word_batch_rollup AS
SELECT
    p.batch_id,
    p.program_id,
    m.target_topic_id AS master_topic_id,
    MIN(p.id) AS source_id,
    MIN(p.taught_at) AS taught_at,
    MIN(p.created_at) AS created_at
FROM lms_batch_topic_progress p
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = p.master_topic_id
GROUP BY p.batch_id, p.program_id, m.target_topic_id;

INSERT INTO lms_batch_topic_progress
    (batch_id, program_id, master_topic_id, topic_id, taught_by_user_id, taught_at, notes, created_at)
SELECT r.batch_id, r.program_id, r.master_topic_id, NULL,
       src.taught_by_user_id, r.taught_at, src.notes, r.created_at
FROM tmp_ccom_word_batch_rollup r
JOIN lms_batch_topic_progress src ON src.id = r.source_id
WHERE NOT EXISTS (
    SELECT 1 FROM lms_batch_topic_progress existing
    WHERE existing.batch_id = r.batch_id
      AND existing.program_id = r.program_id
      AND existing.master_topic_id = r.master_topic_id
);

DELETE p FROM lms_batch_topic_progress p
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = p.master_topic_id;

UPDATE student_program_last_activity activity
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = activity.master_topic_id
SET activity.master_topic_id = m.target_topic_id,
    activity.updated_at = CURRENT_TIMESTAMP;

-- The table predates its logical one-row-per-student/program contract. If an
-- imported topic and its replacement both have last-activity rows, retain the
-- most recently updated row after remapping.
DROP TEMPORARY TABLE IF EXISTS tmp_ccom_word_activity_rank;
CREATE TEMPORARY TABLE tmp_ccom_word_activity_rank AS
SELECT id,
       ROW_NUMBER() OVER (
           PARTITION BY student_id, program_id
           ORDER BY updated_at DESC, id DESC
       ) AS row_rank
FROM student_program_last_activity
WHERE master_topic_id IN (351,27,28,30,37)
  AND EXISTS (
      SELECT 1 FROM backup_20260825_ccom_word_last_activity backed_up
      WHERE backed_up.student_id = student_program_last_activity.student_id
        AND backed_up.program_id = student_program_last_activity.program_id
        AND backed_up.master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052)
  );

DELETE activity
FROM student_program_last_activity activity
JOIN tmp_ccom_word_activity_rank ranked ON ranked.id = activity.id
WHERE ranked.row_rank > 1;

-- Imported lesson bodies are retained in the backup, not attached to old CCOM.
UPDATE lms_topic_contents content
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = content.master_topic_id
SET content.master_topic_id = NULL,
    content.updated_at = CURRENT_TIMESTAMP;

DELETE bridge FROM lms_master_topic_bridge bridge
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = bridge.master_topic_id;

DELETE topic FROM lms_master_topics topic
JOIN tmp_ccom_word_topic_map m ON m.source_topic_id = topic.id
WHERE topic.master_chapter_id = 5;

-- Renumber every chapter in the complete original CCOM program, not only Word.
DROP TEMPORARY TABLE IF EXISTS tmp_ccom_all_topic_order;
CREATE TEMPORARY TABLE tmp_ccom_all_topic_order AS
SELECT mt.id,
       ROW_NUMBER() OVER (
           PARTITION BY mt.master_chapter_id
           ORDER BY mt.topic_order, mt.id
       ) AS new_topic_order
FROM lms_master_topics mt
JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
WHERE pc.program_id = 1;

UPDATE lms_master_topics mt
JOIN tmp_ccom_all_topic_order ordered ON ordered.id = mt.id
SET mt.topic_order = ordered.new_topic_order,
    mt.updated_at = CURRENT_TIMESTAMP;

-- Verification result set. Expected: 14 topics, orders 1..14, no duplicates,
-- and zero live references to source IDs.
SELECT COUNT(*) AS remaining_word_topics,
       MIN(topic_order) AS first_order,
       MAX(topic_order) AS last_order,
       COUNT(DISTINCT topic_order) AS distinct_orders
FROM lms_master_topics WHERE master_chapter_id = 5;

SELECT pc.chapter_order, pc.master_chapter_id, mc.title,
       COUNT(mt.id) AS topic_count,
       MIN(mt.topic_order) AS first_order,
       MAX(mt.topic_order) AS last_order,
       COUNT(DISTINCT mt.topic_order) AS distinct_orders
FROM lms_program_chapters pc
JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
JOIN lms_master_topics mt ON mt.master_chapter_id = pc.master_chapter_id
WHERE pc.program_id = 1
GROUP BY pc.chapter_order, pc.master_chapter_id, mc.title
ORDER BY pc.chapter_order;

SELECT COUNT(*) AS remaining_source_progress
FROM lms_master_topic_progress WHERE master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052);

SELECT COUNT(*) AS remaining_source_batch_progress
FROM lms_batch_topic_progress WHERE master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052);

SELECT COUNT(*) AS remaining_source_last_activity
FROM student_program_last_activity WHERE master_topic_id IN (1045,1046,1047,1048,1049,1050,1051,1052);

COMMIT;
