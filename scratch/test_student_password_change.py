"""Regression checks for student password confirmation and change history."""

import os
import sqlite3
import sys
import tempfile

from flask import Flask, session
from werkzeug.security import check_password_hash, generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.students import routes


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def call_change_password(app, database_path, form_data):
    original_get_conn = routes.get_conn
    original_company = routes.get_company_profile
    original_institute = routes.get_current_institute_id
    original_demo = routes._is_demo
    try:
        routes.get_conn = lambda: connect(database_path)
        routes.get_company_profile = lambda: {"company_name": "Institute Seven"}
        routes.get_current_institute_id = lambda default=None: 7
        routes._is_demo = lambda: False
        with app.test_request_context(
            "/student/change-password",
            method="POST",
            data=form_data,
        ):
            session.update(
                student_id=7,
                student_name="Student Seven",
                student_code="S7",
                institute_id=7,
            )
            return routes.change_password()
    finally:
        routes.get_conn = original_get_conn
        routes.get_company_profile = original_company
        routes.get_current_institute_id = original_institute
        routes._is_demo = original_demo


def main():
    app = Flask(__name__)
    app.secret_key = "student-password-change-regression"
    app.register_blueprint(routes.students_bp)
    handle, database_path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    try:
        conn = connect(database_path)
        conn.execute(
            """
            CREATE TABLE students (
                id INTEGER PRIMARY KEY,
                institute_id INTEGER NOT NULL,
                student_code TEXT NOT NULL,
                password_hash TEXT,
                password_changed_at TEXT,
                status TEXT,
                portal_enabled INTEGER
            )
            """
        )
        old_hash = generate_password_hash("Current@123")
        conn.executemany(
            "INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (7, 7, "S7", old_hash, None, "active", 1),
                (8, 8, "S8", old_hash, None, "active", 1),
            ],
        )
        conn.commit()
        conn.close()

        mismatch_response = call_change_password(
            app,
            database_path,
            {
                "current_password": "Current@123",
                "new_password": "Changed@123",
                "confirm_password": "Different@123",
            },
        )
        assert mismatch_response.status_code == 302
        conn = connect(database_path)
        unchanged = conn.execute(
            "SELECT password_hash, password_changed_at FROM students WHERE id = 7"
        ).fetchone()
        assert check_password_hash(unchanged["password_hash"], "Current@123")
        assert unchanged["password_changed_at"] is None
        conn.close()

        success_response = call_change_password(
            app,
            database_path,
            {
                "current_password": "Current@123",
                "new_password": "Changed@123",
                "confirm_password": "Changed@123",
            },
        )
        assert success_response.status_code == 302
        conn = connect(database_path)
        changed = conn.execute(
            "SELECT password_hash, password_changed_at FROM students WHERE id = 7"
        ).fetchone()
        other = conn.execute(
            "SELECT password_hash, password_changed_at FROM students WHERE id = 8"
        ).fetchone()
        conn.close()

        assert check_password_hash(changed["password_hash"], "Changed@123")
        assert changed["password_changed_at"]
        assert check_password_hash(other["password_hash"], "Current@123")
        assert other["password_changed_at"] is None

        template = open(
            "templates/students/change_password.html", encoding="utf-8"
        ).read()
        assert "Passwords match." in template
        assert "do not match." in template
        assert "Last password change:" in template
        assert "changeButton.disabled = !passwordsMatch" in template
    finally:
        os.remove(database_path)

    print("Student password confirmation and history checks passed.")


if __name__ == "__main__":
    main()
