"""Cross-institute regression checks for the standard business dashboard."""

import os
import sqlite3
import sys
import tempfile

from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.core import routes


SCHEMA = """
CREATE TABLE receipts (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, receipt_date TEXT,
    amount_received REAL
);
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY, branch_id INTEGER, expense_date TEXT, amount REAL
);
CREATE TABLE students (
    id INTEGER PRIMARY KEY, institute_id INTEGER, full_name TEXT,
    student_code TEXT, phone TEXT, status TEXT, joined_date TEXT
);
CREATE TABLE leads (
    id INTEGER PRIMARY KEY, institute_id INTEGER, name TEXT, phone TEXT,
    next_followup_date TEXT, lead_score INTEGER, stage TEXT, status TEXT,
    is_deleted INTEGER, created_at TEXT, assigned_to_id INTEGER
);
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY, institute_id INTEGER, student_id INTEGER,
    invoice_no TEXT, branch_id INTEGER, status TEXT
);
CREATE TABLE installment_plans (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, due_date TEXT,
    amount_due REAL, amount_paid REAL, remarks TEXT, status TEXT
);
CREATE TABLE bad_debt_writeoffs (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, amount_written_off REAL
);
CREATE TABLE branches (
    id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT
);
CREATE TABLE batches (
    id INTEGER PRIMARY KEY, branch_id INTEGER, batch_name TEXT,
    course_id INTEGER, trainer_id INTEGER, start_time TEXT, end_time TEXT,
    start_date TEXT, end_date TEXT, status TEXT
);
CREATE TABLE attendance_records (
    id INTEGER PRIMARY KEY, batch_id INTEGER, attendance_date TEXT, status TEXT
);
CREATE TABLE student_batches (
    id INTEGER PRIMARY KEY, batch_id INTEGER, student_id INTEGER, status TEXT
);
CREATE TABLE activity_logs (
    id INTEGER PRIMARY KEY, institute_id INTEGER, user_id INTEGER,
    action_type TEXT, module_name TEXT, description TEXT, created_at TEXT
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY, institute_id INTEGER, full_name TEXT
);
CREATE TABLE leave_requests (
    id INTEGER PRIMARY KEY, student_id INTEGER, status TEXT
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.create_function("parse_date", 1, lambda value: value)
    return conn


def seed(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    month = routes.datetime.now().strftime("%Y-%m")
    today = routes.datetime.now().date().isoformat()
    conn.executemany(
        "INSERT INTO receipts VALUES (?, ?, ?, ?)",
        [(1, 1, f"{month}-01", 900), (2, 7, f"{month}-01", 100)],
    )
    conn.executemany(
        "INSERT INTO expenses VALUES (?, ?, ?, ?)",
        [(1, 1, f"{month}-01", 300), (2, 7, f"{month}-01", 25)],
    )
    conn.executemany(
        "INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "Other Student", "O1", "1", "active", f"{month}-01"),
            (7, 7, "Harsha Student", "H7", "7", "active", f"{month}-01"),
        ],
    )
    conn.executemany(
        "INSERT INTO leads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "Other Lead", "1", today, 10, "New Lead", "active", 0, today, 1),
            (7, 7, "Harsha Lead", "7", today, 20, "Interested", "active", 0, today, 7),
        ],
    )
    conn.executemany(
        "INSERT INTO bad_debt_writeoffs VALUES (?, ?, ?)",
        [(1, 1, 80), (7, 7, 5)],
    )
    conn.executemany(
        "INSERT INTO branches VALUES (?, ?, ?)",
        [(1, 1, "Other Branch"), (7, 7, "Harsha Branch")],
    )
    conn.executemany(
        "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, 1, 1, "OTHER-1", 1, "unpaid"),
            (7, 7, 7, "HARSHA-7", 7, "unpaid"),
        ],
    )
    conn.executemany(
        "INSERT INTO batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "Other Batch", None, 1, None, None, None, None, "active"),
            (7, 7, "Harsha Batch", None, 7, None, None, None, None, "active"),
        ],
    )
    conn.executemany(
        "INSERT INTO student_batches VALUES (?, ?, ?, ?)",
        [(1, 1, 1, "active"), (7, 7, 7, "active")],
    )
    conn.executemany(
        "INSERT INTO attendance_records VALUES (?, ?, ?, ?)",
        [(1, 1, today, "absent"), (7, 7, today, "present")],
    )
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, ?)",
        [(1, 1, "Other Admin"), (7, 7, "Harsha Admin")],
    )
    conn.executemany(
        "INSERT INTO activity_logs VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, 1, "create", "leads", "Other activity", today),
            (7, 7, 7, "create", "leads", "Harsha activity", today),
        ],
    )
    conn.executemany(
        "INSERT INTO leave_requests VALUES (?, ?, ?)",
        [(1, 1, "pending"), (7, 7, "pending")],
    )
    conn.commit()
    conn.close()


def dashboard_for(app, institute_id, database_path):
    original_get_conn = routes.get_conn
    original_get_institute = routes.get_current_institute_id
    original_render = routes.render_template
    try:
        routes.get_conn = lambda: connect(database_path)
        routes.get_current_institute_id = lambda default=None: institute_id
        routes.render_template = lambda template, **values: {
            "_template": template,
            **values,
        }
        with app.test_request_context("/dashboard"):
            session.update(
                user_id=institute_id,
                institute_id=institute_id,
                username=f"admin-{institute_id}",
                role="admin",
            )
            return routes.dashboard()
    finally:
        routes.get_conn = original_get_conn
        routes.get_current_institute_id = original_get_institute
        routes.render_template = original_render


def main():
    app = Flask(__name__)
    app.secret_key = "dashboard-tenant-isolation-regression"
    handle, database_path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    try:
        seed(database_path)
        harsha = dashboard_for(app, 7, database_path)
        other = dashboard_for(app, 1, database_path)

        assert harsha["_template"] == "core/dashboard_new.html"
        assert harsha["revenue_this_month"] == 100
        assert harsha["expenses_this_month"] == 25
        assert harsha["active_students"] == 1
        assert harsha["active_leads"] == 1
        assert harsha["total_bad_debt"] == 5
        assert harsha["att_present"] == 1
        assert harsha["att_absent"] == 0
        assert harsha["active_batches"] == 1
        assert harsha["recent_activity"][0]["description"] == "Harsha activity"
        assert harsha["pending_leave_count"] == 1

        assert other["revenue_this_month"] == 900
        assert other["expenses_this_month"] == 300
        assert other["total_bad_debt"] == 80
        assert other["att_present"] == 0
        assert other["att_absent"] == 1
        assert other["recent_activity"][0]["description"] == "Other activity"
    finally:
        os.remove(database_path)

    print("Dashboard cross-institute isolation checks passed.")


if __name__ == "__main__":
    main()
