"""Attendance KPIs use one current student/batch roster for numerator and denominator."""


def get_attendance_summary(conn, institute_id, day, trainer_id=None):
    trainer_clause = ' AND b.trainer_id = ?' if trainer_id is not None else ''
    roster_params = [institute_id, institute_id, day, day]
    if trainer_id is not None:
        roster_params.append(trainer_id)
    rows = conn.execute(f"""
        SELECT ar.status, COUNT(*) AS cnt
        FROM (
            SELECT DISTINCT sb.student_id, sb.batch_id
            FROM student_batches sb
            JOIN batches b ON b.id = sb.batch_id
            JOIN branches br ON br.id = b.branch_id
            JOIN students s ON s.id = sb.student_id AND s.institute_id = ?
            WHERE br.institute_id = ? AND b.status = 'active' AND sb.status = 'active'
              AND (b.start_date IS NULL OR DATE(b.start_date) <= DATE(?))
              AND (b.end_date IS NULL OR DATE(b.end_date) >= DATE(?))
              {trainer_clause}
        ) roster
        LEFT JOIN attendance_records ar ON ar.id = (
            SELECT MAX(latest.id) FROM attendance_records latest
            WHERE latest.student_id = roster.student_id AND latest.batch_id = roster.batch_id
              AND latest.attendance_date = ?
        )
        GROUP BY ar.status
    """, [*roster_params, day]).fetchall()
    expected = sum(int(row['cnt']) for row in rows)
    counts = {status: 0 for status in ('present', 'late', 'absent', 'leave')}
    for row in rows:
        if row['status'] in counts:
            counts[row['status']] = int(row['cnt'])
    marked = sum(counts.values())
    outside_params = [institute_id, institute_id, day, day, day]
    if trainer_id is not None:
        outside_params.append(trainer_id)
    outside = conn.execute(f"""
        SELECT COUNT(*) AS cnt FROM attendance_records ar
        JOIN batches b ON b.id = ar.batch_id
        JOIN branches br ON br.id = b.branch_id
        JOIN students s ON s.id = ar.student_id AND s.institute_id = ?
        WHERE br.institute_id = ? AND ar.attendance_date = ? AND b.status = 'active'
          AND (b.start_date IS NULL OR DATE(b.start_date) <= DATE(?))
          AND (b.end_date IS NULL OR DATE(b.end_date) >= DATE(?))
          {trainer_clause}
          AND ar.status IN ('present', 'late', 'absent', 'leave')
          AND ar.id = (SELECT MAX(latest.id) FROM attendance_records latest
                       WHERE latest.student_id = ar.student_id AND latest.batch_id = ar.batch_id
                         AND latest.attendance_date = ar.attendance_date)
          AND NOT EXISTS (SELECT 1 FROM student_batches sb WHERE sb.student_id = ar.student_id
                          AND sb.batch_id = ar.batch_id AND sb.status = 'active')
    """, outside_params).fetchone()['cnt']
    return dict(counts=counts, expected=expected, marked=marked, pending=expected-marked,
                percentage=round(marked / expected * 100, 1) if expected else None,
                outside_roster=int(outside))
