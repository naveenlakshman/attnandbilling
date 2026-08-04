from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_, select, text

from .database import notification_session
from .models import (
    FeeExtensionRequest,
    FeeReminderImpression,
    FeeReminderSettings,
    Notification,
    NotificationReceipt,
)

TYPE_OPTIONS = {
    "fee_due_reminder": {"label": "Fee due reminder", "icon": "bi-wallet2", "color": "primary"},
    "payment_overdue": {"label": "Payment overdue warning", "icon": "bi-exclamation-triangle-fill", "color": "danger"},
    "holiday": {"label": "Holiday announcement", "icon": "bi-calendar-heart", "color": "success"},
    "new_batch": {"label": "New batch announcement", "icon": "bi-people-fill", "color": "info"},
    "referral_offer": {"label": "Referral offer", "icon": "bi-gift-fill", "color": "warning"},
    "exam_schedule": {"label": "Exam schedule", "icon": "bi-journal-check", "color": "primary"},
    "maintenance": {"label": "Maintenance notice", "icon": "bi-tools", "color": "secondary"},
}
AUDIENCE_OPTIONS = {
    "all_students": "All students",
    "batches": "Selected batches",
    "courses": "Selected courses",
    "students": "Selected students",
}

DEFAULT_FEE_REMINDER_SETTINGS = {
    "is_enabled": True,
    "days_before_due": 3,
    "repeat_hours": 12,
    "extension_min_days": 3,
    "extension_max_days": 5,
    "allow_extension_requests": True,
    "title_template": "Fee payment reminder",
    "message_template": "Your installment of {amount} for {invoice_no} is due on {due_date}.",
    "icon": "bi-wallet2",
    "color": "warning",
}


def _parse_due_date(value):
    raw = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def fee_reminder_settings(db, institute_id, create=False):
    settings = db.get(FeeReminderSettings, int(institute_id))
    if settings or not create:
        return settings
    settings = FeeReminderSettings(institute_id=int(institute_id), **DEFAULT_FEE_REMINDER_SETTINGS)
    db.add(settings)
    db.flush()
    return settings


def _automatic_fee_notifications(db, student_id, institute_id, now):
    settings = fee_reminder_settings(db, institute_id)
    values = settings or type("DefaultFeeSettings", (), DEFAULT_FEE_REMINDER_SETTINGS)()
    if not values.is_enabled:
        return []

    today = (now + timedelta(hours=5, minutes=30)).date()
    rows = db.execute(text("""
        SELECT ip.id AS installment_id, ip.due_date, ip.amount_due, ip.amount_paid,
               i.id AS invoice_id, i.invoice_no
        FROM installment_plans ip
        JOIN invoices i ON i.id=ip.invoice_id
        JOIN students s ON s.id=i.student_id AND s.institute_id=i.institute_id
        WHERE i.student_id=:student_id AND i.institute_id=:institute_id
          AND ip.status!='paid' AND (ip.amount_due-ip.amount_paid)>0
          AND i.status NOT IN ('paid','cancelled','write_off')
        ORDER BY ip.due_date, ip.id
    """), {"student_id": student_id, "institute_id": institute_id}).mappings().all()
    if not rows:
        return []

    installment_ids = [int(row["installment_id"]) for row in rows]
    impressions = {
        item.installment_id: item
        for item in db.scalars(select(FeeReminderImpression).where(
            FeeReminderImpression.institute_id == institute_id,
            FeeReminderImpression.student_id == student_id,
            FeeReminderImpression.installment_id.in_(installment_ids),
        )).all()
    }
    requests = {}
    for item in db.scalars(select(FeeExtensionRequest).where(
        FeeExtensionRequest.institute_id == institute_id,
        FeeExtensionRequest.student_id == student_id,
        FeeExtensionRequest.installment_id.in_(installment_ids),
    ).order_by(FeeExtensionRequest.requested_at.desc())).all():
        requests.setdefault(item.installment_id, item)

    result = []
    repeat_cutoff = now - timedelta(hours=int(values.repeat_hours))
    for row in rows:
        due_date = _parse_due_date(row["due_date"])
        if not due_date or not (today <= due_date <= today + timedelta(days=int(values.days_before_due))):
            continue
        impression = impressions.get(int(row["installment_id"]))
        if impression and impression.last_shown_at > repeat_cutoff:
            continue
        balance = float(row["amount_due"] or 0) - float(row["amount_paid"] or 0)
        template_values = {
            "amount": f"Rs.{balance:,.0f}",
            "invoice_no": row["invoice_no"],
            "due_date": due_date.strftime("%d-%b-%Y"),
        }
        try:
            title = values.title_template.format(**template_values)
            message = values.message_template.format(**template_values)
        except (KeyError, ValueError):
            title = DEFAULT_FEE_REMINDER_SETTINGS["title_template"]
            message = DEFAULT_FEE_REMINDER_SETTINGS["message_template"].format(**template_values)
        extension = requests.get(int(row["installment_id"]))
        result.append({
            "id": f"fee-{row['installment_id']}",
            "source": "automatic_fee",
            "type": "fee_due_reminder",
            "title": title,
            "message": message,
            "icon": values.icon,
            "color": values.color,
            "priority": 95,
            "action_label": None,
            "action_url": None,
            "fee": {
                "installment_id": int(row["installment_id"]),
                "invoice_no": row["invoice_no"],
                "amount": template_values["amount"],
                "due_date": due_date.isoformat(),
                "extension_allowed": bool(values.allow_extension_requests) and not (
                    extension and extension.status in {"pending", "approved"}
                ),
                "extension_min_days": int(values.extension_min_days),
                "extension_max_days": int(values.extension_max_days),
                "extension_status": extension.status if extension else None,
                "requested_due_date": extension.requested_due_date.isoformat() if extension else None,
            },
        })
    return result


