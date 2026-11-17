import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "manual-final-exam-schedule-test-only")

from services.final_exam_schedule import (
    apply_manual_schedule,
    has_manual_fee_override,
    preview_manual_schedule,
)


def database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE branches (id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT, is_active INTEGER);
        CREATE TABLE students (id INTEGER PRIMARY KEY, institute_id INTEGER, branch_id INTEGER, student_code TEXT,
          full_name TEXT, phone TEXT, date_of_birth TEXT, status TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, institute_id INTEGER, course_name TEXT);
        CREATE TABLE lms_programs (id INTEGER PRIMARY KEY, institute_id INTEGER, course_id INTEGER,
          program_name TEXT, is_active INTEGER, is_deleted INTEGER DEFAULT 0);
        CREATE TABLE lms_student_program_access (student_id INTEGER, program_id INTEGER, institute_id INTEGER,
          is_active INTEGER, access_status TEXT, access_end_date TEXT);
        CREATE TABLE lms_batch_program_access (batch_id INTEGER, program_id INTEGER, institute_id INTEGER,
          is_active INTEGER, access_end_date TEXT);
        CREATE TABLE student_batches (student_id INTEGER, batch_id INTEGER, status TEXT);
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, student_id INTEGER, institute_id INTEGER);
        CREATE TABLE invoice_items (invoice_id INTEGER, course_id INTEGER);
        CREATE TABLE lms_course_program_map (course_id INTEGER, program_id INTEGER);
        CREATE TABLE lms_program_chapters (program_id INTEGER, master_chapter_id INTEGER, is_visible INTEGER);
        CREATE TABLE lms_master_chapters (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE lms_question_bank (id INTEGER PRIMARY KEY, chapter_id INTEGER, institute_id INTEGER, is_shared INTEGER);
        CREATE TABLE lms_final_exam_applications (id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER, course_id INTEGER, verified_name TEXT, verified_phone TEXT, verified_dob TEXT,
          requested_exam_date TEXT, status TEXT, applied_on TEXT);
        CREATE TABLE lms_final_exam_attempts (id INTEGER PRIMARY KEY, student_id INTEGER,
          course_id INTEGER, application_id INTEGER);
        CREATE TABLE activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER, user_id INTEGER,
          branch_id INTEGER, action_type TEXT, module_name TEXT, record_id INTEGER, description TEXT, created_at TEXT);
        """
    )
    conn.execute("INSERT INTO branches VALUES (3, 1, 'College', 1)")
    conn.execute("INSERT INTO users VALUES (9)")
    conn.executemany(
        "INSERT INTO students VALUES (?, 1, 3, ?, ?, '9000000000', '2005-01-01', 'active')",
        [
            (1, "S1", "Create Student"),
            (2, "S2", "Reschedule Student"),
            (3, "S3", "No Questions Student"),
            (4, "S4", "No Program Student"),
            (5, "S5", "Attempted Student"),
        ],
    )
    conn.executemany("INSERT INTO courses VALUES (?, 1, ?)", [(10, "Course A"), (20, "Course B")])
    conn.executemany(
        "INSERT INTO lms_programs VALUES (?, 1, ?, ?, 1, 0)",
        [(100, 10, "Program A"), (200, 20, "Program B")],
    )
    conn.executemany(
        "INSERT INTO lms_student_program_access VALUES (?, ?, 1, 1, 'active', NULL)",
        [(1, 100), (2, 100), (3, 200), (5, 100)],
    )
    conn.executemany("INSERT INTO lms_program_chapters VALUES (?, ?, 1)", [(100, 1000), (200, 2000)])
    conn.executemany("INSERT INTO lms_master_chapters VALUES (?, 'active')", [(1000,), (2000,)])
    conn.executemany(
        "INSERT INTO lms_question_bank VALUES (?, 1000, 1, 0)",
        [(1,), (2,), (3,)],
    )
    conn.execute(
        """INSERT INTO lms_final_exam_applications
           (student_id, course_id, verified_name, verified_phone, verified_dob,
            requested_exam_date, status, applied_on)
           VALUES (2, 100, 'Reschedule Student', '9000000000', '2005-01-01',
                   '2026-11-20', 'PENDING', '2026-11-17T10:00:00')"""
    )
    attempted_app = conn.execute(
        """INSERT INTO lms_final_exam_applications
           (student_id, course_id, verified_name, verified_phone, verified_dob,
            requested_exam_date, status, applied_on)
           VALUES (5, 100, 'Attempted Student', '9000000000', '2005-01-01',
                   '2026-11-20', 'APPROVED', '2026-11-17T10:00:00')"""
    ).lastrowid
    conn.execute("INSERT INTO lms_final_exam_attempts VALUES (1, 5, 100, ?)", (attempted_app,))
    conn.commit()
    return conn


def test_preview_reports_create_reschedule_and_safe_skips():
    conn = database()
    preview = preview_manual_schedule(conn.cursor(), 1, 3)

    assert preview["student_count"] == 5
    assert preview["schedulable_count"] == 2
    assert preview["create_count"] == 1
    assert preview["reschedule_count"] == 1
    assert preview["attempted_count"] == 1
    assert preview["blocked_question_count"] == 1
    assert len(preview["students_without_program"]) == 1


def test_apply_schedules_and_audits_manual_fee_override():
    conn = database()
    preview, application_ids = apply_manual_schedule(conn, 1, 3, "2026-11-21", 9)
    conn.commit()

    assert preview["schedulable_count"] == 2
    assert len(application_ids) == 2
    applications = conn.execute(
        """SELECT student_id, requested_exam_date, status
           FROM lms_final_exam_applications WHERE student_id IN (1, 2) ORDER BY student_id"""
    ).fetchall()
    assert [tuple(row) for row in applications] == [
        (1, "2026-11-21", "APPROVED"),
        (2, "2026-11-21", "APPROVED"),
    ]
    for application_id in application_ids:
        student_id = conn.execute(
            "SELECT student_id FROM lms_final_exam_applications WHERE id = ?", (application_id,)
        ).fetchone()["student_id"]
        assert has_manual_fee_override(conn.cursor(), 1, student_id, application_id)


if __name__ == "__main__":
    test_preview_reports_create_reschedule_and_safe_skips()
    test_apply_schedules_and_audits_manual_fee_override()
