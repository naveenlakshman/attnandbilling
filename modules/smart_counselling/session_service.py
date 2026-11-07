from datetime import datetime, timezone

from db import get_conn

from .authorization import authorize_session, resolve_start_branch
from .dto import dashboard_session_dto, session_dto
from .errors import SmartCounsellingError, validation_error
from .repository import (
    dashboard_metrics,
    get_session,
    insert_event,
    insert_session,
    list_open_sessions,
    list_recent_sessions,
    update_session_status,
)
from .state_machine import ABANDONED, COMPLETED, TERMINAL_STATUSES, require_transition


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _rollback(conn):
    conn.rollback()


def create_counselling_session(actor, requested_branch_id=None):
    conn = get_conn()
    now = _now()
    try:
        branch = resolve_start_branch(conn, actor, requested_branch_id)
        session_id = insert_session(
            conn,
            institute_id=actor.institute_id,
            branch_id=int(branch["id"]),
            counsellor_user_id=actor.id,
            now=now,
        )
        insert_event(
            conn,
            institute_id=actor.institute_id,
            session_id=session_id,
            lead_id=None,
            actor_user_id=actor.id,
            event_type="session_started",
            metadata={"initialStatus": "IDENTIFICATION_PENDING"},
            now=now,
        )
        created = get_session(conn, actor.institute_id, session_id)
        conn.commit()
        return session_dto(authorize_session(actor, created))
    except Exception:
        _rollback(conn)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_counselling_session(actor, session_id):
    conn = get_conn()
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        return session_dto(row)
    finally:
        conn.close()


def list_resumable_sessions(actor, limit=25):
    conn = get_conn()
    try:
        return [session_dto(row) for row in list_open_sessions(conn, actor, limit)]
    finally:
        conn.close()


def resume_counselling_session(actor, session_id):
    conn = get_conn()
    now = _now()
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        if row["status"] in TERMINAL_STATUSES:
            code = "session_completed" if row["status"] == COMPLETED else "invalid_transition"
            raise SmartCounsellingError(code, "This counselling session cannot be resumed.", 409)
        insert_event(
            conn,
            institute_id=actor.institute_id,
            session_id=int(row["id"]),
            lead_id=row.get("lead_id"),
            actor_user_id=actor.id,
            event_type="session_resumed",
            metadata={"status": row["status"]},
            now=now,
        )
        conn.execute(
            "UPDATE counselling_sessions SET updated_at = ? WHERE id = ? AND institute_id = ?",
            (now, int(row["id"]), actor.institute_id),
        )
        refreshed = get_session(conn, actor.institute_id, session_id)
        conn.commit()
        return session_dto(refreshed)
    except Exception:
        _rollback(conn)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def transition_counselling_session(actor, session_id, target_status, *, reason=None):
    conn = get_conn()
    now = _now()
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        require_transition(row["status"], target_status)
        update_session_status(
            conn,
            int(row["id"]),
            actor.institute_id,
            target_status,
            now,
            abandon_reason=reason if target_status == ABANDONED else None,
        )
        event_type = {
            ABANDONED: "session_abandoned",
            COMPLETED: "session_completed",
        }.get(target_status, "session_status_changed")
        insert_event(
            conn,
            institute_id=actor.institute_id,
            session_id=int(row["id"]),
            lead_id=row.get("lead_id"),
            actor_user_id=actor.id,
            event_type=event_type,
            metadata={
                "fromStatus": row["status"],
                "toStatus": target_status,
                "reasonProvided": bool(reason),
            },
            now=now,
        )
        refreshed = get_session(conn, actor.institute_id, session_id)
        conn.commit()
        return session_dto(refreshed)
    except Exception:
        _rollback(conn)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def abandon_counselling_session(actor, session_id, reason=None):
    clean_reason = (reason or "").strip()
    if len(clean_reason) > 255:
        raise validation_error(
            "Abandonment reason is too long.",
            {"reason": "Use 255 characters or fewer."},
        )
    return transition_counselling_session(
        actor,
        session_id,
        ABANDONED,
        reason=clean_reason or None,
    )


def counselling_dashboard(actor, today):
    conn = get_conn()
    try:
        metrics = dashboard_metrics(conn, actor, today)
        recent = [dashboard_session_dto(row) for row in list_recent_sessions(conn, actor, 10)]
        return {"metrics": metrics, "recentSessions": recent}
    finally:
        conn.close()
