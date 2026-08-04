from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import selectinload

from db import get_conn
from modules.core.utils import admin_required
from services.tenant_context import get_current_institute_id
from . import notifications_bp
from .database import notification_session
from .models import FeeExtensionRequest, Notification, NotificationTarget
from .service import (
    AUDIENCE_OPTIONS,
    DEFAULT_FEE_REMINDER_SETTINGS,
    TYPE_OPTIONS,
    _parse_due_date,
    applicable_notifications,
    fee_reminder_settings,
    record_views,
)


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
        pending_extensions = db.scalar(select(func.count()).select_from(FeeExtensionRequest).where(
            FeeExtensionRequest.institute_id == institute_id,
            FeeExtensionRequest.status == "pending",
        )) or 0
    return render_template(
        "notifications/admin_list.html", notices=notices,
        type_options=TYPE_OPTIONS, audience_options=AUDIENCE_OPTIONS,
        pending_extensions=pending_extensions,
    )


@notifications_bp.route("/admin/fee-reminders", methods=["GET", "POST"])
@admin_required
def fee_reminder_admin():
    institute_id = int(get_current_institute_id(default=1))
    with notification_session() as db:
        settings = fee_reminder_settings(db, institute_id, create=True)
        if request.method == "POST":
            try:
                days_before = int(request.form.get("days_before_due", 3))
                repeat_hours = int(request.form.get("repeat_hours", 12))
                overdue_grace_days = int(request.form.get("overdue_grace_days", 2))
                min_days = int(request.form.get("extension_min_days", 3))
                max_days = int(request.form.get("extension_max_days", 5))
                if not 1 <= days_before <= 14:
                    raise ValueError("Reminder lead time must be between 1 and 14 days.")
                if not 6 <= repeat_hours <= 168:
                    raise ValueError("Repeat interval must be between 6 and 168 hours.")
                if not 1 <= overdue_grace_days <= 14:
                    raise ValueError("Overdue grace period must be between 1 and 14 days.")
                if not (1 <= min_days <= max_days <= 14):
                    raise ValueError("Extension range must be between 1 and 14 days.")
                title = request.form.get("title_template", "").strip()
                message = request.form.get("message_template", "").strip()
                if not title or not message:
                    raise ValueError("Reminder title and message are required.")
                allowed = {"amount": "Rs.1,000", "invoice_no": "INV-001", "due_date": "05-Aug-2026", "lock_date": "08-Aug-2026"}
                title.format(**allowed)
                message.format(**allowed)
                overdue_title = request.form.get("overdue_title_template", "").strip()
                overdue_message = request.form.get("overdue_message_template", "").strip()
                locked_title = request.form.get("locked_title_template", "").strip()
                locked_message = request.form.get("locked_message_template", "").strip()
                if not all((overdue_title, overdue_message, locked_title, locked_message)):
                    raise ValueError("Overdue warning and content restriction messages are required.")
                for template in (overdue_title, overdue_message, locked_title, locked_message):
                    template.format(**allowed)
                settings.is_enabled = "1" in request.form.getlist("is_enabled")
                settings.days_before_due = days_before
                settings.repeat_hours = repeat_hours
                settings.overdue_grace_days = overdue_grace_days
                settings.restrict_content_on_overdue = "1" in request.form.getlist("restrict_content_on_overdue")
                settings.extension_min_days = min_days
                settings.extension_max_days = max_days
                settings.allow_extension_requests = "1" in request.form.getlist("allow_extension_requests")
                settings.title_template = title
                settings.message_template = message
                settings.overdue_title_template = overdue_title
                settings.overdue_message_template = overdue_message
                settings.locked_title_template = locked_title
                settings.locked_message_template = locked_message
                settings.icon = "bi-wallet2"
                settings.color = "warning"
                settings.updated_by = session.get("user_id")
                settings.updated_at = datetime.utcnow()
                db.commit()
                flash("Automatic fee reminder settings saved.", "success")
                return redirect(url_for("notifications.fee_reminder_admin"))
            except (KeyError, TypeError, ValueError) as exc:
                db.rollback()
                flash(f"Invalid reminder settings: {exc}", "danger")
                return redirect(url_for("notifications.fee_reminder_admin"))

        request_rows = db.execute(text("""
            SELECT fer.id, fer.student_id, fer.installment_id, fer.original_due_date,
                   fer.requested_due_date, fer.extension_days, fer.reason, fer.status,
                   fer.requested_at, fer.reviewed_at, fer.review_note,
                   s.full_name, s.student_code, i.invoice_no
            FROM fee_extension_requests fer
            JOIN students s ON s.id=fer.student_id AND s.institute_id=fer.institute_id
            JOIN installment_plans ip ON ip.id=fer.installment_id
            JOIN invoices i ON i.id=ip.invoice_id AND i.student_id=fer.student_id
                              AND i.institute_id=fer.institute_id
            WHERE fer.institute_id=:institute_id
            ORDER BY CASE fer.status WHEN 'pending' THEN 0 ELSE 1 END, fer.requested_at DESC
        """), {"institute_id": institute_id}).mappings().all()
        preview = {
            "title": settings.title_template,
            "message": settings.message_template,
            "overdue_title": settings.overdue_title_template,
            "overdue_message": settings.overdue_message_template,
            "locked_title": settings.locked_title_template,
            "locked_message": settings.locked_message_template,
        }
        sample = {"amount": "Rs.4,150", "invoice_no": "GIT/B/459", "due_date": "05-Aug-2026", "lock_date": "08-Aug-2026"}
        try:
            preview = {key: value.format(**sample) for key, value in preview.items()}
        except (KeyError, ValueError):
            preview = {
                "title": DEFAULT_FEE_REMINDER_SETTINGS["title_template"],
                "message": DEFAULT_FEE_REMINDER_SETTINGS["message_template"].format(**sample),
                "overdue_title": DEFAULT_FEE_REMINDER_SETTINGS["overdue_title_template"],
                "overdue_message": DEFAULT_FEE_REMINDER_SETTINGS["overdue_message_template"].format(**sample),
                "locked_title": DEFAULT_FEE_REMINDER_SETTINGS["locked_title_template"],
                "locked_message": DEFAULT_FEE_REMINDER_SETTINGS["locked_message_template"].format(**sample),
            }
        return render_template(
            "notifications/fee_reminder_admin.html",
            settings=settings, extension_requests=request_rows, preview=preview,
        )


