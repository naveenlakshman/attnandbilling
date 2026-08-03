from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, text

from .database import notification_session
from .models import Notification, NotificationReceipt

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


def applicable_notifications(student_id, institute_id, now=None):
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
        result = []
        for notice in notices:
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
                        WHERE i.student_id=:student_id AND i.status NOT IN ('paid','cancelled','write_off')
                    """), {
                        "student_id": student_id,
                        "today": (now + timedelta(hours=5, minutes=30)).date(),
                    }).mappings().first()
                amount = financial["overdue_total"] if notice.notification_type == "payment_overdue" else financial["due_total"]
                if not amount or float(amount) <= 0:
                    continue
            result.append({
                "id": notice.id, "type": notice.notification_type,
                "title": notice.title, "message": notice.message,
                "icon": notice.icon, "color": notice.color,
                "action_label": notice.action_label, "action_url": notice.action_url,
                "priority": notice.priority,
            })
        return result


def record_views(student_id, institute_id, notification_ids, now=None):
    now = now or datetime.utcnow()
    with notification_session() as db:
        for notification_id in notification_ids:
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
