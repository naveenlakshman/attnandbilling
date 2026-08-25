-- Read-only verification for the complete CCOM cleanup and batch 85.
SELECT b.id, b.batch_name, b.course_id, c.course_name
FROM batches b
JOIN courses c ON c.id = b.course_id
WHERE b.id = 85;

SELECT pc.program_id, pc.chapter_order, pc.master_chapter_id, mc.title,
       COUNT(mt.id) AS topic_count,
       MIN(mt.topic_order) AS first_order,
       MAX(mt.topic_order) AS last_order,
       COUNT(DISTINCT mt.topic_order) AS distinct_orders
FROM lms_program_chapters pc
JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
WHERE pc.program_id = 1
GROUP BY pc.program_id, pc.chapter_order, pc.master_chapter_id, mc.title;

SELECT mt.id, mt.topic_order, mt.title
FROM lms_master_topics mt
WHERE mt.master_chapter_id = 5
ORDER BY mt.topic_order, mt.id;

SELECT topic_order, COUNT(*) AS duplicate_count
FROM lms_master_topics mt
JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
WHERE pc.program_id = 1
GROUP BY mt.master_chapter_id, topic_order
HAVING COUNT(*) > 1;

SELECT pc.program_id, lp.program_name, pc.master_chapter_id
FROM lms_program_chapters pc
JOIN lms_programs lp ON lp.id = pc.program_id
WHERE pc.master_chapter_id = 5
ORDER BY pc.program_id;
