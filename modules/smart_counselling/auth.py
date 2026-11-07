from functools import wraps
from dataclasses import dataclass

from flask import g, jsonify, session

from db import get_conn
from services.subscriptions import SubscriptionAccessDenied, assert_feature_enabled
from services.tenant_context import require_tenant


def error_response(code, message, status, fields=None):
    return jsonify({
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "fields": fields or {}},
    }), status


@dataclass(frozen=True)
class SmartCounsellingActor:
    id: int
    institute_id: int
    role: str
    branch_id: int | None
    can_view_all_branches: bool
    username: str
    full_name: str


def current_actor():
    return getattr(g, "smart_counselling_actor", None)


def smart_counselling_staff_required(route_function):
    """Validate the existing Flask staff session for Smart Counselling APIs."""

    @wraps(route_function)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return error_response("unauthorized", "Please sign in to continue.", 401)

        tenant = require_tenant()
        session_institute_id = session.get("institute_id")
        if not session_institute_id or int(session_institute_id) != int(tenant.institute_id):
            return error_response(
                "forbidden",
                "Your institute session is no longer valid. Please sign in again.",
                403,
            )

        conn = get_conn()
        try:
            user = conn.execute(
                """
                SELECT id, username, full_name, role, branch_id, institute_id,
                       can_view_all_branches, is_active
                FROM users
                WHERE id = ? AND institute_id = ?
                LIMIT 1
                """,
                (int(user_id), int(tenant.institute_id)),
            ).fetchone()
            if user:
                try:
                    assert_feature_enabled(conn, int(tenant.institute_id), "smart_counselling")
                except SubscriptionAccessDenied as exc:
                    return error_response("feature_disabled", str(exc), 403)
        finally:
            conn.close()

        if not user or not user["is_active"] or user["role"] not in {"admin", "staff"}:
            return error_response(
                "forbidden",
                "Smart Counselling is available to active staff members only.",
                403,
            )

        g.smart_counselling_actor = SmartCounsellingActor(
            id=int(user["id"]),
            institute_id=int(user["institute_id"]),
            role=user["role"],
            branch_id=int(user["branch_id"]) if user["branch_id"] is not None else None,
            can_view_all_branches=bool(user["can_view_all_branches"]),
            username=user["username"],
            full_name=user["full_name"],
        )

        return route_function(*args, **kwargs)

    return wrapper
