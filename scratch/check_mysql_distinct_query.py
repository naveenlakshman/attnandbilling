from db import get_conn


conn = get_conn()
try:
    rows = conn.execute(
        """
        SELECT DISTINCT
               s.id, s.student_id, s.original_filename, s.feedback,
               s.status, s.review_status, s.rejection_reason,
               s.submitted_at,
               strftime('%d %b %Y %H:%M', s.submitted_at) AS submitted_date,
               strftime('%d %b %Y %H:%M', s.reviewed_at) AS reviewed_date,
               st.full_name AS student_name, st.student_code
        FROM lms_assignment_submissions s
        JOIN students st ON st.id = s.student_id
        JOIN student_batches sb ON sb.student_id = s.student_id
        JOIN batches b ON b.id = sb.batch_id
        WHERE s.is_latest = 1
        ORDER BY s.submitted_at DESC
        LIMIT 5
        """
    ).fetchall()
    print(f"mysql_distinct_query=OK rows={len(rows)}")
finally:
    conn.close()
