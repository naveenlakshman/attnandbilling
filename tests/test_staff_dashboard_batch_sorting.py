import sqlite3
import pytest

def test_staff_dashboard_my_batches_sorting_by_start_time():
    """Verify that batches in staff dashboard are ordered chronologically by start_time ASC."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE branches (id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, course_name TEXT);
        CREATE TABLE batches (
            id INTEGER PRIMARY KEY,
            batch_name TEXT,
            course_id INTEGER,
            branch_id INTEGER,
            trainer_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            status TEXT
        );
        CREATE TABLE student_batches (
            id INTEGER PRIMARY KEY,
            batch_id INTEGER,
            student_id INTEGER,
            status TEXT
        );
    """)

    cur.execute("INSERT INTO branches VALUES (1, 10, 'Main Branch')")
    cur.execute("INSERT INTO courses VALUES (100, 'Python Bootcamp')")

    # Insert batches out of chronological order
    # Batch A: 14:00 (Afternoon)
    # Batch B: 09:00 (Morning)
    # Batch C: 11:30 (Mid-day)
    # Batch D: NULL start time
    cur.execute("INSERT INTO batches VALUES (1, 'Afternoon Batch', 100, 1, 5, '14:00', '16:00', 'active')")
    cur.execute("INSERT INTO batches VALUES (2, 'Morning Batch', 100, 1, 5, '09:00', '11:00', 'active')")
    cur.execute("INSERT INTO batches VALUES (3, 'Midday Batch', 100, 1, 5, '11:30', '13:30', 'active')")
    cur.execute("INSERT INTO batches VALUES (4, 'Unscheduled Batch', 100, 1, 5, NULL, NULL, 'active')")

    conn.commit()

    institute_id = 10
    user_id = 5

    cur.execute("""
        SELECT b.id, b.batch_name, b.start_time, b.end_time, b.status,
               c.course_name, br.branch_name,
               COUNT(sb.id) AS student_count
        FROM batches b
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN branches br ON b.branch_id = br.id
        LEFT JOIN student_batches sb ON sb.batch_id = b.id AND sb.status = 'active'
        WHERE br.institute_id = ? AND b.trainer_id = ? AND b.status = 'active'
        GROUP BY b.id
        ORDER BY CASE WHEN b.start_time IS NULL OR b.start_time = '' THEN 1 ELSE 0 END, b.start_time ASC, b.batch_name ASC
    """, [institute_id, user_id])

    rows = cur.fetchall()
    conn.close()

    batch_names = [row["batch_name"] for row in rows]
    start_times = [row["start_time"] for row in rows]

    assert batch_names == ['Morning Batch', 'Midday Batch', 'Afternoon Batch', 'Unscheduled Batch']
    assert start_times == ['09:00', '11:30', '14:00', None]
