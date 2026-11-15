"""Regression coverage for completing a partially written-off invoice."""

import sqlite3
from pathlib import Path

import pytest
from flask import Flask

from modules.baddebt import routes


@pytest.fixture
def writeoff_app(tmp_path, monkeypatch):
    database = tmp_path / "multiple-writeoffs.db"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        return conn

    conn = connect()
    conn.executescript(
        """
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            invoice_no TEXT NOT NULL,
            total_amount REAL NOT NULL,
            student_id INTEGER NOT NULL,
            branch_id INTEGER,
            status TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE students (
            id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            student_code TEXT NOT NULL,
            full_name TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE receipts (
            id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            amount_received REAL NOT NULL
        );
        CREATE TABLE bad_debt_writeoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER NOT NULL,
            reference_no TEXT,
            invoice_id INTEGER NOT NULL,
            amount_written_off REAL NOT NULL,
            paid_amount REAL,
            reason TEXT,
            student_status_at_writeoff TEXT,
            authorized_by INTEGER,
            writeoff_date TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE institute_settings (
            institute_id INTEGER PRIMARY KEY,
            invoice_prefix TEXT
        );
        CREATE TABLE expense_categories (
            id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            category_name TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """INSERT INTO students
           (id, institute_id, student_code, full_name, status)
           VALUES (452, 2, '1516688', 'Sukanya S G', 'dropped')"""
    )
    conn.execute(
        """INSERT INTO invoices
           (id, institute_id, invoice_no, total_amount, student_id, branch_id, status)
           VALUES (453, 2, 'GIT/B/453', 15300, 452, 2, 'partially_written_off')"""
    )
    conn.executemany(
        "INSERT INTO receipts (id, institute_id, invoice_id, amount_received) VALUES (?, ?, 453, ?)",
        [(1, 2, 5000), (2, 1, 1000)],
    )
    conn.executemany(
        """INSERT INTO bad_debt_writeoffs
           (id, institute_id, reference_no, invoice_id, amount_written_off,
            paid_amount, reason, student_status_at_writeoff)
           VALUES (?, ?, ?, 453, ?, 5000, 'Student Dropped', 'dropped')""",
        [(1, 2, 'GIT/WO/001', 7225), (2, 1, 'FOREIGN/WO/001', 9999)],
    )
    conn.execute(
        "INSERT INTO institute_settings (institute_id, invoice_prefix) VALUES (2, 'GIT/B')"
    )
    conn.commit()
    conn.close()

    rendered = {}

    def fake_render(template, **context):
        rendered.update(template=template, **context)
        return "rendered"

    monkeypatch.setattr(routes, "get_conn", connect)
    monkeypatch.setattr(routes, "get_current_institute_id", lambda default=None: 2)
    monkeypatch.setattr(routes, "render_template", fake_render)
    monkeypatch.setattr(routes, "allocate_document_number", lambda *args: "GIT/WO/002")
    monkeypatch.setattr(routes, "log_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "_sync_invoice_installments", lambda *args: None)
    monkeypatch.setattr(routes.Config, "DB_TYPE", "sqlite")

    app = Flask("multiple-writeoffs")
    app.config.update(TESTING=True, SECRET_KEY="multiple-writeoffs-test")
    app.register_blueprint(routes.baddebt_bp, url_prefix="/baddebt")
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=7, institute_id=2, branch_id=2, role="admin")

    return client, connect, rendered


def test_partially_written_off_invoice_is_selectable_with_actual_balance(writeoff_app):
    client, _connect, rendered = writeoff_app

    response = client.get("/baddebt/create?invoice_id=453")

    assert response.status_code == 200
    assert rendered["template"] == "baddebt/create.html"
    assert rendered["pre_selected_invoice"]["id"] == 453
    assert len(rendered["invoices"]) == 1
    invoice = rendered["invoices"][0]
    assert float(invoice["paid_amount"]) == 5000
    assert float(invoice["written_off_amount"]) == 7225
    assert float(invoice["total_amount"] - invoice["paid_amount"] - invoice["written_off_amount"]) == 3075


def test_second_writeoff_can_close_exact_remaining_balance(writeoff_app):
    client, connect, _rendered = writeoff_app

    response = client.post(
        "/baddebt/create",
        data={
            "invoice_id": "453",
            "amount_written_off": "3075.00",
            "reason": "Student Dropped",
            "student_status": "dropped",
            "notes": "Remaining balance after course drop",
        },
    )

    assert response.status_code == 302
    conn = connect()
    invoice = conn.execute(
        "SELECT status FROM invoices WHERE id = 453 AND institute_id = 2"
    ).fetchone()
    total = conn.execute(
        """SELECT SUM(amount_written_off) AS total
           FROM bad_debt_writeoffs
           WHERE invoice_id = 453 AND institute_id = 2"""
    ).fetchone()
    latest = conn.execute(
        """SELECT amount_written_off, reference_no
           FROM bad_debt_writeoffs
           WHERE invoice_id = 453 AND institute_id = 2
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    conn.close()

    assert invoice["status"] == "write_off"
    assert float(total["total"]) == 10300
    assert float(latest["amount_written_off"]) == 3075
    assert latest["reference_no"] == "GIT/WO/002"


def test_second_writeoff_cannot_exceed_actual_remaining_balance(writeoff_app):
    client, connect, _rendered = writeoff_app

    response = client.post(
        "/baddebt/create",
        data={
            "invoice_id": "453",
            "amount_written_off": "3075.01",
            "reason": "Student Dropped",
            "student_status": "dropped",
        },
    )

    assert response.status_code == 302
    conn = connect()
    invoice = conn.execute(
        "SELECT status FROM invoices WHERE id = 453 AND institute_id = 2"
    ).fetchone()
    count = conn.execute(
        """SELECT COUNT(*) AS count
           FROM bad_debt_writeoffs
           WHERE invoice_id = 453 AND institute_id = 2"""
    ).fetchone()
    conn.close()

    assert invoice["status"] == "partially_written_off"
    assert count["count"] == 1


def test_writeoff_ui_uses_remaining_balance_after_prior_writeoffs():
    create_template = Path("templates/baddebt/create.html").read_text(encoding="utf-8")
    invoice_template = Path("templates/billing/invoice_view.html").read_text(encoding="utf-8")

    assert 'data-written-off="{{ inv.written_off_amount }}"' in create_template
    assert 'data-balance="{{ inv.total_amount - inv.paid_amount - inv.written_off_amount }}"' in create_template
    assert "parseFloat(option.dataset.balance)" in create_template
    assert "'partially_written_off']" in invoice_template
