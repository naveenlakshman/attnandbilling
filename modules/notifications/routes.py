from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from db import get_conn
from modules.core.utils import admin_required
from services.tenant_context import get_current_institute_id
from . import notifications_bp
from .database import notification_session
from .models import Notification, NotificationTarget
from .service import AUDIENCE_OPTIONS, TYPE_OPTIONS, applicable_notifications, record_views


def _parse_datetime(value, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            raise ValueError("Start date and time is required.")
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M") - timedelta(hours=5, minutes=30)
    except ValueError as exc:
        raise ValueError("Enter a valid date and time.") from exc


def _target_options(institute_id):
    conn = get_conn()
    try:
        students = conn.execute(
            "SELECT id, student_code, full_name FROM students WHERE institute_id=? AND status!='dropped' ORDER BY full_name",
            (institute_id,),
        ).fetchall()
        batches = conn.execute(
            """SELECT DISTINCT b.id, b.batch_name FROM batches b
               JOIN branches br ON br.id=b.branch_id
               WHERE br.institute_id=? ORDER BY b.batch_name""",
            (institute_id,),
        ).fetchall()
        courses = conn.execute(
            "SELECT id, course_name FROM courses WHERE institute_id=? AND is_active=1 ORDER BY course_name",
            (institute_id,),
        ).fetchall()
        return students, batches, courses
    finally:
        conn.close()


@notifications_bp.route("/admin")
@admin_required
def admin_list():
    institute_id = get_current_institute_id(default=1)
    with notification_session() as db:
        notices = db.scalars(
            select(Notification)
            .where(Notification.institute_id == institute_id)
            .options(selectinload(Notification.targets))
            .order_by(Notification.is_active.desc(), Notification.priority.desc(), Notification.starts_at.desc())
        ).all()
    return render_template(
        "notifications/admin_list.html", notices=notices,
        type_options=TYPE_OPTIONS, audience_options=AUDIENCE_OPTIONS,
    )


@notifications_bp.route("/admin/new", methods=["GET", "POST"])
@notifications_bp.route("/admin/<int:notification_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_form(notification_id=None):
    institute_id = get_current_institute_id(default=1)
    with notification_session() as db:
        notice = None
        if notification_id:
            notice = db.scalar(select(Notification).where(
                Notification.id == notification_id,
                Notification.institute_id == institute_id,
            ).options(selectinload(Notification.targets)))
            if not notice:
                abort(404)

        if request.method == "POST":
            try:
                notification_type = request.form.get("notification_type", "")
                audience_type = request.form.get("audience_type", "")
                if notification_type not in TYPE_OPTIONS or audience_type not in AUDIENCE_OPTIONS:
                    raise ValueError("Select a valid notification type and audience.")
                priority = int(request.form.get("priority", 50))
                if not 1 <= priority <= 100:
                    raise ValueError("Priority must be between 1 and 100.")
                title = request.form.get("title", "").strip()
                message = request.form.get("message", "").strip()
                if not title or not message:
                    raise ValueError("Title and message are required.")
                starts_at = _parse_datetime(request.form.get("starts_at"), required=True)
                ends_at = _parse_datetime(request.form.get("ends_at"))
                if ends_at and ends_at <= starts_at:
                    raise ValueError("End date must be later than the start date.")
                defaults = TYPE_OPTIONS[notification_type]
                if notice is None:
                    notice = Notification(institute_id=institute_id, created_by=session["user_id"])
                    db.add(notice)
                notice.notification_type = notification_type
                notice.title = title
                notice.message = message
                notice.icon = request.form.get("icon", "").strip() or defaults["icon"]
                notice.color = request.form.get("color", "").strip() or defaults["color"]
                if notice.color not in {"primary", "danger", "success", "info", "warning", "secondary", "dark"}:
                    raise ValueError("Select a valid notification color.")
                notice.action_label = request.form.get("action_label", "").strip() or None
                notice.action_url = request.form.get("action_url", "").strip() or None
                if notice.action_url:
                    parsed_action = urlparse(notice.action_url)
                    if not (notice.action_url.startswith("/") or parsed_action.scheme in {"http", "https"}):
                        raise ValueError("Action URL must be an internal path or an HTTP/HTTPS link.")
                notice.audience_type = audience_type
                notice.priority = priority
                notice.starts_at = starts_at
                notice.ends_at = ends_at
                notice.is_active = request.form.get("is_active") == "1"
                notice.updated_at = datetime.utcnow()
                db.flush()
                db.execute(delete(NotificationTarget).where(NotificationTarget.notification_id == notice.id))
                if audience_type != "all_students":
                    target_ids = {int(v) for v in request.form.getlist("target_ids") if v.isdigit()}
                    if not target_ids:
                        raise ValueError("Select at least one audience target.")
                    valid_students, valid_batches, valid_courses = _target_options(institute_id)
                    valid_by_type = {
                        "students": {int(row["id"]) for row in valid_students},
                        "batches": {int(row["id"]) for row in valid_batches},
                        "courses": {int(row["id"]) for row in valid_courses},
                    }
                    if not target_ids <= valid_by_type[audience_type]:
                        raise ValueError("One or more audience targets do not belong to this institute.")
                    db.add_all(NotificationTarget(
                        notification_id=notice.id, target_type=audience_type, target_id=target_id
                    ) for target_id in target_ids)
                db.commit()
                flash("Notification saved successfully.", "success")
                return redirect(url_for("notifications.admin_list"))
            except (TypeError, ValueError) as exc:
                db.rollback()
                flash(str(exc), "danger")
                return redirect(request.url)

    students, batches, courses = _target_options(institute_id)
    return render_template(
        "notifications/admin_form.html", notice=notice,
        type_options=TYPE_OPTIONS, audience_options=AUDIENCE_OPTIONS,
        students=students, batches=batches, courses=courses,
        datetime_local_value=lambda value: (
            (value + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M") if value else ""
        ),
    )


@notifications_bp.post("/admin/<int:notification_id>/toggle")
@admin_required
def admin_toggle(notification_id):
    institute_id = get_current_institute_id(default=1)
    with notification_session() as db:
        notice = db.scalar(select(Notification).where(
            Notification.id == notification_id,
            Notification.institute_id == institute_id,
        ))
        if not notice:
            abort(404)
        notice.is_active = not notice.is_active
        notice.updated_at = datetime.utcnow()
        db.commit()
    flash("Notification status updated.", "success")
    return redirect(url_for("notifications.admin_list"))


@notifications_bp.get("/student/applicable")
def student_applicable():
    student_id = session.get("student_id")
    if not student_id:
        abort(401)
    institute_id = get_current_institute_id(default=1)
    if int(session.get("student_institute_id") or institute_id) != int(institute_id):
        abort(403)
    if not session.pop("student_notifications_pending", False):
        return jsonify({"notifications": []})
    notices = applicable_notifications(int(student_id), int(institute_id))
    record_views(int(student_id), int(institute_id), [item["id"] for item in notices])
    return jsonify({"notifications": notices})
