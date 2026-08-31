import sqlite3
import pytest

def test_staff_dashboard_my_batches_sorting_and_labels():
    """Verify that batches in staff dashboard are ordered chronologically and calculate attendance % & taught status."""
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
        CREATE TABLE attendance_records (
            id INTEGER PRIMARY KEY,
            batch_id INTEGER,
            student_id INTEGER,
            attendance_date TEXT,
            status TEXT
        );
        CREATE TABLE lms_batch_topic_progress (
            id INTEGER PRIMARY KEY,
            batch_id INTEGER,
            program_id INTEGER,
            master_topic_id INTEGER,
            topic_id INTEGER,
            taught_by_user_id INTEGER,
            taught_at TEXT
        );
    """)

    today = "2026-08-31"
    cur.execute("INSERT INTO branches VALUES (1, 10, 'Main Branch')")
    cur.execute("INSERT INTO courses VALUES (100, 'Python Bootcamp')")

    # Insert batches
    # Batch 1: Afternoon (2 students, 1 marked -> 50% attendance)
    cur.execute("INSERT INTO batches VALUES (1, 'Afternoon Batch', 100, 1, 5, '14:00', '16:00', 'active')")
    cur.execute("INSERT INTO student_batches VALUES (1, 1, 101, 'active')")
    cur.execute("INSERT INTO student_batches VALUES (2, 1, 102, 'active')")
    cur.execute("INSERT INTO attendance_records VALUES (1, 1, 101, ?, 'present')", (today,))

    # Batch 2: Morning (2 students, 2 marked -> 100% attendance, class taught)
    cur.execute("INSERT INTO batches VALUES (2, 'Morning Batch', 100, 1, 5, '09:00', '11:00', 'active')")
    cur.execute("INSERT INTO student_batches VALUES (3, 2, 201, 'active')")
    cur.execute("INSERT INTO student_batches VALUES (4, 2, 202, 'active')")
    cur.execute("INSERT INTO attendance_records VALUES (2, 2, 201, ?, 'present')", (today,))
    cur.execute("INSERT INTO attendance_records VALUES (3, 2, 202, ?, 'present')", (today,))
    cur.execute("INSERT INTO lms_batch_topic_progress VALUES (1, 2, 1, 1, NULL, 5, ?)", (today + " 10:00:00",))

    # Batch 3: Midday (1 student, 0 marked -> 0% attendance)
    cur.execute("INSERT INTO batches VALUES (3, 'Midday Batch', 100, 1, 5, '11:30', '13:30', 'active')")
    cur.execute("INSERT INTO student_batches VALUES (5, 3, 301, 'active')")

    # Batch 4: Unscheduled (0 students)
    cur.execute("INSERT INTO batches VALUES (4, 'Unscheduled Batch', 100, 1, 5, NULL, NULL, 'active')")

    conn.commit()

    institute_id = 10
    user_id = 5

    cur.execute("""
        SELECT b.id, b.batch_name, b.start_time, b.end_time, b.status,
               c.course_name, br.branch_name,
               (SELECT COUNT(DISTINCT sb.student_id)
                FROM student_batches sb
                WHERE sb.batch_id = b.id AND sb.status = 'active') AS student_count,
               (SELECT COUNT(DISTINCT ar.student_id)
                FROM attendance_records ar
                WHERE ar.batch_id = b.id AND ar.attendance_date = ?) AS att_today_count
        FROM batches b
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN branches br ON b.branch_id = br.id
        WHERE br.institute_id = ? AND b.trainer_id = ? AND b.status = 'active'
        GROUP BY b.id
        ORDER BY CASE WHEN b.start_time IS NULL OR b.start_time = '' THEN 1 ELSE 0 END, b.start_time ASC, b.batch_name ASC
    """, [today, institute_id, user_id])

    raw_batches = cur.fetchall()

    cur.execute("SELECT DISTINCT batch_id FROM lms_batch_topic_progress WHERE date(taught_at) = ?", (today,))
    taught_batch_ids = {r["batch_id"] for r in cur.fetchall()}

    my_batches = []
    for b in raw_batches:
        b_dict = dict(b)
        student_count = b_dict.get("student_count") or 0
        att_today_count = b_dict.get("att_today_count") or 0
        b_dict["student_count"] = student_count
        b_dict["att_today_count"] = att_today_count

        if student_count > 0:
            att_pct = int(round((att_today_count / student_count) * 100))
        else:
            att_pct = 0
        b_dict["attendance_pct"] = att_pct
        b_dict["is_attendance_full"] = (att_today_count >= student_count and student_count > 0)
        b_dict["class_taught_today"] = b_dict["id"] in taught_batch_ids
        my_batches.append(b_dict)

    conn.close()

    batch_names = [row["batch_name"] for row in my_batches]
    assert batch_names == ['Morning Batch', 'Midday Batch', 'Afternoon Batch', 'Unscheduled Batch']

    # Morning batch: 100% attendance, class taught
    mb = my_batches[0]
    assert mb["is_attendance_full"] is True
    assert mb["attendance_pct"] == 100
    assert mb["class_taught_today"] is True

    # Midday batch: 0% attendance, class not taught
    midb = my_batches[1]
    assert midb["is_attendance_full"] is False
    assert midb["attendance_pct"] == 0
    assert midb["class_taught_today"] is False

    # Afternoon batch: 50% attendance (1/2 students marked), class not taught
    ab = my_batches[2]
    assert ab["is_attendance_full"] is False
    assert ab["attendance_pct"] == 50
    assert ab["class_taught_today"] is False
