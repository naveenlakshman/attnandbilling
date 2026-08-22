from datetime import datetime, timezone

from modules.leads.helpers import can_access_lead

from .authorization import authorize_session
from .errors import SmartCounsellingError
from .phone import mask_mobile, try_normalize_indian_mobile
from .repository import get_session, insert_event
from .state_machine import IDENTIFICATION_PENDING, IDENTIFIED, require_transition
from db import get_conn


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _require_admin_resolution(actor, session):
    if actor.role != "admin":
        raise SmartCounsellingError(
            "forbidden", "Only an administrator can resolve an unverified identity.", 403
        )
    if (
        session["status"] != IDENTIFICATION_PENDING
        or session.get("verification_method") != "OVERRIDE"
        or session.get("identification_status") != "UNVERIFIED_MATCH_REQUIRES_CONFIRMATION"
        or not session.get("identity_mobile_normalized")
    ):
        raise SmartCounsellingError(
            "resolution_not_available",
            "This counselling session does not require CRM identity resolution.",
            409,
        )


def _matching_candidates(conn, actor, mobile):
    rows = conn.execute(
        """
        SELECT l.id, l.name, l.phone, l.stage, l.status, l.is_deleted,
               l.assigned_to_id, l.branch_id, l.created_at,
               b.branch_name, u.full_name AS assigned_to_name,
               s.id AS student_id, s.student_code
        FROM leads l
        LEFT JOIN branches b
          ON b.id = l.branch_id AND b.institute_id = l.institute_id
        LEFT JOIN users u
          ON u.id = l.assigned_to_id AND u.institute_id = l.institute_id
        LEFT JOIN students s
          ON s.lead_id = l.id AND s.institute_id = l.institute_id
        WHERE l.institute_id = ?
        ORDER BY l.id
        """,
        (actor.institute_id,),
    ).fetchall()
    candidates = []
    for raw in rows:
        row = dict(raw)
        if try_normalize_indian_mobile(row.get("phone")) != mobile:
            continue
        if not actor.can_view_all_branches and int(row.get("branch_id") or 0) != int(actor.branch_id or 0):
            continue
        if not can_access_lead(actor.id, actor.role, row.get("assigned_to_id")):
            continue
        candidates.append(row)
    return candidates


def _candidate_dto(row):
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "Prospect",
        "mobileMasked": mask_mobile(try_normalize_indian_mobile(row.get("phone"))),
        "stage": row.get("stage"),
        "status": row.get("status"),
        "branch": row.get("branch_name"),
        "assignedCounsellor": row.get("assigned_to_name"),
        "studentCode": row.get("student_code"),
        "archived": bool(row.get("is_deleted")),
        "viewUrl": f"/leads/{int(row['id'])}",
    }


def get_identity_resolution(actor, session_id):
    conn = get_conn()
    try:
        session = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        _require_admin_resolution(actor, session)
        candidates = _matching_candidates(conn, actor, session["identity_mobile_normalized"])
        return {
            "sessionId": int(session["id"]),
            "mobileMasked": mask_mobile(session["identity_mobile_normalized"]),
            "candidates": [_candidate_dto(row) for row in candidates],
        }
    finally:
        conn.close()


def confirm_identity_resolution(actor, session_id, lead_id):
    try:
        lead_id = int(lead_id)
    except (TypeError, ValueError):
        raise SmartCounsellingError("validation_error", "Choose a valid CRM record.", 400)

    conn = get_conn()
    now = _now()
    try:
        session = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        _require_admin_resolution(actor, session)
        candidates = _matching_candidates(conn, actor, session["identity_mobile_normalized"])
        selected = next((row for row in candidates if int(row["id"]) == lead_id), None)
        if not selected or selected.get("is_deleted"):
            raise SmartCounsellingError(
                "resolution_candidate_invalid",
                "The selected active CRM record is not available for this session.",
                409,
            )

        status = (
            "EXISTING_STUDENT"
            if selected.get("student_id") or str(selected.get("status") or "").lower() == "converted"
            else "EXISTING_LEAD"
        )
        require_transition(session["status"], IDENTIFIED)
        conn.execute(
            """
            UPDATE counselling_sessions
            SET lead_id = ?, identification_status = ?, status = 'IDENTIFIED', updated_at = ?
            WHERE id = ? AND institute_id = ? AND status = 'IDENTIFICATION_PENDING'
            """,
            (lead_id, status, now, session_id, actor.institute_id),
        )
        insert_event(
            conn,
            institute_id=actor.institute_id,
            session_id=session_id,
            lead_id=lead_id,
            actor_user_id=actor.id,
            event_type="identity_match_confirmed",
            metadata={"verificationMethod": "ADMIN_REVIEW"},
            now=now,
        )
        insert_event(
            conn,
            institute_id=actor.institute_id,
            session_id=session_id,
            lead_id=lead_id,
            actor_user_id=actor.id,
            event_type="lead_linked",
            metadata={"source": "identity_resolution"},
            now=now,
        )
        conn.commit()
        lead = _candidate_dto(selected)
        return {
            "verification": {
                "verified": False,
                "method": "OVERRIDE",
                "mobileMasked": mask_mobile(session["identity_mobile_normalized"]),
            },
            "prospect": {"status": status, "lead": lead, "matches": []},
            "nextStep": "PROFILE" if status == "EXISTING_LEAD" else "RESOLUTION",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