def applicable_notifications(student_id, institute_id, now=None, include_standard=True):
    now = now or datetime.utcnow()
    with notification_session() as db:
        student_scope = db.execute(
            text("""
                SELECT s.id, GROUP_CONCAT(DISTINCT sb.batch_id) AS batch_ids,
                       GROUP_CONCAT(DISTINCT b.course_id) AS course_ids
                FROM students s
                LEFT JOIN student_batches sb ON sb.student_id=s.id AND sb.status='active'
                LEFT JOIN batches b ON b.id=sb.batch_id
                WHERE s.id=:student_id AND s.institute_id=:institute_id
                GROUP BY s.id
            """),
            {"student_id": student_id, "institute_id": institute_id},
        ).mappings().first()
        if not student_scope:
            return []
        batch_ids = {int(v) for v in (student_scope["batch_ids"] or "").split(",") if v}
        course_ids = {int(v) for v in (student_scope["course_ids"] or "").split(",") if v}

        notices = db.scalars(
            select(Notification).where(
                Notification.institute_id == institute_id,
                Notification.is_active.is_(True),
                Notification.starts_at <= now,
                or_(Notification.ends_at.is_(None), Notification.ends_at >= now),
            ).order_by(Notification.priority.desc(), Notification.starts_at.asc(), Notification.id.asc())
        ).all()

        financial = None
        result = _automatic_fee_notifications(db, student_id, institute_id, now)
        for notice in notices if include_standard else []:
            target_ids = {target.target_id for target in notice.targets}
            audience_match = (
                notice.audience_type == "all_students"
                or (notice.audience_type == "students" and student_id in target_ids)
                or (notice.audience_type == "batches" and bool(batch_ids & target_ids))
                or (notice.audience_type == "courses" and bool(course_ids & target_ids))
            )
            if not audience_match:
                continue
            if notice.notification_type in {"fee_due_reminder", "payment_overdue"}:
                if financial is None:
                    financial = db.execute(text("""
                        SELECT
                          SUM(CASE WHEN ip.amount_due > ip.amount_paid THEN ip.amount_due-ip.amount_paid ELSE 0 END) AS due_total,
                          SUM(CASE WHEN ip.due_date < :today AND ip.amount_due > ip.amount_paid THEN ip.amount_due-ip.amount_paid ELSE 0 END) AS overdue_total
                        FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id
                        WHERE i.student_id=:student_id AND i.institute_id=:institute_id
                          AND i.status NOT IN ('paid','cancelled','write_off')
                    """), {
                        "student_id": student_id,
                        "institute_id": institute_id,
                        "today": (now + timedelta(hours=5, minutes=30)).date(),
                    }).mappings().first()
                amount = financial["overdue_total"] if notice.notification_type == "payment_overdue" else financial["due_total"]
                if not amount or float(amount) <= 0:
                    continue
            result.append({
                "id": notice.id, "source": "standard", "type": notice.notification_type,
                "title": notice.title, "message": notice.message,
                "icon": notice.icon, "color": notice.color,
                "action_label": notice.action_label, "action_url": notice.action_url,
                "priority": notice.priority,
            })
        result.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("id"))))
        return result


def record_views(student_id, institute_id, notifications, now=None):
    now = now or datetime.utcnow()
    with notification_session() as db:
        for item in notifications:
            if item.get("source") == "automatic_fee":
                installment_id = int(item["fee"]["installment_id"])
                impression = db.scalar(select(FeeReminderImpression).where(
                    FeeReminderImpression.institute_id == institute_id,
                    FeeReminderImpression.student_id == student_id,
                    FeeReminderImpression.installment_id == installment_id,
                ))
                if impression:
                    impression.last_shown_at = now
                    impression.view_count += 1
                else:
                    db.add(FeeReminderImpression(
                        institute_id=institute_id, student_id=student_id,
                        installment_id=installment_id, first_shown_at=now,
                        last_shown_at=now, view_count=1,
                    ))
                continue
            notification_id = int(item["id"])
            receipt = db.scalar(select(NotificationReceipt).where(
                NotificationReceipt.notification_id == notification_id,
                NotificationReceipt.student_id == student_id,
                NotificationReceipt.institute_id == institute_id,
            ))
            if receipt:
                receipt.last_viewed_at = now
                receipt.view_count += 1
            else:
                db.add(NotificationReceipt(
                    notification_id=notification_id, student_id=student_id,
                    institute_id=institute_id, first_viewed_at=now,
                    last_viewed_at=now, view_count=1,
                ))
        db.commit()