@notifications_bp.post("/admin/fee-extensions/<int:extension_id>/<action>")
@admin_required
def review_fee_extension(extension_id, action):
    if action not in {"approve", "reject"}:
        abort(404)
    institute_id = int(get_current_institute_id(default=1))
    with notification_session() as db:
        extension = db.scalar(select(FeeExtensionRequest).where(
            FeeExtensionRequest.id == extension_id,
            FeeExtensionRequest.institute_id == institute_id,
        ))
        if not extension:
            abort(404)
        if extension.status != "pending":
            flash("This request has already been reviewed.", "warning")
            return redirect(url_for("notifications.fee_reminder_admin"))
        note = request.form.get("review_note", "").strip() or None
        if action == "reject":
            extension.status = "rejected"
        else:
            row = db.execute(text("""
                SELECT ip.due_date
                FROM installment_plans ip
                JOIN invoices i ON i.id=ip.invoice_id
                WHERE ip.id=:installment_id AND i.student_id=:student_id
                  AND i.institute_id=:institute_id
                FOR UPDATE
            """), {
                "installment_id": extension.installment_id,
                "student_id": extension.student_id,
                "institute_id": institute_id,
            }).mappings().first()
            current_due = _parse_due_date(row["due_date"]) if row else None
            if current_due != extension.original_due_date:
                db.rollback()
                flash("The installment due date changed after this request. Review the latest invoice before approving.", "danger")
                return redirect(url_for("notifications.fee_reminder_admin"))
            result = db.execute(text("UPDATE installment_plans SET due_date=:due_date WHERE id=:installment_id"), {
                "due_date": extension.requested_due_date.isoformat(),
                "installment_id": extension.installment_id,
            })
            if result.rowcount != 1:
                db.rollback()
                flash("The installment could not be updated.", "danger")
                return redirect(url_for("notifications.fee_reminder_admin"))
            extension.status = "approved"
            extension.applied_at = datetime.utcnow()
        extension.reviewed_by = session.get("user_id")
        extension.reviewed_at = datetime.utcnow()
        extension.review_note = note
        db.commit()
    flash("Due-date extension approved successfully." if action == "approve" else "Due-date extension rejected.", "success")
    return redirect(url_for("notifications.fee_reminder_admin"))


