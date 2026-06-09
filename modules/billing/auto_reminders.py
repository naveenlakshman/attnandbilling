from datetime import date, datetime, timedelta

from db import get_company_profile, get_conn, log_activity
from modules.core.sms import normalize_sms_phone, send_sms


AUTO_SMS_SENT_VIA = "auto_sms"


def _money(amount):
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    return f"Rs.{value:,.0f}"


def _format_due_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d-%b-%Y")
    except Exception:
        return str(value or "")


def _reminder_type(days_until_due):
    if days_until_due == 3:
        return "before_3_days"
    if days_until_due == 2:
        return "before_2_days"
    if days_until_due == 0:
        return "due_today"
    if -7 <= days_until_due <= -1:
        return f"overdue_day_{abs(days_until_due)}"
    return None


def _build_message(row, reminder_type, company):
    first_name = (row["student_name"] or "Student").split()[0]
    company_name = company.get("company_name") or "Global IT Education"
    contact_number = company.get("phone") or ""
    amount = _money(row["balance_due"])
    due_date = _format_due_date(row["due_date_iso"])
    invoice_no = row["invoice_no"]
    contact_suffix = f" For any clarification, contact {contact_number}." if contact_number else ""

    if reminder_type == "before_3_days":
        return (
            f"Dear {first_name}, this is a reminder from {company_name}. "
            f"Your fee installment of {amount} for Invoice {invoice_no} is due on {due_date}. "
            f"Kindly make the payment on or before the due date.{contact_suffix}"
        )

    if reminder_type == "before_2_days":
        return (
            f"Dear {first_name}, gentle reminder from {company_name}: "
            f"your fee installment of {amount} for Invoice {invoice_no} is due on {due_date}. "
            f"Please arrange payment on time.{contact_suffix}"
        )

    if reminder_type == "due_today":
        return (
            f"Dear {first_name}, reminder from {company_name}: "
            f"your fee amount of {amount} for Invoice {invoice_no} is due today. "
            f"Kindly make the payment today.{contact_suffix}"
        )

    overdue_day = reminder_type.replace("overdue_day_", "")
    return (
        f"Dear {first_name}, reminder from {company_name}: "
        f"your pending fee amount of {amount} for Invoice {invoice_no} was due on {due_date}. "
        f"This is overdue by {overdue_day} day(s). Kindly make the payment at the earliest.{contact_suffix}"
    )


def _load_due_installments(cur, run_date):
    start_date = (run_date - timedelta(days=7)).isoformat()
    end_date = (run_date + timedelta(days=3)).isoformat()

    cur.execute("""
        SELECT
            ip.id AS installment_id,
            ip.due_date,
            parse_date(ip.due_date) AS due_date_iso,
            ip.amount_due,
            ip.amount_paid,
            (ip.amount_due - ip.amount_paid) AS balance_due,
            i.id AS invoice_id,
            i.invoice_no,
            i.branch_id,
            i.total_amount,
            s.id AS student_id,
            s.full_name AS student_name,
            s.phone AS student_phone
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND (ip.amount_due - ip.amount_paid) > 0
          AND parse_date(ip.due_date) >= ?
          AND parse_date(ip.due_date) <= ?
          AND i.status NOT IN ('paid', 'cancelled', 'write_off', 'partially_written_off')
          AND (
            (SELECT COALESCE(SUM(r.amount_received), 0) FROM receipts r WHERE r.invoice_id = i.id)
            + (SELECT COALESCE(SUM(bw.amount_written_off), 0) FROM bad_debt_writeoffs bw WHERE bw.invoice_id = i.id)
          ) < i.total_amount
        ORDER BY parse_date(ip.due_date) ASC, s.full_name ASC
    """, (start_date, end_date))
    return cur.fetchall()


def _already_processed_today(cur, installment_id, reminder_type, run_date):
    cur.execute("""
        SELECT 1
        FROM reminder_logs
        WHERE installment_id = ?
          AND reminder_type = ?
          AND sent_via = ?
          AND substr(sent_at, 1, 10) = ?
        LIMIT 1
    """, (installment_id, reminder_type, AUTO_SMS_SENT_VIA, run_date.isoformat()))
    return cur.fetchone() is not None


def send_automatic_fee_reminders(run_date=None, dry_run=False, limit=None):
    run_date = run_date or date.today()
    company = get_company_profile()
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    summary = {
        "date": run_date.isoformat(),
        "dry_run": dry_run,
        "eligible": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "items": [],
    }

    try:
        for row in _load_due_installments(cur, run_date):
            try:
                due_date = date.fromisoformat(str(row["due_date_iso"])[:10])
            except Exception:
                summary["skipped"] += 1
                continue

            reminder_type = _reminder_type((due_date - run_date).days)
            if not reminder_type:
                summary["skipped"] += 1
                continue

            if _already_processed_today(cur, row["installment_id"], reminder_type, run_date):
                summary["skipped"] += 1
                continue

            phone = normalize_sms_phone(row["student_phone"])
            if not phone:
                summary["skipped"] += 1
                summary["items"].append({
                    "installment_id": row["installment_id"],
                    "invoice_no": row["invoice_no"],
                    "student": row["student_name"],
                    "status": "skipped",
                    "reason": "missing_phone",
                })
                continue

            message = _build_message(row, reminder_type, company)
            summary["eligible"] += 1

            if dry_run:
                summary["items"].append({
                    "installment_id": row["installment_id"],
                    "invoice_no": row["invoice_no"],
                    "student": row["student_name"],
                    "phone": phone,
                    "reminder_type": reminder_type,
                    "status": "dry_run",
                })
            else:
                result = send_sms(phone, message)
                status = "sent" if result.get("success") else "failed"
                cur.execute("""
                    INSERT INTO reminder_logs (
                        student_id, invoice_id, installment_id, phone_number,
                        reminder_type, message_text, status, sent_via, sent_by, sent_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["student_id"],
                    row["invoice_id"],
                    row["installment_id"],
                    phone,
                    reminder_type,
                    message,
                    status,
                    AUTO_SMS_SENT_VIA,
                    None,
                    now,
                ))
                if result.get("success"):
                    summary["sent"] += 1
                    log_activity(
                        user_id=None,
                        branch_id=row["branch_id"],
                        action_type="sms",
                        module_name="receivables",
                        record_id=row["installment_id"],
                        description=f"Automatic fee reminder SMS sent to {phone} for {row['invoice_no']}",
                        conn=conn,
                    )
                else:
                    summary["failed"] += 1

                summary["items"].append({
                    "installment_id": row["installment_id"],
                    "invoice_no": row["invoice_no"],
                    "student": row["student_name"],
                    "phone": phone,
                    "reminder_type": reminder_type,
                    "status": status,
                    "error": result.get("error"),
                })

            if limit and summary["eligible"] >= limit:
                break

        if not dry_run:
            conn.commit()
        return summary
    finally:
        conn.close()
