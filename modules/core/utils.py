from functools import wraps
from flask import abort, session, redirect, url_for, flash
from db import get_conn

def login_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("core.login"))
        return route_function(*args, **kwargs)
    return wrapper

def admin_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("core.login"))

        if session.get("role") != "admin":
            flash("Access denied.", "danger")
            return redirect(url_for("core.dashboard"))

        return route_function(*args, **kwargs)
    return wrapper


def platform_owner_required(route_function):
    """Restrict platform-wide tenant administration to platform owners."""
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("core.login"))

        conn = get_conn()
        try:
            owner = conn.execute(
                """SELECT id FROM users
                   WHERE id = ? AND platform_role = 'platform_owner' AND is_active = 1""",
                (session["user_id"],),
            ).fetchone()
        finally:
            conn.close()

        if not owner:
            session.pop("platform_role", None)
            abort(403)

        return route_function(*args, **kwargs)
    return wrapper


def lms_content_manager_required(route_function):
    """Allow LMS content management access to admin and staff only."""
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("core.login"))

        if session.get("role") not in ("admin", "staff"):
            flash("Access denied.", "danger")
            return redirect(url_for("core.dashboard"))

        return route_function(*args, **kwargs)
    return wrapper

