"""Read classroom teaching completion for several batches without per-batch queries."""


def batch_syllabus_progress(conn, institute_id, batch_ids):
    batch_ids = sorted(set(batch_ids))
    if not batch_ids:
        return {}
    placeholders = ','.join('?' for _ in batch_ids)
    programs = conn.execute(f"""
        SELECT DISTINCT b.id AS batch_id, lp.id AS program_id
        FROM batches b
        JOIN branches br ON br.id = b.branch_id AND br.institute_id = ?
        LEFT JOIN courses c ON c.id = b.course_id AND c.institute_id = ?
        JOIN lms_programs lp ON lp.institute_id = ?
          AND lp.is_active = 1 AND lp.is_deleted = 0
        WHERE b.id IN ({placeholders}) AND (
            lp.course_id = c.id
            OR EXISTS (SELECT 1 FROM lms_course_program_map cpm
                       WHERE cpm.program_id = lp.id AND cpm.course_id = c.id)
            OR EXISTS (SELECT 1 FROM lms_batch_program_access bpa
                       WHERE bpa.program_id = lp.id AND bpa.batch_id = b.id AND bpa.is_active = 1)
        )
    """, [institute_id, institute_id, institute_id, *batch_ids]).fetchall()
    summaries = {bid: {'total_topics': 0, 'completed_topics': 0, 'percent': 0.0} for bid in batch_ids}
    program_ids = sorted({row['program_id'] for row in programs})
    if not program_ids:
        return summaries

    program_placeholders = ','.join('?' for _ in program_ids)
    topics = conn.execute(f"""
        SELECT DISTINCT pc.program_id, mt.id AS topic_id, 'master' AS topic_type
        FROM lms_program_chapters pc
        JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id AND mc.status = 'active'
        JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id AND mt.status = 'active'
        WHERE pc.program_id IN ({program_placeholders}) AND pc.is_visible = 1
        UNION ALL
        SELECT DISTINCT lc.program_id, lt.id AS topic_id, 'legacy' AS topic_type
        FROM lms_chapters lc
        JOIN lms_topics lt ON lt.chapter_id = lc.id AND lt.is_active = 1
        WHERE lc.program_id IN ({program_placeholders}) AND lc.is_active = 1
          AND NOT EXISTS (
              SELECT 1 FROM lms_program_chapters pc
              JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id AND mc.status = 'active'
              JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id AND mt.status = 'active'
              WHERE pc.program_id = lc.program_id AND pc.is_visible = 1
          )
    """, [*program_ids, *program_ids]).fetchall()
    progress = conn.execute(f"""
        SELECT batch_id, program_id, master_topic_id, topic_id
        FROM lms_batch_topic_progress
        WHERE batch_id IN ({placeholders}) AND program_id IN ({program_placeholders})
    """, [*batch_ids, *program_ids]).fetchall()
    taught = set()
    for row in progress:
        if row['master_topic_id'] is not None:
            taught.add((row['batch_id'], row['program_id'], 'master', row['master_topic_id']))
        if row['topic_id'] is not None:
            taught.add((row['batch_id'], row['program_id'], 'legacy', row['topic_id']))
    topics_by_program = {}
    for row in topics:
        topics_by_program.setdefault(row['program_id'], set()).add((row['topic_type'], row['topic_id']))
    for row in programs:
        bid, pid = row['batch_id'], row['program_id']
        syllabus = topics_by_program.get(pid, set())
        summaries[bid]['total_topics'] += len(syllabus)
        summaries[bid]['completed_topics'] += sum((bid, pid, kind, tid) in taught for kind, tid in syllabus)
    for summary in summaries.values():
        total = summary['total_topics']
        if total:
            summary['percent'] = round(summary['completed_topics'] / total * 100, 1)
    return summaries
