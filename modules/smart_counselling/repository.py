import json

from .state_machine import OPEN_STATUSES


SESSION_SELECT = """
    SELECT cs.id, cs.institute_id, cs.branch_id, cs.lead_id,
           cs.counsellor_user_id, cs.status, cs.mobile_verified,
           cs.verification_method, cs.verified_mobile_normalized,
           cs.identity_mobile_normalized, cs.identification_status,
           cs.primary_interested_course_id, cs.secondary_interested_course_id,
           cs.outcome, cs.outcome_reason, cs.next_action, cs.next_followup_date,
           cs.staff_notes, cs.completion_followup_id,
           cs.started_at, cs.completed_at,
           cs.abandoned_at, cs.created_at, cs.updated_at,
           b.branch_name,
           u.full_name AS counsellor_name,
           l.name AS lead_name,
           l.assigned_to_id AS lead_assigned_to_id
    FROM counselling_sessions cs
    JOIN branches b
      ON b.id = cs.branch_id AND b.institute_id = cs.institute_id
    JOIN users u
      ON u.id = cs.counsellor_user_id AND u.institute_id = cs.institute_id
    LEFT JOIN leads l
      ON l.id = cs.lead_id AND l.institute_id = cs.institute_id
"""


def _dict(row):
    return dict(row) if row is not None else None


def insert_session(conn, *, institute_id, branch_id, counsellor_user_id, now):
    cursor = conn.execute(
        """
        INSERT INTO counselling_sessions (
            institute_id, branch_id, lead_id, counsellor_user_id, status,
            mobile_verified, verification_method, started_at, created_at, updated_at
        ) VALUES (?, ?, NULL, ?, 'IDENTIFICATION_PENDING', 0, NULL, ?, ?, ?)
        """,
        (institute_id, branch_id, counsellor_user_id, now, now, now),
    )
    return int(cursor.lastrowid)


def get_session(conn, institute_id, session_id):
    row = conn.execute(
        SESSION_SELECT + " WHERE cs.id = ? AND cs.institute_id = ? LIMIT 1",
        (int(session_id), int(institute_id)),
    ).fetchone()
    return _dict(row)


def list_open_sessions(conn, actor, limit=25):
    placeholders = ", ".join("?" for _ in OPEN_STATUSES)
    conditions = ["cs.institute_id = ?", f"cs.status IN ({placeholders})"]
    params = [actor.institute_id, *OPEN_STATUSES]
    if not actor.can_view_all_branches:
        conditions.append("cs.branch_id = ?")
        params.append(actor.branch_id)
    if actor.role == "staff":
        conditions.append("cs.counsellor_user_id = ?")
        params.append(actor.id)
    params.append(max(1, min(int(limit), 100)))
    rows = conn.execute(
        SESSION_SELECT
        + " WHERE " + " AND ".join(conditions)
        + " ORDER BY cs.updated_at DESC, cs.id DESC LIMIT ?",
        tuple(params),
    ).fetchall()
    return [_dict(row) for row in rows]


def list_recent_sessions(conn, actor, limit=10):
    conditions = ["cs.institute_id = ?"]
    params = [actor.institute_id]
    if not actor.can_view_all_branches:
        conditions.append("cs.branch_id = ?")
        params.append(actor.branch_id)
    if actor.role == "staff":
        conditions.append("cs.counsellor_user_id = ?")
        params.append(actor.id)
    params.append(max(1, min(int(limit), 50)))
    rows = conn.execute(
        SESSION_SELECT
        + " WHERE " + " AND ".join(conditions)
        + " ORDER BY cs.updated_at DESC, cs.id DESC LIMIT ?",
        tuple(params),
    ).fetchall()
    return [_dict(row) for row in rows]


def dashboard_metrics(conn, actor, today):
    conditions = ["institute_id = ?"]
    scope_params = [actor.institute_id]
    if not actor.can_view_all_branches:
        conditions.append("branch_id = ?")
        scope_params.append(actor.branch_id)
    if actor.role == "staff":
        conditions.append("counsellor_user_id = ?")
        scope_params.append(actor.id)
    open_placeholders = ", ".join("?" for _ in OPEN_STATUSES)
    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN DATE(started_at) = ? THEN 1 ELSE 0 END), 0) AS today_sessions,
            COALESCE(SUM(CASE WHEN lead_id IS NULL AND status IN ({open_placeholders}) THEN 1 ELSE 0 END), 0) AS unlinked_sessions,
            COALESCE(SUM(CASE WHEN status = 'COMPLETED' AND DATE(completed_at) = ? THEN 1 ELSE 0 END), 0) AS completed_sessions,
            COALESCE(SUM(CASE WHEN status IN ({open_placeholders}) THEN 1 ELSE 0 END), 0) AS open_sessions
        FROM counselling_sessions
        WHERE {" AND ".join(conditions)}
        """,
        tuple([today, *OPEN_STATUSES, today, *OPEN_STATUSES, *scope_params]),
    ).fetchone()
    return {
        "todaySessions": int(row["today_sessions"] or 0),
        "newUnlinkedSessions": int(row["unlinked_sessions"] or 0),
        "completedSessions": int(row["completed_sessions"] or 0),
        "openSessions": int(row["open_sessions"] or 0),
        "readyForAdmission": None,
    }


def update_session_status(conn, session_id, institute_id, target_status, now, *, abandon_reason=None):
    completed_at = now if target_status == "COMPLETED" else None
    abandoned_at = now if target_status == "ABANDONED" else None
    conn.execute(
        """
        UPDATE counselling_sessions
        SET status = ?, completed_at = COALESCE(?, completed_at),
            abandoned_at = COALESCE(?, abandoned_at),
            abandon_reason = COALESCE(?, abandon_reason), updated_at = ?
        WHERE id = ? AND institute_id = ?
        """,
        (target_status, completed_at, abandoned_at, abandon_reason, now, session_id, institute_id),
    )


def insert_event(conn, *, institute_id, session_id, lead_id, actor_user_id, event_type, metadata, now):
    safe_metadata = json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True)
    conn.execute(
        """
        INSERT INTO counselling_events (
            institute_id, counselling_session_id, lead_id, actor_user_id,
            event_type, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (institute_id, session_id, lead_id, actor_user_id, event_type, safe_metadata, now),
    )
