import sqlite3
from pathlib import Path

from modules.exams import routes as exam_routes
from modules.exams.routes import (
    _final_exam_assignment_check,
    _final_exam_assignment_override,
)


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE lms_program_chapters (
            program_id INTEGER NOT NULL,
            master_chapter_id INTEGER NOT NULL,
            custom_title TEXT,
            chapter_order INTEGER NOT NULL,
            is_visible INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE lms_master_chapters (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE lms_master_topics (
            id INTEGER PRIMARY KEY,
            master_chapter_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            topic_order INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE lms_assignments (
            id INTEGER PRIMARY KEY,
            master_topic_id INTEGER NOT NULL,
            title TEXT NOT NULL
        );
        CREATE TABLE lms_assignment_submissions (
            id INTEGER PRIMARY KEY,
            assignment_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status TEXT,
            review_status TEXT,
            is_latest INTEGER NOT NULL DEFAULT 1,
            submitted_at TEXT
        );
        CREATE TABLE lms_final_exam_applications (
            id INTEGER PRIMARY KEY,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            applied_on TEXT NOT NULL
        );

        INSERT INTO lms_master_chapters VALUES (10, 'Excel Fundamentals', 'active');
        INSERT INTO lms_master_chapters VALUES (20, 'Other Program', 'active');
        INSERT INTO lms_program_chapters VALUES (7, 10, 'Spreadsheet Skills', 1, 1);
        INSERT INTO lms_program_chapters VALUES (8, 20, NULL, 1, 1);
        INSERT INTO lms_master_topics VALUES (101, 10, 'Formulas', 1, 'active');
        INSERT INTO lms_master_topics VALUES (102, 10, 'Charts', 2, 'active');
        INSERT INTO lms_master_topics VALUES (201, 20, 'Unrelated Topic', 1, 'active');
        INSERT INTO lms_assignments VALUES (1001, 101, 'Formula Practice');
        INSERT INTO lms_assignments VALUES (1002, 101, 'Lookup Functions');
        INSERT INTO lms_assignments VALUES (1003, 102, 'Build a Dashboard');
        INSERT INTO lms_assignments VALUES (2001, 201, 'Other Program Work');

        INSERT INTO lms_assignment_submissions
            VALUES (1, 1001, 50, 'submitted', 'accepted', 1, '2026-11-10 10:00:00');
        INSERT INTO lms_assignment_submissions
            VALUES (2, 1002, 50, 'submitted', 'rejected', 1, '2026-11-11 10:00:00');
        INSERT INTO lms_assignment_submissions
            VALUES (3, 1003, 99, 'submitted', 'accepted', 1, '2026-11-12 10:00:00');
        """
    )
    return conn


def test_final_exam_check_lists_actionable_assignments_by_topic():
    conn = _connection()
    try:
        result = _final_exam_assignment_check(conn.cursor(), student_id=50, program_id=7)
    finally:
        conn.close()

    assert result["total"] == 3
    assert result["submitted"] == 1
    assert result["missing"] == 2
    assert result["passed"] is False
    assert [item["assignment_id"] for item in result["pending"]] == [1002, 1003]
    assert result["pending"][0] == {
        "assignment_id": 1002,
        "assignment_title": "Lookup Functions",
        "master_topic_id": 101,
        "topic_title": "Formulas",
        "chapter_title": "Spreadsheet Skills",
        "chapter_order": 1,
        "topic_order": 1,
        "submission_status": "rejected",
        "action_label": "Needs resubmission",
    }
    assert result["pending"][1]["topic_title"] == "Charts"
    assert result["pending"][1]["action_label"] == "Not submitted"


def test_final_exam_check_treats_awaiting_review_as_submitted():
    conn = _connection()
    try:
        conn.execute(
            """
            INSERT INTO lms_assignment_submissions
                VALUES (4, 1003, 50, 'submitted', 'submitted', 1, '2026-11-13 10:00:00')
            """
        )
        result = _final_exam_assignment_check(conn.cursor(), student_id=50, program_id=7)
    finally:
        conn.close()

    assert result["submitted"] == 2
    assert result["missing"] == 1
    assert [item["assignment_id"] for item in result["pending"]] == [1002]


def test_pending_assignment_link_opens_the_assignment_tab():
    root = Path(__file__).resolve().parents[1]
    exam_template = (root / "templates" / "exams" / "student_final_exam_apply.html").read_text(
        encoding="utf-8"
    )
    topic_template = (root / "templates" / "students" / "topic.html").read_text(encoding="utf-8")

    assert "tab='assignments'" in exam_template
    assert "new URLSearchParams(window.location.search).get('tab')" in topic_template
    assert "requestedTab === 'assignments'" in topic_template


def test_pending_assignments_are_advisory_for_exam_application(monkeypatch):
    monkeypatch.setattr(
        exam_routes,
        "_final_exam_syllabus_check",
        lambda cur, student_id, program_id: {"passed": True},
    )
    monkeypatch.setattr(
        exam_routes,
        "_final_exam_assignment_check",
        lambda cur, student_id, program_id: {"passed": False, "missing": 2},
    )
    monkeypatch.setattr(
        exam_routes,
        "_final_exam_dues_check",
        lambda cur, student_id: {"passed": True},
    )
    monkeypatch.setattr(
        exam_routes,
        "_final_exam_profile_check",
        lambda cur, student_id: {"passed": True},
    )

    checks = exam_routes._final_exam_checks(None, student_id=50, program_id=7)

    assert checks["application_ready"] is True
    assert checks["all_passed"] is False


def test_staff_approval_creates_assignment_or_project_override():
    conn = _connection()
    try:
        assert _final_exam_assignment_override(conn.cursor(), student_id=50, program_id=7) is False
        conn.execute(
            """
            INSERT INTO lms_final_exam_applications
                VALUES (1, 50, 7, 'APPROVED', '2026-11-16 10:00:00')
            """
        )
        assert _final_exam_assignment_override(conn.cursor(), student_id=50, program_id=7) is True
        assert _final_exam_assignment_override(conn.cursor(), student_id=50, program_id=8) is False
    finally:
        conn.close()


def test_staff_review_and_certificate_views_explain_the_exception():
    root = Path(__file__).resolve().parents[1]
    applications = (root / "templates" / "exams" / "admin_final_exam_applications.html").read_text(
        encoding="utf-8"
    )
    result = (root / "templates" / "exams" / "admin_final_exam_result.html").read_text(
        encoding="utf-8"
    )
    certificate = (root / "templates" / "certificates" / "admin_issue.html").read_text(
        encoding="utf-8"
    )

    assert "Assignments / Projects" in applications
    assert "review project evidence" in applications
    assert "pending assignment(s)" in applications
    assert "Staff-approved project exception" in result
    assert "Staff-approved project exception" in certificate
