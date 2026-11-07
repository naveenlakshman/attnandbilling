"""Regression checks for institute isolation in the student demo portal."""

import sqlite3
import sys
from pathlib import Path

from flask import Flask, session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.students import routes as student_routes


def _database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE lms_programs (
            id INTEGER PRIMARY KEY,
            course_id INTEGER,
            program_name TEXT,
            program_reference_name TEXT,
            description TEXT,
            is_active INTEGER,
            is_deleted INTEGER,
            is_published INTEGER,
            institute_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE lms_course_program_map (program_id INTEGER, course_id INTEGER);
        CREATE TABLE lms_program_chapters (
            program_id INTEGER, master_chapter_id INTEGER,
            is_visible INTEGER, chapter_order INTEGER
        );
        CREATE TABLE lms_master_chapters (id INTEGER, status TEXT);
        CREATE TABLE lms_master_topics (
            id INTEGER, master_chapter_id INTEGER, status TEXT, topic_order INTEGER
        );
        CREATE TABLE lms_chapters (
            id INTEGER, program_id INTEGER, is_active INTEGER, chapter_order INTEGER
        );
        CREATE TABLE lms_topics (
            id INTEGER, chapter_id INTEGER, is_active INTEGER, topic_order INTEGER
        );

        INSERT INTO lms_programs VALUES
            (11, 101, 'Tenant One', 'Course A', '', 1, 0, 1, 1,
             '2026-08-13 10:00:00', '2026-08-13 10:00:00'),
            (22, 202, 'Tenant Two', 'Course B', '', 1, 0, 1, 2,
             '2026-08-13 11:00:00', '2026-08-13 11:00:00');
        """
    )
    return conn


def test_demo_dashboard_and_direct_access_are_tenant_scoped():
    app = Flask(__name__)
    app.secret_key = "demo-tenant-test"
    conn = _database()
    captured = {}

    original_get_conn = student_routes.get_conn
    original_company = student_routes.get_company_profile
    original_render = student_routes.render_template
    original_institute = student_routes.get_current_institute_id
    try:
        student_routes.get_conn = lambda: conn
        student_routes.get_company_profile = lambda: {}
        student_routes.get_current_institute_id = lambda default=None: 2

        def capture_template(template, **context):
            captured.update(context)
            return template

        student_routes.render_template = capture_template

        with app.test_request_context("/student/dashboard"):
            session["student_id"] = 0
            session["demo_mode"] = True
            session["institute_id"] = 2

            assert not student_routes._has_program_access(conn, 11, 0)
            assert student_routes._has_program_access(conn, 22, 0)

            result = student_routes.dashboard.__wrapped__()

            assert result == "students/dashboard.html"
            assert [program["id"] for program in captured["programs"]] == [22]
    finally:
        student_routes.get_conn = original_get_conn
        student_routes.get_company_profile = original_company
        student_routes.render_template = original_render
        student_routes.get_current_institute_id = original_institute
        try:
            conn.close()
        except sqlite3.ProgrammingError:
            pass


if __name__ == "__main__":
    test_demo_dashboard_and_direct_access_are_tenant_scoped()
    print("PASS: student demo dashboard and direct access are institute-isolated.")
