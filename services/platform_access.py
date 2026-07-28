"""Platform account and audited tenant-support session helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import current_app, request, session
from werkzeug.security import generate_password_hash


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def close_support_session(conn, reason="exited"):
    support_session_id = session.get("support_session_id")
    platform_account_id = session.get("platform_account_id")
    if support_session_id and platform_account_id:
        conn.execute(
            """UPDATE platform_support_sessions
               SET ended_at = ?, end_reason = ?, last_activity_at = ?
               WHERE id = ? AND platform_account_id = ? AND ended_at IS NULL""",
            (
                now_text(),
                reason[:120],
                now_text(),
                support_session_id,
                platform_account_id,
            ),
        )


def clear_tenant_support_state():
    for key in (
        "support_session_id",
        "support_institute_name",
        "user_id",
        "institute_id",
        "membership_role",
        "branch_id",
        "can_view_all_branches",
    ):
        session.pop(key, None)
    if session.get("platform_account_id"):
        session["role"] = "platform_owner"
        session["platform_role"] = "platform_owner"


def _support_actor(conn, platform_account, institute_id):
    username = f"__platform_support_{int(platform_account['id'])}"
    actor = conn.execute(
        """SELECT * FROM users
           WHERE institute_id = ? AND username = ?""",
        (institute_id, username),
    ).fetchone()
    now = now_text()
    if actor:
        conn.execute(
            """UPDATE users SET full_name = ?, role = 'admin',
                   platform_role = 'platform_support_actor', branch_id = NULL,
                   can_view_all_branches = 1, is_active = 1, updated_at = ?
               WHERE id = ? AND institute_id = ?""",
            (
                f"Platform Support — {platform_account['full_name']}",
                now,
                actor["id"],
                institute_id,
            ),
        )
        return int(actor["id"])

    cursor = conn.execute(
        """INSERT INTO users (
               institute_id, full_name, username, password_hash, role,
               platform_role, branch_id, can_view_all_branches, is_active,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, 'admin', 'platform_support_actor',
                     NULL, 1, 1, ?, ?)""",
        (
            institute_id,
            f"Platform Support — {platform_account['full_name']}",
            username,
            generate_password_hash(secrets.token_urlsafe(48)),
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def start_support_session(conn, platform_account, institute, reason):
    close_support_session(conn, "replaced")
    clear_tenant_support_state()
    now = datetime.now()
    expires = now + timedelta(
        minutes=current_app.config["PLATFORM_SUPPORT_SESSION_MINUTES"]
    )
    support_user_id = _support_actor(conn, platform_account, institute["id"])
    cursor = conn.execute(
        """INSERT INTO platform_support_sessions (
               platform_account_id, institute_id, support_user_id, reason,
               started_at, expires_at, last_activity_at, request_ip, user_agent
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            platform_account["id"],
            institute["id"],
            support_user_id,
            reason,
            now.isoformat(timespec="seconds"),
            expires.isoformat(timespec="seconds"),
            now.isoformat(timespec="seconds"),
            (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64],
            (request.user_agent.string or "")[:500],
        ),
    )
    session["support_session_id"] = int(cursor.lastrowid)
    session["support_institute_name"] = institute["name"]
    session["user_id"] = support_user_id
    session["institute_id"] = int(institute["id"])
    session["role"] = "admin"
    session["platform_role"] = "platform_owner"
    session["membership_role"] = "platform_support"
    session["branch_id"] = None
    session["can_view_all_branches"] = 1


def validate_support_session(conn):
    support_session_id = session.get("support_session_id")
    platform_account_id = session.get("platform_account_id")
    if not support_session_id or not platform_account_id:
        return None
    row = conn.execute(
        """SELECT ps.*, i.name AS institute_name, i.status AS institute_status
           FROM platform_support_sessions ps
           JOIN institutes i ON i.id = ps.institute_id
           WHERE ps.id = ? AND ps.platform_account_id = ?
             AND ps.ended_at IS NULL AND ps.expires_at > ?""",
        (support_session_id, platform_account_id, now_text()),
    ).fetchone()
    if not row:
        return None
    if int(session.get("institute_id") or 0) != int(row["institute_id"]):
        return None
    conn.execute(
        "UPDATE platform_support_sessions SET last_activity_at = ? WHERE id = ?",
        (now_text(), support_session_id),
    )
    return row
