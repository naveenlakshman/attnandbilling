"""Regression checks for platform-only identity and audited tenant switching."""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, session

from services.platform_access import (
    clear_tenant_support_state,
    close_support_session,
    start_support_session,
    validate_support_session,
)


class Connection:
    def __init__(self):
        self.raw = sqlite3.connect(":memory:")
        self.raw.row_factory = sqlite3.Row

    def execute(self, sql, args=()):
        return self.raw.execute(sql, args)


def main():
    conn = Connection()
    conn.raw.executescript(
        """
        CREATE TABLE institutes (
            id INTEGER PRIMARY KEY, name TEXT, status TEXT
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institute_id INTEGER, full_name TEXT, username TEXT,
            password_hash TEXT, role TEXT, platform_role TEXT,
            branch_id INTEGER, can_view_all_branches INTEGER,
            is_active INTEGER, created_at TEXT, updated_at TEXT,
            UNIQUE(institute_id, username)
        );
        CREATE TABLE platform_support_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_account_id INTEGER, institute_id INTEGER,
            support_user_id INTEGER, reason TEXT, started_at TEXT,
            expires_at TEXT, last_activity_at TEXT, ended_at TEXT,
            end_reason TEXT, request_ip TEXT, user_agent TEXT
        );
        INSERT INTO institutes VALUES (7, 'Tenant Seven', 'active');
        """
    )
    app = Flask(__name__)
    app.secret_key = "test-only-platform-separation"
    app.config["PLATFORM_SUPPORT_SESSION_MINUTES"] = 60
    account = {"id": 3, "full_name": "Platform Owner"}
    institute = {"id": 7, "name": "Tenant Seven"}

    with app.test_request_context("/platform/institutes/7", headers={"User-Agent": "test"}):
        session["platform_account_id"] = 3
        session["platform_role"] = "platform_owner"
        start_support_session(
            conn, account, institute, "Investigating tenant configuration"
        )
        assert session["institute_id"] == 7
        assert session["support_session_id"]
        assert session["membership_role"] == "platform_support"
        support = validate_support_session(conn)
        assert support and support["institute_id"] == 7
        actor = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        assert actor["platform_role"] == "platform_support_actor"
        close_support_session(conn, "test_exit")
        clear_tenant_support_state()
        assert "user_id" not in session and "institute_id" not in session
        assert session["platform_account_id"] == 3
        audit = conn.execute(
            "SELECT * FROM platform_support_sessions"
        ).fetchone()
        assert audit["ended_at"] and audit["end_reason"] == "test_exit"

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sidebar = open(
        os.path.join(root, "templates", "includes", "sidebar_master.html"),
        encoding="utf-8",
    ).read()
    assert "not is_platform_owner or session.get('support_session_id')" in sidebar
    bootstrap = open(os.path.join(root, "db.py"), encoding="utf-8").read()
    assert "SET platform_role = 'platform_owner'" not in bootstrap
    print("Platform identity separation and support-session checks passed.")


if __name__ == "__main__":
    main()
