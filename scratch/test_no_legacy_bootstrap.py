"""Regression check: application startup must not create legacy credentials/branches."""

from __future__ import annotations

import os
import tempfile

import db


with tempfile.TemporaryDirectory() as temp_dir:
    original_path = db.DB_PATH
    original_type = db.Config.DB_TYPE
    try:
        db.DB_PATH = os.path.join(temp_dir, "bootstrap.db")
        db.Config.DB_TYPE = "sqlite"

        # A restart must remain idempotent and must not create shared credentials.
        db.init_db()
        db.init_db()

        conn = db.get_conn()
        try:
            legacy_users = conn.execute(
                """SELECT COUNT(*) AS count
                   FROM users
                   WHERE username = 'admin' OR platform_role = 'platform_owner'"""
            ).fetchone()["count"]
            legacy_branches = conn.execute(
                """SELECT COUNT(*) AS count
                   FROM branches
                   WHERE branch_code IN ('HO', 'HB')"""
            ).fetchone()["count"]
        finally:
            conn.close()

        assert legacy_users == 0, "Startup created a shared administrator account"
        assert legacy_branches == 0, "Startup created legacy institute branches"
        print("legacy_bootstrap_disabled=OK")
    finally:
        db.DB_PATH = original_path
        db.Config.DB_TYPE = original_type