@notifications_bp.post("/student/fee-extension")
def request_fee_extension():
    student_id = session.get("student_id")
    if not student_id:
        abort(401)
    institute_id = int(get_current_institute_id(default=1))
    if int(session.get("student_institute_id") or institute_id) != institute_id:
        abort(403)
    payload = request.get_json(silent=True) or {}
    try:
        installment_id = int(payload.get("installment_id"))
        extension_days = int(payload.get("extension_days"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Select a valid extension period."}), 400
    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 10 or len(reason) > 1000:
        return jsonify({"ok": False, "message": "Please provide a reason between 10 and 1000 characters."}), 400

    with notification_session() as db:
        settings = fee_reminder_settings(db, institute_id)
        values = settings or type("DefaultFeeSettings", (), DEFAULT_FEE_REMINDER_SETTINGS)()
        if not values.is_enabled or not values.allow_extension_requests:
            return jsonify({"ok": False, "message": "Due-date extension requests are not currently available."}), 403
        if not int(values.extension_min_days) <= extension_days <= int(values.extension_max_days):
            return jsonify({"ok": False, "message": "Select an allowed extension period."}), 400
        row = db.execute(text("""
            SELECT ip.due_date, ip.amount_due, ip.amount_paid
            FROM installment_plans ip
            JOIN invoices i ON i.id=ip.invoice_id
            WHERE ip.id=:installment_id AND i.student_id=:student_id
              AND i.institute_id=:institute_id AND ip.status!='paid'
              AND (ip.amount_due-ip.amount_paid)>0
              AND i.status NOT IN ('paid','cancelled','write_off')
        """), {
            "installment_id": installment_id,
            "student_id": int(student_id),
            "institute_id": institute_id,
        }).mappings().first()
        due_date = _parse_due_date(row["due_date"]) if row else None
        today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
        if not due_date or not (today <= due_date <= today + timedelta(days=int(values.days_before_due))):
            return jsonify({"ok": False, "message": "This installment is not currently eligible for an extension request."}), 400
        existing = db.scalar(select(FeeExtensionRequest).where(
            FeeExtensionRequest.institute_id == institute_id,
            FeeExtensionRequest.student_id == int(student_id),
            FeeExtensionRequest.installment_id == installment_id,
            FeeExtensionRequest.status.in_(["pending", "approved"]),
        ))
        if existing:
            return jsonify({"ok": False, "message": "An extension request already exists for this installment."}), 409
        requested_due = due_date + timedelta(days=extension_days)
        extension = FeeExtensionRequest(
            institute_id=institute_id, student_id=int(student_id), installment_id=installment_id,
            original_due_date=due_date, requested_due_date=requested_due,
            extension_days=extension_days, reason=reason, status="pending",
        )
        db.add(extension)
        db.commit()
        return jsonify({
            "ok": True,
            "message": "Your request was sent to the institute administrator for approval.",
            "requested_due_date": requested_due.isoformat(),
        })


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
    include_standard = session.pop("student_notifications_pending", False)
    notices = applicable_notifications(
        int(student_id), int(institute_id), include_standard=include_standard,
    )
    record_views(int(student_id), int(institute_id), notices)
    return jsonify({"notifications": notices})
