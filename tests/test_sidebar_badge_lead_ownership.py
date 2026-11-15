"""Regression coverage for counsellor-scoped lead follow-up badges."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from flask import Flask, session

from modules.core import routes


@pytest.fixture
def badge_client(tmp_path, monkeypatch):
    database = tmp_path / "sidebar-badges.db"

    def connect():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        conn.create_function("parse_date", 1, lambda value: value)
        return conn

    conn = connect()
    conn.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            assigned_to_id INTEGER,
            status TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            next_followup_date TEXT
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            full_name TEXT,
            username TEXT
        );
        CREATE TABLE installment_plans (
            id INTEGER PRIMARY KEY, invoice_id INTEGER, status TEXT,
            due_date TEXT, amount_due REAL, amount_paid REAL
        );
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY, institute_id INTEGER, student_id INTEGER,
            branch_id INTEGER, status TEXT
        );
        CREATE TABLE students (
            id INTEGER PRIMARY KEY, institute_id INTEGER
        );
        CREATE TABLE leave_requests (
            id INTEGER PRIMARY KEY, student_id INTEGER, status TEXT
        );
        CREATE TABLE lms_final_exam_applications (
            id INTEGER PRIMARY KEY, institute_id INTEGER, status TEXT
        );
        CREATE TABLE student_profile_update_requests (
            id INTEGER PRIMARY KEY, institute_id INTEGER, student_id INTEGER,
            status TEXT
        );
        CREATE TABLE reminder_logs (
            id INTEGER PRIMARY KEY, institute_id INTEGER, installment_id INTEGER,
            status TEXT
        );
        """
    )
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=1)).isoformat()
    conn.executemany(
        "INSERT INTO users (id, institute_id, full_name, username) VALUES (?, ?, ?, ?)",
        [
            (22, 2, "Navi", "navi"),
            (23, 2, "Meghana", "meghana"),
            (24, 1, "Foreign User", "foreign"),
        ],
    )
    conn.executemany(
        """INSERT INTO leads
           (id, institute_id, assigned_to_id, status, is_deleted, next_followup_date)
           VALUES (?, ?, ?, 'active', 0, ?)""",
        [
            (1, 2, 23, today),
            (2, 2, 23, today),
            (3, 2, 22, future),
            (4, 1, 22, today),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(routes, "get_conn", connect)
    monkeypatch.setattr(
        routes,
        "get_current_institute_id",
        lambda default=None: session.get("institute_id", default),
    )

    app = Flask("sidebar-badge-ownership")
    app.config.update(TESTING=True, SECRET_KEY="isolated-sidebar-badge-test")
    app.register_blueprint(routes.core_bp)
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(
            user_id=22,
            institute_id=2,
            branch_id=2,
            role="staff",
            can_view_all_branches=1,
        )
    return client


def test_all_branch_staff_badge_excludes_other_counsellors_followups(badge_client):
    response = badge_client.get("/api/sidebar-badges")
    assert response.status_code == 200
    assert response.get_json()["leads"] == 0
    assert response.get_json()["lead_owners"] == []


def test_admin_badge_includes_all_due_followups_in_institute(badge_client):
    with badge_client.session_transaction() as state:
        state.update(role="admin")

    response = badge_client.get("/api/sidebar-badges")
    assert response.status_code == 200
    assert response.get_json()["leads"] == 2
    assert response.get_json()["lead_owners"] == [
        {"assigned_to_id": 23, "owner_name": "Meghana", "count": 2}
    ]


def test_base_template_has_escalating_user_scoped_followup_reminders():
    template = Path("templates/base.html").read_text(encoding="utf-8")
    assert 'id="leadFollowupReminderModal"' in template
    assert 'id="leadFollowupReminderToast"' in template
    assert 'id="leadFollowupOwnerBreakdown"' in template
    assert "erp_lead_followup_reminder_v3_{{ session.get(\"user_id\") }}" in template
    assert "leadReminderOneHour = 60 * 60 * 1000" in template
    assert "leadReminderThreeHours = 3 * leadReminderOneHour" in template
    assert "clearLeadReminderState()" in template
    assert "state.lastModalAt = now" in template
    assert "state.lastReminderAt = now" in template
    assert "showLeadFollowupReminder(data)" in template
    assert "url_for('leads.followups_today')" in template
