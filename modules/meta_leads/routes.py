from __future__ import annotations

import re

from flask import flash, redirect, render_template, request, session, url_for

from db import get_conn, log_activity
from modules.core.utils import admin_required
from services.meta_lead_routes import list_routes, save_route
from services.tenant_context import get_current_institute_id

from . import meta_leads_bp


def _positive_int(name):
    value = (request.form.get(name) or "").strip()
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f"{name.replace('_', ' ').title()} is required.")
    return int(value)


def _options(conn, institute_id):
    courses = conn.execute("""SELECT id,course_name,duration_hours FROM courses
        WHERE institute_id=? AND is_active=1 ORDER BY course_name""", (institute_id,)).fetchall()
    batches = conn.execute("""SELECT b.id,b.batch_name,b.course_id,b.branch_id,b.start_date,b.end_date,
        b.start_time,b.end_time FROM batches b JOIN branches br ON br.id=b.branch_id
        WHERE br.institute_id=? AND br.is_active=1 AND b.status='active'
        ORDER BY b.start_date,b.start_time,b.batch_name""", (institute_id,)).fetchall()
    branches = conn.execute("""SELECT id,branch_name FROM branches
        WHERE institute_id=? AND is_active=1 ORDER BY branch_name""", (institute_id,)).fetchall()
    counsellors = conn.execute("""SELECT u.id,u.full_name,u.branch_id,u.can_view_all_branches
        FROM users u JOIN institute_memberships im ON im.user_id=u.id AND im.institute_id=u.institute_id
        WHERE u.institute_id=? AND u.is_active=1 AND im.is_active=1 AND u.role IN ('admin','staff')
        ORDER BY u.full_name""", (institute_id,)).fetchall()
    return courses, batches, branches, counsellors


@meta_leads_bp.route("/mappings", methods=["GET", "POST"])
@admin_required
def mappings():
    institute_id = get_current_institute_id(default=1)
    conn = get_conn()
    try:
        courses, batches, branches, counsellors = _options(conn, institute_id)
        if request.method == "POST":
            page_id = (request.form.get("page_id") or "").strip()
            form_id = (request.form.get("form_id") or "").strip()
            if not re.fullmatch(r"[0-9]{1,40}", page_id) or not re.fullmatch(r"[0-9]{1,40}", form_id):
                raise ValueError("Page ID and Form ID must be numeric Meta identifiers.")
            course_id = _positive_int("course_id")
            batch_id = _positive_int("batch_id")
            branch_id = _positive_int("branch_id")
            counsellor_id = _positive_int("counsellor_user_id")
            active = request.form.get("is_active") == "1"
            course = conn.execute("SELECT id FROM courses WHERE id=? AND institute_id=? AND is_active=1",
                                  (course_id, institute_id)).fetchone()
            branch = conn.execute("SELECT id FROM branches WHERE id=? AND institute_id=? AND is_active=1",
                                  (branch_id, institute_id)).fetchone()
            batch = conn.execute("""SELECT id FROM batches WHERE id=? AND course_id=? AND branch_id=?
                AND status='active'""", (batch_id, course_id, branch_id)).fetchone()
            counsellor = conn.execute("""SELECT u.id FROM users u
                JOIN institute_memberships im ON im.user_id=u.id AND im.institute_id=u.institute_id
                WHERE u.id=? AND u.institute_id=? AND u.is_active=1 AND im.is_active=1
                  AND (u.branch_id=? OR u.can_view_all_branches=1)""",
                (counsellor_id, institute_id, branch_id)).fetchone()
            if not all((course, branch, batch, counsellor)):
                raise ValueError("Course, batch, branch or counsellor mapping is not active and consistent.")
            route_id = save_route(institute_id=institute_id, page_id=page_id, form_id=form_id,
                course_id=course_id, batch_id=batch_id, branch_id=branch_id,
                counsellor_user_id=counsellor_id, is_active=active,
                actor_user_id=int(session["user_id"]))
            log_activity(session["user_id"], session.get("branch_id"), "update", "meta_lead_routes",
                         route_id, f"Saved Meta routing for Page {page_id}, Form {form_id}")
            flash("Meta lead mapping saved. Existing REVIEW notifications were not reassigned.", "success")
            return redirect(url_for("meta_leads.mappings"))
    except ValueError as exc:
        flash(str(exc), "danger")
    finally:
        conn.close()
    try:
        routes, reviews = list_routes(institute_id)
    except Exception:
        routes, reviews = [], []
        flash("Meta routing storage is unavailable.", "danger")
    names = {
        "courses": {int(x["id"]): x["course_name"] for x in courses},
        "batches": {int(x["id"]): x["batch_name"] for x in batches},
        "branches": {int(x["id"]): x["branch_name"] for x in branches},
        "counsellors": {int(x["id"]): x["full_name"] for x in counsellors},
    }
    return render_template("meta_leads/mappings.html", routes=routes, reviews=reviews,
        courses=courses, batches=batches, branches=branches, counsellors=counsellors, names=names)

