"""Cross-institute regression checks for the billing dashboard."""

import os
import sqlite3
import sys
import tempfile
from datetime import date

from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.billing import routes


SCHEMA = """
CREATE TABLE branches (
    id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT,
    is_active INTEGER
);
CREATE TABLE students (
    id INTEGER PRIMARY KEY, institute_id INTEGER, branch_id INTEGER,
    created_at TEXT
);
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY, student_id INTEGER, branch_id INTEGER,
    invoice_date TEXT, total_amount REAL
);
CREATE TABLE receipts (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, receipt_date TEXT,
    amount_received REAL
);
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY, branch_id INTEGER, expense_date TEXT,
    amount REAL
);
CREATE TABLE installment_plans (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, due_date TEXT,
    amount_due REAL, amount_paid REAL, status TEXT
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
    today = date.today().isoformat()
    conn.executemany(
        "INSERT INTO branches VALUES (?, ?, ?, ?)",
        [(1, 1, "Institute One", 1), (7, 7, "Institute Seven", 1)],
    )
    conn.executemany(
        "INSERT INTO students VALUES (?, ?, ?, ?)",
        [(1, 1, 1, today), (7, 7, 7, today)],
    )
    conn.executemany(
        "INSERT INTO invoices VALUES (?, ?, ?, ?, ?)",
        [(1, 1, 1, today, 1000), (7, 7, 7, today, 7000)],
    )
    conn.executemany(
        "INSERT INTO receipts VALUES (?, ?, ?, ?)",
        [(1, 1, today, 400), (7, 7, today, 2800)],
    )
    conn.executemany(
        "INSERT INTO expenses VALUES (?, ?, ?, ?)",
        [(1, 1, today, 100), (7, 7, today, 700)],
    )
    conn.executemany(
        "INSERT INTO installment_plans VALUES (?, ?, ?, ?, ?, ?)",
        [(1, 1, today, 1000, 400, "partially_paid"),
         (7, 7, today, 7000, 2800, "partially_paid")],
    )
    conn.commit()
    conn.close()


def dashboard_for(app, institute_id, database_path, query_string=""):
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
        path = "/billing/dashboard"
        if query_string:
            path += f"?{query_string}"
        with app.test_request_context(path):
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


def assert_totals(result, *, students, invoices, sales, receipts, expenses, receivables):
    assert result["_template"] == "billing/dashboard.html"
    assert result["total_students"] == students
    assert result["total_invoices"] == invoices
    assert result["total_sales"] == sales
    assert result["total_receipts"] == receipts
    assert result["total_expenses"] == expenses
    assert result["total_receivables"] == receivables
    assert sum(result["sales_data"]) == sales
    assert sum(result["receipts_data"]) == receipts
    assert sum(result["expenses_data"]) == expenses


def main():
    app = Flask(__name__)
    app.secret_key = "billing-dashboard-tenant-isolation-regression"
    handle, database_path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    try:
        seed(database_path)
        institute_one = dashboard_for(app, 1, database_path)
        institute_seven = dashboard_for(app, 7, database_path)
        institute_seven_branch = dashboard_for(
            app, 7, database_path, query_string="branch_id=7"
        )
        foreign_branch = dashboard_for(
            app, 7, database_path, query_string="branch_id=1"
        )

        assert_totals(
            institute_one,
            students=1, invoices=1, sales=1000,
            receipts=400, expenses=100, receivables=600,
        )
        assert_totals(
            institute_seven,
            students=1, invoices=1, sales=7000,
            receipts=2800, expenses=700, receivables=4200,
        )
        assert_totals(
            institute_seven_branch,
            students=1, invoices=1, sales=7000,
            receipts=2800, expenses=700, receivables=4200,
        )
        assert_totals(
            foreign_branch,
            students=0, invoices=0, sales=0,
            receipts=0, expenses=0, receivables=0,
        )
        assert [row["id"] for row in institute_seven["branches"]] == [7]
    finally:
        os.remove(database_path)

    print("Billing dashboard cross-institute isolation checks passed.")


if __name__ == "__main__":
    main()
