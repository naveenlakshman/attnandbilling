from modules.leads.helpers import can_access_lead

from .errors import SmartCounsellingError, validation_error


def resolve_start_branch(conn, actor, requested_branch_id=None):
    branch_id = requested_branch_id
    if not actor.can_view_all_branches:
        if requested_branch_id is not None and int(requested_branch_id) != int(actor.branch_id or 0):
            raise SmartCounsellingError(
                "branch_forbidden",
                "You cannot start counselling for this branch.",
                403,
            )
        branch_id = actor.branch_id
    elif branch_id is None:
        branch_id = actor.branch_id

    if not branch_id:
        raise validation_error(
            "Choose an active branch before starting counselling.",
            {"branchId": "An active branch is required."},
        )

    branch = conn.execute(
        """
        SELECT id, branch_name
        FROM branches
        WHERE id = ? AND institute_id = ? AND is_active = 1
        LIMIT 1
        """,
        (int(branch_id), actor.institute_id),
    ).fetchone()
    if not branch:
        raise SmartCounsellingError(
            "branch_forbidden",
            "The selected branch is not available for this institute.",
            403,
        )
    return branch


def authorize_session(actor, counselling_session):
    if not counselling_session:
        raise SmartCounsellingError("not_found", "Counselling session was not found.", 404)

    if int(counselling_session["institute_id"]) != actor.institute_id:
        raise SmartCounsellingError("not_found", "Counselling session was not found.", 404)

    if not actor.can_view_all_branches and int(counselling_session["branch_id"]) != int(actor.branch_id or 0):
        raise SmartCounsellingError(
            "branch_forbidden",
            "You do not have access to this counselling session's branch.",
            403,
        )

    if actor.role == "staff" and int(counselling_session["counsellor_user_id"]) != actor.id:
        raise SmartCounsellingError(
            "forbidden",
            "You do not have access to this counselling session.",
            403,
        )

    lead_id = counselling_session.get("lead_id")
    if lead_id and not can_access_lead(actor.id, actor.role, counselling_session.get("lead_assigned_to_id")):
        raise SmartCounsellingError(
            "forbidden",
            "The linked lead is assigned to another counsellor.",
            403,
        )
    return counselling_session


def require_session_mutable(counselling_session):
    if counselling_session.get("status") in {"COMPLETED", "ABANDONED"}:
        raise SmartCounsellingError(
            "session_completed",
            "A completed counselling session cannot be changed.",
            409,
        )
    return counselling_session
