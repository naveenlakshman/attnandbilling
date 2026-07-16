from flask import Blueprint, render_template, request, session, redirect, url_for, flash, Response, jsonify, current_app
from datetime import date, datetime, timedelta
import calendar
import logging
import uuid
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required
from modules.core.sms import normalize_sms_phone, send_sms
from werkzeug.security import generate_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import io
import csv
import os
import base64


IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_now():
    return datetime.utcnow() + IST_OFFSET


def _parse_time_minutes(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return None

    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            parsed = datetime.strptime(raw_value.upper(), fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def _format_time_label(minutes):
    if minutes is None:
        return "-"
    minutes = int(minutes) % (24 * 60)
    return datetime(2000, 1, 1, minutes // 60, minutes % 60).strftime("%I:%M %p")


def _format_time_range(start_time, end_time):
    start_minutes = _parse_time_minutes(start_time)
    end_minutes = _parse_time_minutes(end_time)
    if start_minutes is not None and end_minutes is not None:
        return f"{_format_time_label(start_minutes)} - {_format_time_label(end_minutes)}"
    return (start_time or end_time or "Time not set")


def _initials_from_name(name):
    pieces = [piece for piece in (name or "").split() if piece]
    if not pieces:
        return "ST"
    return "".join(piece[0].upper() for piece in pieces[:2])


def _existing_student_photo(filename):
    photo_filename = (filename or "").strip()
    if not photo_filename:
        return None

    safe_filename = os.path.basename(photo_filename)
    photo_path = os.path.join(
        current_app.root_path,
        "static",
        "images",
        "student_photos",
        safe_filename
    )
    return safe_filename if os.path.isfile(photo_path) else None


def _occupancy_status(student_count, computer_count):
    if computer_count <= 0:
        return {
            "key": "over",
            "label": "Over Capacity",
            "message": "Computer capacity not configured",
            "percentage": 0,
        }

    percentage = round((student_count / computer_count) * 100, 1)
    if percentage <= 50:
        key = "free"
        label = "Free"
    elif percentage <= 75:
        key = "normal"
        label = "Normal"
    elif percentage <= 100:
        key = "busy"
        label = "Busy"
    else:
        key = "over"
        label = "Over Capacity"

    if student_count > computer_count:
        message = f"Over by {student_count - computer_count} students"
    else:
        message = f"{computer_count - student_count} seats free"

    return {
        "key": key,
        "label": label,
        "message": message,
        "percentage": percentage,
    }


def _parse_display_datetime(value):
    if not value:
        return None, False

    if isinstance(value, datetime):
        return value, True

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()), False

    if isinstance(value, str):
        raw_value = value.strip()
        if not raw_value:
            return None, False

        normalized = raw_value.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(normalized)
            has_time = ('T' in raw_value) or (' ' in raw_value and ':' in raw_value)
            return parsed, has_time
        except ValueError:
            pass

        for fmt, has_time in (
            ("%Y-%m-%d %H:%M:%S", True),
            ("%Y-%m-%d %H:%M", True),
            ("%Y-%m-%d", False),
            ("%d-%m-%Y", False),
        ):
            try:
                return datetime.strptime(raw_value, fmt), has_time
            except ValueError:
                continue

    return None, False


def _format_display_datetime(value):
    parsed, has_time = _parse_display_datetime(value)
    if not parsed:
        return value or "-"
    if not has_time:
        return parsed.strftime("%d %b %Y")
    return parsed.strftime("%d %b %Y, %I:%M %p")


def _format_display_date(value):
    parsed, _ = _parse_display_datetime(value)
    if not parsed:
        return value or "-"
    return parsed.strftime("%d %b %Y")


def _format_inr(amount):
    try:
        amount_value = float(amount or 0)
    except (TypeError, ValueError):
        amount_value = 0.0

    sign = "-" if amount_value < 0 else ""
    whole_part, fractional_part = f"{abs(amount_value):.2f}".split('.')

    if len(whole_part) > 3:
        last_three = whole_part[-3:]
        remaining = whole_part[:-3]
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        whole_part = ','.join(groups + [last_three])

    return f"{sign}{whole_part}.{fractional_part}"


def _auto_enable_portal(student_id):
    """Set portal_enabled=1 and default password (=student_code) if not already set."""
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT student_code, portal_enabled, password_hash FROM students WHERE id = ?",
            (student_id,)
        ).fetchone()
        if row and not row['portal_enabled']:
            ph = generate_password_hash(row['student_code'])
            conn.execute(
                "UPDATE students SET portal_enabled = 1, password_hash = ? WHERE id = ?",
                (ph, student_id)
            )
            conn.commit()
        conn.close()
    except Exception:
        pass  # Never block the main flow


QUALIFICATION_LEVELS = {
    "School": [
        "1st Standard",
        "2nd Standard",
        "3rd Standard",
        "4th Standard",
        "5th Standard",
        "6th Standard",
        "7th Standard",
        "8th Standard",
        "9th Standard",
        "10th Standard / SSLC",
        "10th Standard / SSLC Completed",
    ],
    "Pre-University": [
        "1st PUC - Science",
        "1st PUC - Commerce",
        "1st PUC - Arts",
        "2nd PUC - Science",
        "2nd PUC - Commerce",
        "2nd PUC - Arts",
        "11th CBSE - Science",
        "11th CBSE - Commerce",
        "11th CBSE - Humanities",
        "12th CBSE - Science",
        "12th CBSE - Commerce",
        "12th CBSE - Humanities",
        "11th ICSE - Science",
        "11th ICSE - Commerce",
        "12th ICSE - Science",
        "12th ICSE - Commerce",
        "12th / PUC Completed",
    ],
    "Diploma": [
        "Diploma in Computer Science",
        "Diploma in Information Technology",
        "Diploma in Electronics & Communication",
        "Diploma in Electrical Engineering",
        "Diploma in Mechanical Engineering",
        "Diploma in Civil Engineering",
        "Diploma in Automobile Engineering",
        "Diploma in Fashion Design",
        "Diploma in Hotel Management",
        "Diploma - 1st Year",
        "Diploma - 2nd Year",
        "Diploma - 3rd Year",
        "Diploma Completed",
    ],
    "Undergraduate": [
        "B.Com - 1st Year",
        "B.Com - 2nd Year",
        "B.Com - 3rd Year",
        "B.Com Completed",
        "BBA - 1st Year",
        "BBA - 2nd Year",
        "BBA - 3rd Year",
        "BBA Completed",
        "BBM Completed",
        "BA - 1st Year",
        "BA - 2nd Year",
        "BA - 3rd Year",
        "BA Completed",
        "BCA - 1st Year",
        "BCA - 2nd Year",
        "BCA - 3rd Year",
        "BCA Completed",
        "B.Sc - 1st Year",
        "B.Sc - 2nd Year",
        "B.Sc - 3rd Year",
        "B.Sc Completed",
        "B.Sc (CS) Completed",
        "B.Sc (IT) Completed",
        "BE / B.Tech - 1st Year",
        "BE / B.Tech - 2nd Year",
        "BE / B.Tech - 3rd Year",
        "BE / B.Tech - 4th Year",
        "BE / B.Tech Completed",
        "B.Ed Completed",
        "B.Pharm Completed",
        "BHM Completed",
        "BJMC Completed",
        "B.Design Completed",
        "B.Arch Completed",
        "LLB Completed",
        "Undergraduate Completed",
    ],
    "Postgraduate": [
        "M.Com",
        "M.Com Completed",
        "MBA",
        "MBA Completed",
        "MCA",
        "MCA Completed",
        "M.Sc",
        "M.Sc Completed",
        "M.Sc (CS) Completed",
        "M.Sc (IT) Completed",
        "MA",
        "MA Completed",
        "M.Tech / ME",
        "M.Tech / ME Completed",
        "PGDM",
        "PGDCA",
        "M.Ed Completed",
        "LLM Completed",
        "Postgraduate Completed",
    ],
    "Technical": [
        "ITI - COPA (Computer Operator & Programming)",
        "ITI - Electronics",
        "ITI - Electrician",
        "ITI - Fitter",
        "ITI - Mechanic",
        "ITI Completed",
        "Polytechnic - 1st Year",
        "Polytechnic - 2nd Year",
        "Polytechnic - 3rd Year",
        "Polytechnic Completed",
        "Certification Course",
        "Vocational Training",
    ],
    "Professional": [
        "Working Professional - IT / Software",
        "Working Professional - Finance / Accounts",
        "Working Professional - Sales / Marketing",
        "Working Professional - Teaching / Education",
        "Working Professional - Healthcare",
        "Working Professional - Government / PSU",
        "Working Professional - Banking / Insurance",
        "Working Professional - Retail / E-commerce",
        "Working Professional - Other",
        "Freelancer",
        "Business Owner / Entrepreneur",
    ],
    "Doctoral": [
        "Ph.D - Pursuing",
        "Ph.D Completed",
        "M.Phil",
    ],
}

STUDENT_RESUME_FIELDS = (
    "father_name",
    "mother_name",
    "tenth_institution",
    "tenth_board",
    "tenth_year",
    "tenth_percentage",
    "puc_institution",
    "puc_board",
    "puc_stream",
    "puc_year",
    "puc_percentage",
    "degree_institution",
    "degree_university",
    "degree_course",
    "degree_year",
    "degree_percentage",
)

STUDENT_REQUIRED_FIELD_LABELS = (
    ("branch_id", "Branch"),
    ("full_name", "Full Name"),
    ("phone", "Phone"),
    ("gender", "Gender"),
    ("email", "Email"),
    ("date_of_birth", "Date of Birth"),
    ("pincode", "Pincode"),
    ("locality", "Locality"),
    ("address", "Address"),
    ("city", "City / District / Town"),
    ("state", "State"),
    ("landmark", "Landmark"),
    ("alternate_phone", "Alternate Phone"),
    ("address_type", "Address Type"),
    ("father_name", "Father Name"),
    ("mother_name", "Mother Name"),
    ("parent_name", "Parent/Guardian Name"),
    ("parent_contact", "Parent/Guardian Contact Number"),
    ("education_level", "Education Level"),
    ("qualification", "Qualification"),
    ("student_location", "Student From"),
    ("employment_status", "Employment Status"),
    ("status", "Student Status"),
)

STUDENT_RESUME_REQUIRED_LABELS = {
    "tenth": (
        ("tenth_institution", "10th School Name"),
        ("tenth_board", "10th Board"),
        ("tenth_year", "10th Passed Year"),
        ("tenth_percentage", "10th Percentage / CGPA"),
    ),
    "puc": (
        ("puc_institution", "PUC College Name"),
        ("puc_board", "PUC Board"),
        ("puc_stream", "PUC Stream"),
        ("puc_year", "PUC Passed Year / Status"),
        ("puc_percentage", "PUC Percentage / CGPA"),
    ),
    "degree": (
        ("degree_institution", "Degree College Name"),
        ("degree_university", "Degree University"),
        ("degree_course", "Degree Course"),
        ("degree_year", "Degree Passed Year / Status"),
        ("degree_percentage", "Degree Percentage / CGPA"),
    ),
}


def _requires_puc_resume_details(education_level, qualification):
    qualification_value = (qualification or "").lower()
    return any(
        marker in qualification_value
        for marker in ("2nd puc", "12th", "puc completed")
    )


def _requires_degree_resume_details(education_level, qualification):
    qualification_value = (qualification or "").lower()
    degree_markers = (
        "b.com",
        "bba",
        "bbm",
        "ba",
        "bca",
        "b.sc",
        "be / b.tech",
        "b.ed",
        "b.pharm",
        "bhm",
        "bjmc",
        "b.design",
        "b.arch",
        "llb",
        "undergraduate",
    )
    return education_level == "Undergraduate" or any(
        marker in qualification_value for marker in degree_markers
    )


def _student_resume_form_values(form, education_level, qualification):
    values = {
        field: form.get(field, "").strip() or None
        for field in STUDENT_RESUME_FIELDS
    }

    needs_puc = _requires_puc_resume_details(education_level, qualification)
    needs_degree = _requires_degree_resume_details(education_level, qualification)
    needs_tenth = needs_puc or needs_degree

    if not needs_tenth:
        for field in (
            "tenth_institution",
            "tenth_board",
            "tenth_year",
            "tenth_percentage",
        ):
            values[field] = None

    if not (needs_puc or needs_degree):
        for field in (
            "puc_institution",
            "puc_board",
            "puc_stream",
            "puc_year",
            "puc_percentage",
        ):
            values[field] = None

    if not needs_degree:
        for field in (
            "degree_institution",
            "degree_university",
            "degree_course",
            "degree_year",
            "degree_percentage",
        ):
            values[field] = None

    return values


def _student_required_missing_labels(values, resume_fields, has_photo):
    missing = []
    for field, label in STUDENT_REQUIRED_FIELD_LABELS:
        if not str(values.get(field) or "").strip():
            missing.append(label)

    if not has_photo:
        missing.append("Student Photo")

    needs_puc = _requires_puc_resume_details(
        values.get("education_level"),
        values.get("qualification"),
    )
    needs_degree = _requires_degree_resume_details(
        values.get("education_level"),
        values.get("qualification"),
    )

    if needs_puc or needs_degree:
        for field, label in STUDENT_RESUME_REQUIRED_LABELS["tenth"]:
            if not resume_fields.get(field):
                missing.append(label)

    if needs_puc or needs_degree:
        for field, label in STUDENT_RESUME_REQUIRED_LABELS["puc"]:
            if not resume_fields.get(field):
                missing.append(label)

    if needs_degree:
        for field, label in STUDENT_RESUME_REQUIRED_LABELS["degree"]:
            if not resume_fields.get(field):
                missing.append(label)

    return missing


def _student_required_error_message(missing):
    if not missing:
        return None
    if len(missing) <= 5:
        return "Please fill all mandatory fields: " + ", ".join(missing) + "."
    shown = ", ".join(missing[:5])
    return f"Please fill all mandatory fields. Missing: {shown}, and {len(missing) - 5} more."


billing_bp = Blueprint("billing", __name__)
logger = logging.getLogger(__name__)


@billing_bp.route('/student/<int:student_id>/toggle-portal', methods=['POST'])
@login_required
def toggle_portal(student_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT full_name, student_code, portal_enabled, password_hash FROM students WHERE id = ?",
        (student_id,)
    ).fetchone()
    if not row:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for('billing.students'))

    if row['portal_enabled']:
        # Disable
        conn.execute("UPDATE students SET portal_enabled = 0 WHERE id = ?", (student_id,))
        conn.commit()
        conn.close()
        log_activity(session['user_id'], None, 'update', 'students', student_id,
                     f"Disabled portal access for {row['full_name']} ({row['student_code']})")
        flash(f"Portal access disabled for {row['full_name']}. They can no longer log in.", "warning")
    else:
        # Enable — set password to student_code if not set
        ph = row['password_hash'] or generate_password_hash(row['student_code'])
        conn.execute(
            "UPDATE students SET portal_enabled = 1, password_hash = ? WHERE id = ?",
            (ph, student_id)
        )
        conn.commit()
        conn.close()
        log_activity(session['user_id'], None, 'update', 'students', student_id,
                     f"Enabled portal access for {row['full_name']} ({row['student_code']})")
        flash(f"Portal access enabled for {row['full_name']}. Password: {row['student_code']}", "success")

    return redirect(url_for('billing.student_profile', student_id=student_id))


@billing_bp.route('/student/<int:student_id>/reset-portal-password', methods=['POST'])
@login_required
def reset_portal_password(student_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT full_name, student_code, portal_enabled FROM students WHERE id = ?",
        (student_id,)
    ).fetchone()

    if not row:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for('billing.students'))

    default_password = row['student_code']
    conn.execute(
        "UPDATE students SET password_hash = ? WHERE id = ?",
        (generate_password_hash(default_password), student_id)
    )
    conn.commit()
    conn.close()

    log_activity(
        session['user_id'],
        None,
        'update',
        'students',
        student_id,
        f"Force reset portal password for {row['full_name']} ({row['student_code']})"
    )

    if row['portal_enabled']:
        flash(
            f"Password reset successful for {row['full_name']}. New password: {default_password}. Student must change it on next login.",
            "success"
        )
    else:
        flash(
            f"Password reset for {row['full_name']} to {default_password}, but portal access is currently disabled. They must change it on next login once enabled.",
            "warning"
        )

    return redirect(url_for('billing.student_profile', student_id=student_id))


def save_student_photo(photo_data, student_code):
    """Save student photo from base64 data"""
    if not photo_data:
        return None
    
    try:
        # Remove data URL prefix if present
        if ',' in photo_data:
            photo_data = photo_data.split(',')[1]
        
        # Create directory if it doesn't exist
        photo_dir = os.path.join('static', 'images', 'student_photos')
        os.makedirs(photo_dir, exist_ok=True)
        
        # Decode and save
        photo_bytes = base64.b64decode(photo_data)
        filename = f"{student_code}.jpg"
        filepath = os.path.join(photo_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(photo_bytes)
        
        return filename
    except Exception as e:
        print(f"Error saving photo: {e}")
        return None

@billing_bp.route("/")
@login_required
def menu():
    """Staff menu page - simple overview for staff members"""
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()

    # Past dues
    past_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) < ?
        ORDER BY parse_date(ip.due_date) ASC
    """

    cur.execute(past_dues_query, [today])
    past_dues = cur.fetchall()

    # Today's dues
    todays_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) = ?
        ORDER BY s.full_name ASC
    """

    cur.execute(todays_dues_query, [today])
    todays_dues = cur.fetchall()

    total_past_due = sum(float(row["balance_due"] or 0) for row in past_dues)
    total_today_due = sum(float(row["balance_due"] or 0) for row in todays_dues)

    # Get bad debt statistics
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            COUNT(*) AS total_writeoffs,
            IFNULL(SUM(amount_written_off), 0) AS total_written_off
        FROM bad_debt_writeoffs
    """)
    bad_debt_stats = cur.fetchone()

    conn.close()

    return render_template(
        "billing/menu.html",
        past_dues=past_dues,
        todays_dues=todays_dues,
        total_past_due=total_past_due,
        total_today_due=total_today_due,
        today=today,
        bad_debt_stats=bad_debt_stats
    )

@billing_bp.route("/dashboard")
@login_required
@admin_required
def dashboard():
    conn = get_conn()
    cur = conn.cursor()

    branch_id = request.args.get("branch_id", "").strip()
    period = request.args.get("period", "this_fy").strip()

    today = date.today()

    def get_period_range(period_key):
        year = today.year
        month = today.month

        if period_key == "this_fy":
            if month >= 4:
                start_date = date(year, 4, 1)
                end_date = date(year + 1, 3, 31)
            else:
                start_date = date(year - 1, 4, 1)
                end_date = date(year, 3, 31)

        elif period_key == "last_fy":
            if month >= 4:
                start_date = date(year - 1, 4, 1)
                end_date = date(year, 3, 31)
            else:
                start_date = date(year - 2, 4, 1)
                end_date = date(year - 1, 3, 31)

        elif period_key == "last_12_months":
            first_day_this_month = date(today.year, today.month, 1)

            start_year = first_day_this_month.year
            start_month = first_day_this_month.month - 11
            while start_month <= 0:
                start_month += 12
                start_year -= 1

            start_date = date(start_year, start_month, 1)

            end_year = first_day_this_month.year
            end_month = first_day_this_month.month
            last_day = calendar.monthrange(end_year, end_month)[1]
            end_date = date(end_year, end_month, last_day)

        else:
            if month >= 4:
                start_date = date(year, 4, 1)
                end_date = date(year + 1, 3, 31)
            else:
                start_date = date(year - 1, 4, 1)
                end_date = date(year, 3, 31)

        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    start_date, end_date = get_period_range(period)

    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    student_query = "SELECT COUNT(*) AS total_students FROM students WHERE substr(created_at, 1, 10) BETWEEN ? AND ?"
    student_params = [start_date, end_date]

    invoice_count_query = "SELECT COUNT(*) AS total_invoices FROM invoices WHERE parse_date(invoice_date) BETWEEN ? AND ?"
    invoice_count_params = [start_date, end_date]

    sales_query = "SELECT IFNULL(SUM(total_amount), 0) AS total_sales FROM invoices WHERE parse_date(invoice_date) BETWEEN ? AND ?"
    sales_params = [start_date, end_date]

    receipt_query = """
        SELECT IFNULL(SUM(amount_received), 0) AS total_receipts
        FROM receipts
        JOIN invoices ON receipts.invoice_id = invoices.id
        WHERE parse_date(receipts.receipt_date) BETWEEN ? AND ?
    """
    receipt_params = [start_date, end_date]

    expense_query = """
        SELECT IFNULL(SUM(amount), 0) AS total_expenses
        FROM expenses
        WHERE expense_date BETWEEN ? AND ?
    """
    expense_params = [start_date, end_date]

    if branch_id:
        student_query += " AND branch_id = ?"
        student_params.append(branch_id)

        invoice_count_query += " AND branch_id = ?"
        invoice_count_params.append(branch_id)

        sales_query += " AND (branch_id = ? OR branch_id IS NULL)"
        sales_params.append(branch_id)

        receipt_query += " AND (invoices.branch_id = ? OR invoices.branch_id IS NULL)"
        receipt_params.append(branch_id)

        expense_query += " AND branch_id = ?"
        expense_params.append(branch_id)

    cur.execute(student_query, student_params)
    total_students = int(cur.fetchone()["total_students"] or 0)

    cur.execute(invoice_count_query, invoice_count_params)
    total_invoices = int(cur.fetchone()["total_invoices"] or 0)

    cur.execute(sales_query, sales_params)
    total_sales = float(cur.fetchone()["total_sales"] or 0)

    cur.execute(receipt_query, receipt_params)
    total_receipts = float(cur.fetchone()["total_receipts"] or 0)

    cur.execute(expense_query, expense_params)
    total_expenses = float(cur.fetchone()["total_expenses"] or 0)

    net_position = total_receipts - total_expenses

    current_amount = 0.0
    bucket_1_15 = 0.0
    bucket_16_30 = 0.0
    bucket_31_45 = 0.0
    bucket_above_45 = 0.0

    aging_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            i.branch_id
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        WHERE ip.status IN ('pending', 'partially_paid', 'overdue')
    """
    aging_params = []

    if branch_id:
        aging_query += " AND (i.branch_id = ? OR i.branch_id IS NULL)"
        aging_params.append(branch_id)

    cur.execute(aging_query, aging_params)
    aging_rows = cur.fetchall()

    for row in aging_rows:
        due_date_str = row["due_date"]
        due_date_obj = None

        try:
            if len(due_date_str) == 10 and due_date_str[4] == '-':
                due_date_obj = datetime.strptime(due_date_str, "%Y-%m-%d").date()
            elif len(due_date_str) == 10 and due_date_str[2] == '-':
                due_date_obj = datetime.strptime(due_date_str, "%d-%m-%Y").date()
            elif len(due_date_str) > 10:
                try:
                    due_date_obj = datetime.strptime(due_date_str, "%d %B %Y").date()
                except ValueError:
                    due_date_obj = datetime.strptime(due_date_str, "%d %b %Y").date()
        except (ValueError, TypeError):
            continue

        if not due_date_obj:
            continue

        amount_due = float(row["amount_due"] or 0)
        amount_paid = float(row["amount_paid"] or 0)
        outstanding = amount_due - amount_paid

        if outstanding <= 0:
            continue

        overdue_days = (today - due_date_obj).days

        if overdue_days <= 0:
            current_amount += outstanding
        elif 1 <= overdue_days <= 15:
            bucket_1_15 += outstanding
        elif 16 <= overdue_days <= 30:
            bucket_16_30 += outstanding
        elif 31 <= overdue_days <= 45:
            bucket_31_45 += outstanding
        else:
            bucket_above_45 += outstanding

    total_receivables = current_amount + bucket_1_15 + bucket_16_30 + bucket_31_45 + bucket_above_45

    month_keys = []
    month_labels = []

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    y = start_dt.year
    m = start_dt.month

    while (y < end_dt.year) or (y == end_dt.year and m <= end_dt.month):
        key = f"{y}-{m:02d}"
        label = f"{calendar.month_abbr[m]} {y}"
        month_keys.append(key)
        month_labels.append(label)

        m += 1
        if m > 12:
            m = 1
            y += 1

    sales_map = {k: 0.0 for k in month_keys}
    receipts_map = {k: 0.0 for k in month_keys}
    expenses_map = {k: 0.0 for k in month_keys}

    monthly_sales_query = """
        SELECT
            invoice_date,
            total_amount
        FROM invoices
        WHERE parse_date(invoice_date) BETWEEN ? AND ?
    """
    monthly_sales_params = [start_date, end_date]

    if branch_id:
        monthly_sales_query += " AND branch_id = ?"
        monthly_sales_params.append(branch_id)

    cur.execute(monthly_sales_query, monthly_sales_params)
    for row in cur.fetchall():
        invoice_date_str = row["invoice_date"]
        total_amount = float(row["total_amount"] or 0)

        ym = None
        try:
            if len(invoice_date_str) == 10 and invoice_date_str[4] == '-':
                parsed = datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
                ym = f"{parsed.year}-{parsed.month:02d}"
            elif len(invoice_date_str) > 10:
                try:
                    parsed = datetime.strptime(invoice_date_str, "%d %B %Y").date()
                except ValueError:
                    parsed = datetime.strptime(invoice_date_str, "%d %b %Y").date()
                ym = f"{parsed.year}-{parsed.month:02d}"
        except (ValueError, TypeError):
            pass

        if ym and ym in sales_map:
            sales_map[ym] = sales_map.get(ym, 0) + total_amount

    monthly_receipts_query = """
        SELECT
            SUBSTR(parse_date(receipts.receipt_date), 1, 7) AS ym,
            IFNULL(SUM(receipts.amount_received), 0) AS total_amount
        FROM receipts
        JOIN invoices ON receipts.invoice_id = invoices.id
        WHERE parse_date(receipts.receipt_date) BETWEEN ? AND ?
    """
    monthly_receipts_params = [start_date, end_date]

    if branch_id:
        monthly_receipts_query += " AND invoices.branch_id = ?"
        monthly_receipts_params.append(branch_id)

    monthly_receipts_query += " GROUP BY SUBSTR(parse_date(receipts.receipt_date), 1, 7)"

    cur.execute(monthly_receipts_query, monthly_receipts_params)
    for row in cur.fetchall():
        ym = row["ym"]
        if ym in receipts_map:
            receipts_map[ym] = float(row["total_amount"] or 0)

    monthly_expenses_query = """
        SELECT
            substr(expense_date, 1, 7) AS ym,
            IFNULL(SUM(amount), 0) AS total_amount
        FROM expenses
        WHERE expense_date BETWEEN ? AND ?
    """
    monthly_expenses_params = [start_date, end_date]

    if branch_id:
        monthly_expenses_query += " AND branch_id = ?"
        monthly_expenses_params.append(branch_id)

    monthly_expenses_query += " GROUP BY substr(expense_date, 1, 7)"

    cur.execute(monthly_expenses_query, monthly_expenses_params)
    for row in cur.fetchall():
        ym = row["ym"]
        if ym in expenses_map:
            expenses_map[ym] = float(row["total_amount"] or 0)

    sales_data = [round(sales_map[key], 2) for key in month_keys]
    receipts_data = [round(receipts_map[key], 2) for key in month_keys]
    expenses_data = [round(expenses_map[key], 2) for key in month_keys]

    conn.close()

    return render_template(
        "billing/dashboard.html",
        branches=branches,
        branch_id=branch_id,
        period=period,
        start_date=start_date,
        end_date=end_date,
        total_students=total_students,
        total_invoices=total_invoices,
        total_sales=total_sales,
        total_receipts=total_receipts,
        total_expenses=total_expenses,
        net_position=net_position,
        total_receivables=total_receivables,
        current_amount=current_amount,
        bucket_1_15=bucket_1_15,
        bucket_16_30=bucket_16_30,
        bucket_31_45=bucket_31_45,
        bucket_above_45=bucket_above_45,
        month_labels=month_labels,
        sales_data=sales_data,
        receipts_data=receipts_data,
        expenses_data=expenses_data
    )

@billing_bp.route("/student/<int:student_id>/enrollment-agreement/<int:invoice_id>")
@login_required
def student_enrollment_agreement(student_id, invoice_id):
    """Display printable enrollment agreement for student"""
    conn = get_conn()
    cur = conn.cursor()

    # Fetch student details
    cur.execute("""
        SELECT
            students.*,
            branches.branch_name
        FROM students
        LEFT JOIN branches ON students.branch_id = branches.id
        WHERE students.id = ?
    """, (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("billing.students"))

    # Fetch invoice details
    cur.execute("""
        SELECT *
        FROM invoices
        WHERE id = ? AND student_id = ?
    """, (invoice_id, student_id))
    invoice = cur.fetchone()

    if not invoice:
        conn.close()
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing.student_profile", student_id=student_id))

    # Fetch invoice items (courses)
    cur.execute("""
        SELECT *
        FROM invoice_items
        WHERE invoice_id = ?
        ORDER BY id
    """, (invoice_id,))
    invoice_items = cur.fetchall()

    # Fetch installment plans for this invoice
    cur.execute("""
        SELECT *
        FROM installment_plans
        WHERE invoice_id = ?
        ORDER BY installment_no ASC
    """, (invoice_id,))
    installment_plans = cur.fetchall()

    # Fetch total paid for this invoice
    cur.execute("""
        SELECT IFNULL(SUM(amount_received), 0) AS total_paid
        FROM receipts
        WHERE invoice_id = ?
    """, (invoice_id,))
    payment_info = cur.fetchone()
    total_paid = float(payment_info["total_paid"] or 0)
    balance = float(invoice["total_amount"] or 0) - total_paid

    conn.close()

    return render_template(
        "billing/student_enrollment_agreement.html",
        student=student,
        invoice=invoice,
        invoice_items=invoice_items,
        installment_plans=installment_plans,
        total_paid=total_paid,
        balance=balance
    )

@billing_bp.route("/students")
@login_required
def students():
    conn = get_conn()
    cur = conn.cursor()

    # Get search and filter parameters
    search_query = request.args.get("search", "").strip()
    branch_filter = request.args.get("branch", "").strip()
    status_filter = request.args.get("status", "").strip()
    batch_filter = request.args.get("batch", "").strip()

    # Get student statistics
    cur.execute("""
        SELECT 
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_count,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
            SUM(CASE WHEN status = 'dropped' THEN 1 ELSE 0 END) AS dropped_count,
            COUNT(*) AS total_count
        FROM students
    """)
    stats = cur.fetchone()

    # Get branch-wise student statistics
    cur.execute("""
        SELECT 
            branches.id AS branch_id,
            branches.branch_name,
            branches.branch_code,
            SUM(CASE WHEN students.status = 'active' THEN 1 ELSE 0 END) AS active_count,
            SUM(CASE WHEN students.status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
            SUM(CASE WHEN students.status = 'dropped' THEN 1 ELSE 0 END) AS dropped_count,
            COUNT(students.id) AS total_count
        FROM branches
        LEFT JOIN students ON branches.id = students.branch_id
        WHERE branches.is_active = 1
        GROUP BY branches.id, branches.branch_name, branches.branch_code
        ORDER BY branches.branch_name
    """)
    branch_stats = cur.fetchall()

    # Build student list query
    query = """
        SELECT
            students.*,
            branches.branch_name,
            branches.branch_code
        FROM students
        LEFT JOIN branches
            ON students.branch_id = branches.id
        WHERE 1=1
    """
    params = []

    # Search filter
    if search_query:
        query += """
            AND (
                students.full_name LIKE ?
                OR students.phone LIKE ?
                OR students.email LIKE ?
                OR students.student_code LIKE ?
            )
        """
        search_param = f"%{search_query}%"
        params.extend([search_param, search_param, search_param, search_param])

    # Branch filter
    if branch_filter:
        query += " AND students.branch_id = ?"
        params.append(branch_filter)

    # Status filter
    if status_filter == 'active_completed_batch':
        # Active students who have completed ALL their batches (no active batches remaining)
        query += """ AND students.status = 'active'
            AND students.id IN (
                SELECT DISTINCT sb.student_id
                FROM student_batches sb
                JOIN batches b ON sb.batch_id = b.id
                WHERE b.status = 'completed'
            )
            AND students.id NOT IN (
                SELECT DISTINCT sb.student_id
                FROM student_batches sb
                JOIN batches b ON sb.batch_id = b.id
                WHERE b.status = 'active'
            )"""
    elif status_filter:
        query += " AND students.status = ?"
        params.append(status_filter)

    # Batch filter
    if batch_filter == 'none':
        query += """ AND students.id NOT IN (
            SELECT DISTINCT student_id FROM student_batches
        )"""
    elif batch_filter == 'unassigned':
        query += """ AND students.status = 'active'
            AND students.id NOT IN (
                SELECT DISTINCT sb.student_id
                FROM student_batches sb
                JOIN batches b ON b.id = sb.batch_id
                WHERE sb.status = 'active'
                  AND LOWER(COALESCE(b.status, '')) = 'active'
                  AND b.trainer_id IS NOT NULL
            )"""
    elif batch_filter:
        query += """ AND students.id IN (
            SELECT student_id FROM student_batches WHERE batch_id = ?
        )"""
        params.append(batch_filter)

    query += " ORDER BY students.id DESC"

    cur.execute(query, params)
    students = cur.fetchall()

    # Build batch lookup for all returned students (single query, no N+1)
    student_batches_map = {}
    if students:
        student_ids = [s['id'] for s in students]
        placeholders = ','.join('?' * len(student_ids))
        cur.execute(f"""
            SELECT sb.student_id, b.id AS batch_id, b.batch_name
            FROM student_batches sb
            JOIN batches b ON sb.batch_id = b.id
            WHERE sb.student_id IN ({placeholders})
            AND sb.status = 'active'
            ORDER BY sb.student_id, b.batch_name
        """, student_ids)
        for row in cur.fetchall():
            sid = row['student_id']
            if sid not in student_batches_map:
                student_batches_map[sid] = []
            student_batches_map[sid].append({
                'batch_id': row['batch_id'],
                'batch_name': row['batch_name']
            })

    # Build course lookups for all returned students (single query, no N+1)
    student_batch_courses_map = {}
    student_invoiced_courses_map = {}
    if students:
        student_ids = [s['id'] for s in students]
        placeholders = ','.join('?' * len(student_ids))

        # 1) Active batch course mappings
        cur.execute(f"""
            SELECT DISTINCT sb.student_id, c.course_name
            FROM student_batches sb
            JOIN batches b ON sb.batch_id = b.id
            LEFT JOIN courses c ON b.course_id = c.id
            WHERE sb.student_id IN ({placeholders})
              AND sb.status = 'active'
              AND c.course_name IS NOT NULL
              AND TRIM(c.course_name) <> ''
            ORDER BY sb.student_id, c.course_name
        """, student_ids)

        for row in cur.fetchall():
            sid = row['student_id']
            if sid not in student_batch_courses_map:
                student_batch_courses_map[sid] = []
            student_batch_courses_map[sid].append(row['course_name'])

        # 2) Invoiced course lines
        cur.execute(f"""
            SELECT DISTINCT i.student_id,
                   COALESCE(c.course_name, ii.description) AS course_name
            FROM invoices i
            JOIN invoice_items ii ON i.id = ii.invoice_id
            LEFT JOIN courses c ON ii.course_id = c.id
            WHERE i.student_id IN ({placeholders})
              AND COALESCE(c.course_name, ii.description) IS NOT NULL
              AND TRIM(COALESCE(c.course_name, ii.description)) <> ''
            ORDER BY i.student_id, course_name
        """, student_ids)

        for row in cur.fetchall():
            sid = row['student_id']
            cname = row['course_name']
            if sid not in student_invoiced_courses_map:
                student_invoiced_courses_map[sid] = []
            if cname not in student_invoiced_courses_map[sid]:
                student_invoiced_courses_map[sid].append(cname)

    # Branches for filter dropdown
    cur.execute("""
        SELECT id, branch_name, branch_code
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    # All batches for filter dropdown
    cur.execute("""
        SELECT id, batch_name, status
        FROM batches
        ORDER BY batch_name
    """)
    all_batches = cur.fetchall()

    conn.close()

    return render_template(
        "billing/students.html",
        students=students,
        branches=branches,
        all_batches=all_batches,
        search_query=search_query,
        branch_filter=branch_filter,
        status_filter=status_filter,
        batch_filter=batch_filter,
        stats=stats,
        branch_stats=branch_stats,
        student_batches_map=student_batches_map,
        student_batch_courses_map=student_batch_courses_map,
        student_invoiced_courses_map=student_invoiced_courses_map
    )


@billing_bp.route("/students/batch-progress")
@login_required
def student_batch_progress_monitor():
    """Visual batch-wise student monitor with LMS progress signals."""
    conn = get_conn()
    cur = conn.cursor()

    current_user_id = session.get("user_id")
    session_role = (session.get("role") or "").strip().lower()

    cur.execute(
        "SELECT id, role, branch_id, can_view_all_branches FROM users WHERE id = ?",
        (current_user_id,)
    )
    current_user = cur.fetchone()

    role = (current_user["role"] if current_user else session_role) or session_role
    user_branch_id = current_user["branch_id"] if current_user else session.get("branch_id")
    can_view_all = int((current_user["can_view_all_branches"] if current_user else session.get("can_view_all_branches", 0)) or 0)
    is_admin = role == "admin"

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM batches WHERE trainer_id = ? AND status IN ('active', 'completed')",
        (current_user_id,)
    )
    trainer_batch_count = cur.fetchone()["cnt"] or 0
    trainer_scoped = (not is_admin) and trainer_batch_count > 0 and not can_view_all

    filters = {
        "course_id": request.args.get("course_id", "").strip(),
        "batch_id": request.args.get("batch_id", "").strip(),
        "branch_id": request.args.get("branch_id", "").strip(),
        "trainer_id": request.args.get("trainer_id", "").strip(),
        "progress": request.args.get("progress", "").strip(),
        "student_status": request.args.get("student_status", "").strip(),
        "q": request.args.get("q", "").strip(),
        "view": request.args.get("view", "cards").strip() or "cards",
    }
    if filters["view"] not in {"cards", "table"}:
        filters["view"] = "cards"

    if (not is_admin) and (not can_view_all) and user_branch_id:
        filters["branch_id"] = str(user_branch_id)
    if trainer_scoped:
        filters["trainer_id"] = str(current_user_id)

    branch_dropdown_sql = "SELECT id, branch_name FROM branches WHERE is_active = 1"
    branch_dropdown_params = []
    if (not is_admin) and (not can_view_all) and user_branch_id:
        branch_dropdown_sql += " AND id = ?"
        branch_dropdown_params.append(user_branch_id)
    branch_dropdown_sql += " ORDER BY branch_name"
    branches = cur.execute(branch_dropdown_sql, branch_dropdown_params).fetchall()

    courses = cur.execute("""
        SELECT id, course_name
        FROM courses
        WHERE is_active = 1
        ORDER BY course_name
    """).fetchall()

    trainer_dropdown_sql = """
        SELECT DISTINCT u.id, u.full_name
        FROM users u
        JOIN batches b ON b.trainer_id = u.id
        WHERE u.is_active = 1 AND b.status IN ('active', 'completed')
    """
    trainer_dropdown_params = []
    if trainer_scoped:
        trainer_dropdown_sql += " AND u.id = ?"
        trainer_dropdown_params.append(current_user_id)
    elif (not is_admin) and (not can_view_all) and user_branch_id:
        trainer_dropdown_sql += " AND b.branch_id = ?"
        trainer_dropdown_params.append(user_branch_id)
    trainer_dropdown_sql += " ORDER BY u.full_name"
    trainers = cur.execute(trainer_dropdown_sql, trainer_dropdown_params).fetchall()

    batch_dropdown_sql = """
        SELECT b.id, b.batch_name, b.start_time, b.end_time, c.course_name, br.branch_name
        FROM batches b
        LEFT JOIN courses c ON c.id = b.course_id
        LEFT JOIN branches br ON br.id = b.branch_id
        WHERE b.status IN ('active', 'completed')
    """
    batch_dropdown_params = []
    if filters["branch_id"].isdigit():
        batch_dropdown_sql += " AND b.branch_id = ?"
        batch_dropdown_params.append(int(filters["branch_id"]))
    elif (not is_admin) and (not can_view_all) and user_branch_id:
        batch_dropdown_sql += " AND b.branch_id = ?"
        batch_dropdown_params.append(user_branch_id)
    if trainer_scoped:
        batch_dropdown_sql += " AND b.trainer_id = ?"
        batch_dropdown_params.append(current_user_id)
    batch_dropdown_sql += " ORDER BY b.start_time, b.batch_name"
    batches = cur.execute(batch_dropdown_sql, batch_dropdown_params).fetchall()

    master_check = """EXISTS (
        SELECT 1
        FROM lms_program_chapters pcx
        JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
        JOIN lms_master_topics mtx ON mtx.master_chapter_id = mcx.id
        WHERE pcx.program_id = lp.id
          AND pcx.is_visible = 1
          AND mcx.status = 'active'
          AND mtx.status = 'active'
    )"""

    where_clauses = ["sb.status IN ('active', 'completed')", "b.status IN ('active', 'completed')"]
    params = []

    if filters["course_id"].isdigit():
        where_clauses.append("c.id = ?")
        params.append(int(filters["course_id"]))

    if filters["batch_id"].isdigit():
        where_clauses.append("b.id = ?")
        params.append(int(filters["batch_id"]))

    if filters["branch_id"].isdigit():
        where_clauses.append("(b.branch_id = ? OR s.branch_id = ?)")
        params.extend([int(filters["branch_id"]), int(filters["branch_id"])])

    if filters["trainer_id"].isdigit() and (is_admin or can_view_all or trainer_scoped):
        where_clauses.append("b.trainer_id = ?")
        params.append(int(filters["trainer_id"]))

    if filters["q"]:
        where_clauses.append("(s.full_name LIKE ? OR s.phone LIKE ? OR s.student_code LIKE ?)")
        search_term = f"%{filters['q']}%"
        params.extend([search_term, search_term, search_term])

    if trainer_scoped and not filters["trainer_id"].isdigit():
        where_clauses.append("b.trainer_id = ?")
        params.append(current_user_id)
    elif (not is_admin) and (not can_view_all) and user_branch_id and not filters["branch_id"].isdigit():
        where_clauses.append("(b.branch_id = ? OR s.branch_id = ?)")
        params.extend([user_branch_id, user_branch_id])

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        WITH batch_programs AS (
            SELECT b.id AS batch_id, lp.id AS program_id
            FROM batches b
            JOIN lms_programs lp ON lp.course_id = b.course_id
            WHERE lp.is_active = 1 AND lp.is_deleted = 0
            UNION
            SELECT bpa.batch_id, bpa.program_id
            FROM lms_batch_program_access bpa
            JOIN lms_programs lp ON lp.id = bpa.program_id
            WHERE bpa.is_active = 1
              AND lp.is_active = 1
              AND lp.is_deleted = 0
              AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
            UNION
            SELECT b.id AS batch_id, cpm.program_id
            FROM batches b
            JOIN lms_course_program_map cpm ON cpm.course_id = b.course_id
            JOIN lms_programs lp ON lp.id = cpm.program_id
            WHERE lp.is_active = 1 AND lp.is_deleted = 0
        )
        SELECT
            s.id AS student_id,
            s.student_code,
            s.full_name,
            s.phone,
            s.status AS student_status,
            s.photo_filename,
            sb.status AS student_batch_status,
            b.id AS batch_id,
            b.batch_name,
            b.status AS batch_status,
            b.start_time,
            b.end_time,
            c.id AS course_id,
            COALESCE(c.course_name, lp.program_name, 'Course not mapped') AS course_name,
            br.branch_name,
            u.id AS trainer_id,
            COALESCE(u.full_name, 'Unassigned') AS trainer_name,
            lp.id AS program_id,
            lp.program_name,
            CASE WHEN lp.id IS NULL THEN 0 WHEN {master_check} THEN (
                SELECT COUNT(*)
                FROM lms_master_topics mt
                JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE pc.program_id = lp.id
                  AND pc.is_visible = 1
                  AND mc.status = 'active'
                  AND mt.status = 'active'
            ) ELSE (
                SELECT COUNT(*)
                FROM lms_topics lt
                JOIN lms_chapters lc ON lt.chapter_id = lc.id
                WHERE lc.program_id = lp.id
                  AND lt.is_active = 1
            ) END AS total_topics,
            CASE WHEN lp.id IS NULL THEN 0 WHEN {master_check} THEN (
                SELECT COUNT(*)
                FROM lms_master_topic_progress mtp
                JOIN lms_master_topics mt ON mt.id = mtp.master_topic_id
                JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE mtp.student_id = s.id
                  AND mtp.program_id = lp.id
                  AND mtp.is_completed = 1
                  AND pc.program_id = lp.id
                  AND pc.is_visible = 1
                  AND mc.status = 'active'
                  AND mt.status = 'active'
            ) ELSE (
                SELECT COUNT(*)
                FROM lms_topic_progress tp
                JOIN lms_topics lt ON tp.topic_id = lt.id
                JOIN lms_chapters lc ON lt.chapter_id = lc.id
                WHERE tp.student_id = s.id
                  AND lc.program_id = lp.id
                  AND tp.is_completed = 1
            ) END AS completed_topics,
            CASE WHEN lp.id IS NULL THEN NULL ELSE (
                SELECT MAX(last_act) FROM (
                    SELECT MAX(tp.completed_at) AS last_act
                    FROM lms_topic_progress tp
                    JOIN lms_topics lt ON tp.topic_id = lt.id
                    JOIN lms_chapters lc ON lt.chapter_id = lc.id
                    WHERE tp.student_id = s.id
                      AND lc.program_id = lp.id
                      AND tp.is_completed = 1
                    UNION ALL
                    SELECT MAX(mtp.completed_at) AS last_act
                    FROM lms_master_topic_progress mtp
                    WHERE mtp.student_id = s.id
                      AND mtp.program_id = lp.id
                      AND mtp.is_completed = 1
                )
            ) END AS last_activity
        FROM student_batches sb
        JOIN students s ON s.id = sb.student_id
        JOIN batches b ON b.id = sb.batch_id
        LEFT JOIN courses c ON c.id = b.course_id
        LEFT JOIN branches br ON br.id = b.branch_id
        LEFT JOIN users u ON u.id = b.trainer_id
        LEFT JOIN batch_programs bp ON bp.batch_id = b.id
        LEFT JOIN lms_programs lp ON lp.id = bp.program_id
        WHERE {where_sql}
        ORDER BY
            CASE WHEN sb.status = 'active' AND b.status = 'active' THEN 0
                 WHEN sb.status = 'active' THEN 1
                 ELSE 2
            END,
            COALESCE(sb.updated_at, sb.joined_on, b.start_date, b.created_at) DESC,
            b.start_time,
            b.batch_name,
            s.full_name,
            lp.program_name
    """
    rows = cur.execute(sql, params).fetchall()

    student_trainer_map = {}
    student_ids = sorted({row["student_id"] for row in rows})
    if student_ids:
        placeholders = ",".join("?" for _ in student_ids)
        trainer_rows = cur.execute(f"""
            SELECT
                sb.student_id,
                COALESCE(NULLIF(TRIM(u.full_name), ''), NULLIF(TRIM(u.username), ''), 'Unassigned') AS trainer_name
            FROM student_batches sb
            JOIN batches b ON b.id = sb.batch_id
            LEFT JOIN users u ON u.id = b.trainer_id
            WHERE sb.student_id IN ({placeholders})
              AND sb.status IN ('active', 'completed')
              AND b.status IN ('active', 'completed')
            ORDER BY
                sb.student_id,
                CASE WHEN sb.status = 'active' AND b.status = 'active' THEN 0
                     WHEN sb.status = 'active' THEN 1
                     ELSE 2
                END,
                COALESCE(sb.updated_at, sb.joined_on, b.start_date, b.created_at) DESC,
                b.id DESC
        """, student_ids).fetchall()

        trainer_names_by_student = {}
        for trainer_row in trainer_rows:
            sid = trainer_row["student_id"]
            trainer_name = trainer_row["trainer_name"] or "Unassigned"
            trainer_names_by_student.setdefault(sid, [])
            if trainer_name not in trainer_names_by_student[sid]:
                trainer_names_by_student[sid].append(trainer_name)

        for sid, names in trainer_names_by_student.items():
            student_trainer_map[sid] = " / ".join(names) if len(names) > 1 else names[0]

    conn.close()

    def _batch_time(row):
        start_time = row["start_time"] or ""
        end_time = row["end_time"] or ""
        if start_time and end_time:
            return f"{start_time} - {end_time}"
        return start_time or end_time or "Time not set"

    def _initials(name):
        pieces = [p for p in (name or "").split() if p]
        if not pieces:
            return "ST"
        return "".join(p[0].upper() for p in pieces[:2])

    def _progress_class(pct, total, done):
        if total <= 0 or done <= 0:
            return "not-started"
        if pct >= 75:
            return "high"
        if pct >= 50:
            return "mid"
        if pct >= 25:
            return "low"
        return "critical"

    def _progress_label(pct, total, done):
        if total <= 0 or done <= 0:
            return "Not Started"
        if pct >= 100:
            return "Completed"
        if pct >= 75:
            return "Above 75%"
        if pct >= 50:
            return "50% to 75%"
        if pct >= 25:
            return "25% to 50%"
        return "Below 25%"

    def _monitor_status(group, fallback_status):
        fallback = (fallback_status or "active").strip().lower()
        if fallback == "dropped":
            return "dropped"
        if group["has_active_batch"]:
            return "active"
        if group["has_completed_batch"]:
            return "completed"
        return fallback or "active"

    def _existing_photo_filename(filename):
        photo_filename = (filename or "").strip()
        if not photo_filename:
            return None

        safe_filename = os.path.basename(photo_filename)
        photo_path = os.path.join(
            current_app.root_path,
            "static",
            "images",
            "student_photos",
            safe_filename
        )
        return safe_filename if os.path.isfile(photo_path) else None

    grouped_rows = {}
    for row in rows:
        group_key = row["student_id"]
        if group_key not in grouped_rows:
            grouped_rows[group_key] = {
                "row": row,
                "course_names": [],
                "batch_names": [],
                "batch_times": [],
                "branch_names": [],
                "seen_batches": set(),
                "program_ids": [],
                "program_names": [],
                "seen_programs": set(),
                "total_topics": 0,
                "completed_topics": 0,
                "last_activity": None,
                "has_active_batch": False,
                "has_completed_batch": False,
            }

        group = grouped_rows[group_key]

        batch_key = row["batch_id"]
        if batch_key not in group["seen_batches"]:
            group["seen_batches"].add(batch_key)
            student_batch_status = (row["student_batch_status"] or "").strip().lower()
            batch_status = (row["batch_status"] or "").strip().lower()
            if student_batch_status == "active" and batch_status == "active":
                group["has_active_batch"] = True
            if student_batch_status == "completed" or batch_status == "completed":
                group["has_completed_batch"] = True
            if row["course_name"] and row["course_name"] not in group["course_names"]:
                group["course_names"].append(row["course_name"])
            if row["batch_name"] and row["batch_name"] not in group["batch_names"]:
                group["batch_names"].append(row["batch_name"])
            batch_time = _batch_time(row)
            if batch_time and batch_time not in group["batch_times"]:
                group["batch_times"].append(batch_time)
            if row["branch_name"] and row["branch_name"] not in group["branch_names"]:
                group["branch_names"].append(row["branch_name"])

        program_key = row["program_id"] if row["program_id"] is not None else "no_program"
        if program_key not in group["seen_programs"]:
            group["seen_programs"].add(program_key)
            group["total_topics"] += int(row["total_topics"] or 0)
            group["completed_topics"] += int(row["completed_topics"] or 0)
            if row["program_id"] is not None:
                group["program_ids"].append(row["program_id"])
            if row["program_name"] and row["program_name"] not in group["program_names"]:
                group["program_names"].append(row["program_name"])

        last_activity = row["last_activity"]
        if last_activity and (
            not group["last_activity"] or str(last_activity) > str(group["last_activity"])
        ):
            group["last_activity"] = last_activity

    monitor_rows = []
    for group in grouped_rows.values():
        row = group["row"]
        total = group["total_topics"]
        done = group["completed_topics"]
        pct = round((done / total) * 100, 1) if total > 0 else 0.0
        photo_filename = _existing_photo_filename(row["photo_filename"])
        program_ids = group["program_ids"]
        program_names = group["program_names"]
        program_id = program_ids[0] if len(program_ids) == 1 else None
        program_name = " / ".join(program_names) if program_names else "LMS not mapped"
        course_name = " / ".join(group["course_names"]) if group["course_names"] else row["course_name"]
        batch_name = " / ".join(group["batch_names"]) if group["batch_names"] else row["batch_name"]
        batch_time = " / ".join(group["batch_times"]) if group["batch_times"] else _batch_time(row)
        branch_name = " / ".join(group["branch_names"]) if group["branch_names"] else "Unassigned"
        monitor_status = _monitor_status(group, row["student_status"])
        item = {
            "student_id": row["student_id"],
            "student_code": row["student_code"],
            "full_name": row["full_name"],
            "phone": row["phone"],
            "student_status": monitor_status,
            "photo_filename": photo_filename,
            "initials": _initials(row["full_name"]),
            "batch_id": row["batch_id"],
            "batch_name": batch_name,
            "batch_time": batch_time,
            "course_name": course_name,
            "branch_name": branch_name,
            "trainer_name": student_trainer_map.get(row["student_id"]) or row["trainer_name"] or "Unassigned",
            "program_id": program_id,
            "program_name": program_name,
            "total_topics": total,
            "completed_topics": done,
            "progress_pct": pct,
            "progress_class": _progress_class(pct, total, done),
            "progress_label": _progress_label(pct, total, done),
            "last_activity": _format_display_datetime(group["last_activity"]) if group["last_activity"] else "Not Started",
        }
        monitor_rows.append(item)

    progress_filter = filters["progress"]
    if progress_filter:
        def _matches_progress(item):
            pct = item["progress_pct"]
            total = item["total_topics"]
            done = item["completed_topics"]
            if progress_filter == "not_started":
                return total <= 0 or done <= 0
            if progress_filter == "below_25":
                return done > 0 and pct < 25
            if progress_filter == "25_50":
                return 25 <= pct < 50
            if progress_filter == "50_75":
                return 50 <= pct < 75
            if progress_filter == "above_75":
                return 75 <= pct < 100
            if progress_filter == "completed":
                return pct >= 100
            return True
        monitor_rows = [item for item in monitor_rows if _matches_progress(item)]

    status_filter = filters["student_status"]
    if status_filter in {"active", "completed", "dropped"}:
        monitor_rows = [
            item for item in monitor_rows
            if (item["student_status"] or "").strip().lower() == status_filter
        ]

    unique_student_count = len({item["student_id"] for item in monitor_rows})
    avg_progress = round(
        sum(item["progress_pct"] for item in monitor_rows) / len(monitor_rows),
        1
    ) if monitor_rows else 0
    not_started_count = sum(1 for item in monitor_rows if item["completed_topics"] <= 0)
    support_needed_count = sum(1 for item in monitor_rows if item["progress_pct"] < 25)
    completed_count = sum(1 for item in monitor_rows if item["progress_pct"] >= 100)

    base_url_args = {
        "course_id": filters["course_id"],
        "batch_id": filters["batch_id"],
        "branch_id": filters["branch_id"],
        "trainer_id": filters["trainer_id"],
        "progress": filters["progress"],
        "student_status": filters["student_status"],
        "q": filters["q"],
    }

    return render_template(
        "billing/student_batch_progress_monitor.html",
        rows=monitor_rows,
        filters=filters,
        branches=branches,
        courses=courses,
        batches=batches,
        trainers=trainers,
        unique_student_count=unique_student_count,
        avg_progress=avg_progress,
        not_started_count=not_started_count,
        support_needed_count=support_needed_count,
        completed_count=completed_count,
        card_view_url=url_for("billing.student_batch_progress_monitor", **base_url_args, view="cards"),
        table_view_url=url_for("billing.student_batch_progress_monitor", **base_url_args, view="table"),
        live_batches_url=url_for("attendance.dashboard", branch_id=filters["branch_id"] or None, trainer_id=filters["trainer_id"] or None),
        day_overview_url=url_for("billing.institute_day_overview", date=_ist_now().strftime("%Y-%m-%d"), branch_id=filters["branch_id"], trainer_id=filters["trainer_id"], course_id=filters["course_id"], batch_status="", occupancy_status=""),
        can_mark_followup=True,
        trainer_scoped=trainer_scoped,
        role=role,
    )


def _build_institute_day_overview(cur, filters, user, role):
    selected_date = datetime.strptime(filters["date"], "%Y-%m-%d").date()
    now_dt = _ist_now()
    today = now_dt.date()
    now_minutes = now_dt.hour * 60 + now_dt.minute
    is_today = selected_date == today

    is_admin = (role or "").strip().lower() == "admin"
    can_view_all = int((user["can_view_all_branches"] if user else 0) or 0)
    user_branch_id = user["branch_id"] if user else None

    branch_sql = """
        SELECT id, branch_name, no_of_computers, opening_time, closing_time
        FROM branches
        WHERE is_active = 1
    """
    branch_params = []
    if (not is_admin) and (not can_view_all) and user_branch_id:
        branch_sql += " AND id = ?"
        branch_params.append(user_branch_id)
    branch_sql += " ORDER BY branch_name"
    branches = cur.execute(branch_sql, branch_params).fetchall()

    courses = cur.execute("""
        SELECT id, course_name
        FROM courses
        WHERE is_active = 1
        ORDER BY course_name
    """).fetchall()

    trainer_sql = """
        SELECT DISTINCT u.id, COALESCE(NULLIF(TRIM(u.full_name), ''), u.username) AS full_name
        FROM users u
        JOIN batches b ON b.trainer_id = u.id
        WHERE u.is_active = 1
          AND b.status = 'active'
    """
    trainer_params = []
    if (not is_admin) and (not can_view_all) and user_branch_id:
        trainer_sql += " AND b.branch_id = ?"
        trainer_params.append(user_branch_id)
    trainer_sql += " ORDER BY full_name"
    trainers = cur.execute(trainer_sql, trainer_params).fetchall()

    selected_branch_id = filters["branch_id"]
    accessible_branch_ids = [branch["id"] for branch in branches]
    if selected_branch_id.isdigit():
        requested_branch_id = int(selected_branch_id)
        if requested_branch_id in accessible_branch_ids:
            selected_branch_ids = [requested_branch_id]
        else:
            selected_branch_ids = []
    else:
        selected_branch_ids = accessible_branch_ids

    branch_by_id = {
        branch["id"]: {
            "id": branch["id"],
            "branch_name": branch["branch_name"],
            "no_of_computers": int(branch["no_of_computers"] or 0),
            "opening_time": branch["opening_time"],
            "closing_time": branch["closing_time"],
        }
        for branch in branches
        if branch["id"] in selected_branch_ids
    }

    opening_candidates = [
        _parse_time_minutes(branch["opening_time"])
        for branch in branch_by_id.values()
        if _parse_time_minutes(branch["opening_time"]) is not None
    ]
    closing_candidates = [
        _parse_time_minutes(branch["closing_time"])
        for branch in branch_by_id.values()
        if _parse_time_minutes(branch["closing_time"]) is not None
    ]
    office_open = min(opening_candidates) if opening_candidates else 9 * 60
    office_close = max(closing_candidates) if closing_candidates else 21 * 60
    if office_close <= office_open:
        office_close = office_open + (12 * 60)

    batch_where = [
        "b.status = 'active'",
        "(b.start_date IS NULL OR date(b.start_date) <= date(?))",
        "(b.end_date IS NULL OR date(b.end_date) >= date(?))",
    ]
    batch_params = [filters["date"], filters["date"]]

    if selected_branch_ids:
        placeholders = ",".join("?" for _ in selected_branch_ids)
        batch_where.append(f"b.branch_id IN ({placeholders})")
        batch_params.extend(selected_branch_ids)
    else:
        batch_where.append("1 = 0")

    if filters["trainer_id"].isdigit():
        batch_where.append("b.trainer_id = ?")
        batch_params.append(int(filters["trainer_id"]))

    if filters["course_id"].isdigit():
        batch_where.append("b.course_id = ?")
        batch_params.append(int(filters["course_id"]))

    batch_rows = cur.execute(f"""
        SELECT
            b.id,
            b.batch_name,
            b.branch_id,
            b.course_id,
            b.start_date,
            b.end_date,
            b.start_time,
            b.end_time,
            COALESCE(c.course_name, 'Course not mapped') AS course_name,
            COALESCE(br.branch_name, 'Branch not mapped') AS branch_name,
            COALESCE(NULLIF(TRIM(u.full_name), ''), u.username, 'Unassigned') AS trainer_name,
            COALESCE(br.no_of_computers, 0) AS no_of_computers
        FROM batches b
        LEFT JOIN courses c ON c.id = b.course_id
        LEFT JOIN branches br ON br.id = b.branch_id
        LEFT JOIN users u ON u.id = b.trainer_id
        WHERE {" AND ".join(batch_where)}
        ORDER BY b.start_time, b.end_time, b.batch_name
    """, batch_params).fetchall()

    batch_ids = [row["id"] for row in batch_rows]
    students_by_batch = {batch_id: [] for batch_id in batch_ids}
    unique_student_ids = set()

    if batch_ids:
        placeholders = ",".join("?" for _ in batch_ids)
        student_rows = cur.execute(f"""
            SELECT
                sb.batch_id,
                s.id AS student_id,
                s.student_code,
                s.full_name,
                s.phone,
                s.photo_filename,
                COALESCE(c.course_name, 'Course not mapped') AS course_name,
                b.start_time,
                b.end_time,
                COALESCE(ar.status, 'not_marked') AS attendance_status
            FROM student_batches sb
            JOIN students s ON s.id = sb.student_id
            JOIN batches b ON b.id = sb.batch_id
            LEFT JOIN courses c ON c.id = b.course_id
            LEFT JOIN attendance_records ar
              ON ar.student_id = s.id
             AND ar.batch_id = sb.batch_id
             AND ar.attendance_date = ?
            WHERE sb.status = 'active'
              AND sb.batch_id IN ({placeholders})
            ORDER BY s.full_name
        """, [filters["date"], *batch_ids]).fetchall()

        seen_batch_students = set()
        for row in student_rows:
            key = (row["batch_id"], row["student_id"])
            if key in seen_batch_students:
                continue
            seen_batch_students.add(key)
            unique_student_ids.add(row["student_id"])
            students_by_batch.setdefault(row["batch_id"], []).append({
                "student_id": row["student_id"],
                "student_code": row["student_code"],
                "full_name": row["full_name"],
                "phone": row["phone"],
                "photo_filename": _existing_student_photo(row["photo_filename"]),
                "initials": _initials_from_name(row["full_name"]),
                "course_name": row["course_name"],
                "batch_time": _format_time_range(row["start_time"], row["end_time"]),
                "attendance_status": row["attendance_status"] or "not_marked",
            })

    def day_status(start_minutes, end_minutes):
        if selected_date < today:
            return "completed"
        if selected_date > today:
            return "upcoming"
        if start_minutes is None or end_minutes is None:
            return "upcoming"
        if now_minutes < start_minutes:
            return "upcoming"
        if now_minutes > end_minutes:
            return "completed"
        return "live"

    batch_cards = []
    for row in batch_rows:
        start_minutes = _parse_time_minutes(row["start_time"])
        end_minutes = _parse_time_minutes(row["end_time"])
        student_list = students_by_batch.get(row["id"], [])
        computer_count = int(row["no_of_computers"] or 0)
        occupancy = _occupancy_status(len(student_list), computer_count)
        status_key = day_status(start_minutes, end_minutes)

        batch_cards.append({
            "id": row["id"],
            "batch_name": row["batch_name"],
            "batch_time": _format_time_range(row["start_time"], row["end_time"]),
            "start_minutes": start_minutes,
            "end_minutes": end_minutes,
            "trainer_name": row["trainer_name"],
            "course_name": row["course_name"],
            "branch_id": row["branch_id"],
            "branch_name": row["branch_name"],
            "student_count": len(student_list),
            "computer_count": computer_count,
            "occupancy_pct": occupancy["percentage"],
            "occupancy_key": occupancy["key"],
            "occupancy_label": occupancy["label"],
            "status_key": status_key,
            "status_label": status_key.capitalize(),
            "students_preview": student_list[:5],
            "more_count": max(0, len(student_list) - 5),
        })

    if filters["batch_status"] in {"live", "completed", "upcoming"}:
        batch_cards = [
            batch for batch in batch_cards
            if batch["status_key"] == filters["batch_status"]
        ]

    if filters["occupancy_status"] in {"free", "normal", "busy", "over"}:
        batch_cards = [
            batch for batch in batch_cards
            if batch["occupancy_key"] == filters["occupancy_status"]
        ]

    visible_batch_ids = {batch["id"] for batch in batch_cards}
    visible_students_by_batch = {
        str(batch_id): students
        for batch_id, students in students_by_batch.items()
        if batch_id in visible_batch_ids
    }
    visible_unique_student_ids = {
        student["student_id"]
        for batch_id, students in students_by_batch.items()
        if batch_id in visible_batch_ids
        for student in students
    }

    slot_minutes = list(range(office_open, office_close + 1, 60))
    if not slot_minutes or slot_minutes[-1] != office_close:
        slot_minutes.append(office_close)

    total_computers = sum(branch["no_of_computers"] for branch in branch_by_id.values())
    chart_students = []
    for slot in slot_minutes:
        slot_students = set()
        for batch in batch_cards:
            if batch["start_minutes"] is None or batch["end_minutes"] is None:
                continue
            if batch["start_minutes"] <= slot < batch["end_minutes"]:
                for student in students_by_batch.get(batch["id"], []):
                    slot_students.add(student["student_id"])
        chart_students.append(len(slot_students))

    average_students = round(sum(chart_students) / len(chart_students), 1) if chart_students else 0
    average_occupancy = round((average_students / total_computers) * 100, 1) if total_computers > 0 else 0
    peak_count = max(chart_students) if chart_students else 0
    low_count = min(chart_students) if chart_students else 0
    peak_index = chart_students.index(peak_count) if chart_students else 0
    low_index = chart_students.index(low_count) if chart_students else 0

    branch_summaries = []
    for branch_id, branch in branch_by_id.items():
        branch_students_now = set()
        for batch in batch_cards:
            if batch["branch_id"] != branch_id:
                continue
            if not is_today:
                continue
            if batch["start_minutes"] is None or batch["end_minutes"] is None:
                continue
            if batch["start_minutes"] <= now_minutes <= batch["end_minutes"]:
                for student in students_by_batch.get(batch["id"], []):
                    branch_students_now.add(student["student_id"])

        occupancy = _occupancy_status(len(branch_students_now), branch["no_of_computers"])
        branch_summaries.append({
            "id": branch_id,
            "branch_name": branch["branch_name"],
            "students_now": len(branch_students_now),
            "computer_count": branch["no_of_computers"],
            "occupancy_pct": occupancy["percentage"],
            "status_key": occupancy["key"],
            "status_label": occupancy["label"],
            "message": occupancy["message"],
        })

    branch_summaries.sort(key=lambda item: item["occupancy_pct"], reverse=True)

    return {
        "filters": filters,
        "branches": branches,
        "courses": courses,
        "trainers": trainers,
        "is_today": is_today,
        "selected_date_label": selected_date.strftime("%d %b %Y"),
        "office_hours": f"{_format_time_label(office_open)} - {_format_time_label(office_close)}",
        "summary": {
            "total_batches": len(batch_cards),
            "total_students": len(visible_unique_student_ids),
            "total_computers": total_computers,
            "average_occupancy": average_occupancy,
            "peak_time": _format_time_label(slot_minutes[peak_index]) if slot_minutes else "-",
            "peak_count": peak_count,
            "low_time": _format_time_label(slot_minutes[low_index]) if slot_minutes else "-",
            "low_count": low_count,
        },
        "chart_data": {
            "labels": [_format_time_label(slot) for slot in slot_minutes],
            "students": chart_students,
            "capacity": [total_computers for _ in slot_minutes],
            "peakIndex": peak_index,
            "lowIndex": low_index,
        },
        "branch_summaries": branch_summaries,
        "batch_cards": batch_cards,
        "students_by_batch": visible_students_by_batch,
    }


@billing_bp.route("/students/batch-progress/day-overview")
@login_required
def institute_day_overview():
    conn = get_conn()
    cur = conn.cursor()

    current_user_id = session.get("user_id")
    session_role = (session.get("role") or "").strip().lower()
    cur.execute(
        "SELECT id, role, branch_id, can_view_all_branches FROM users WHERE id = ?",
        (current_user_id,)
    )
    user = cur.fetchone()
    role = (user["role"] if user else session_role) or session_role

    today = _ist_now().strftime("%Y-%m-%d")
    selected_date = request.args.get("date", today).strip() or today
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = today

    filters = {
        "date": selected_date,
        "branch_id": request.args.get("branch_id", "").strip(),
        "trainer_id": request.args.get("trainer_id", "").strip(),
        "course_id": request.args.get("course_id", "").strip(),
        "batch_status": request.args.get("batch_status", "").strip(),
        "occupancy_status": request.args.get("occupancy_status", "").strip(),
    }

    try:
        overview = _build_institute_day_overview(cur, filters, user, role)
    finally:
        conn.close()

    base_url_args = {
        "course_id": "",
        "batch_id": "",
        "branch_id": filters["branch_id"],
        "trainer_id": filters["trainer_id"],
        "progress": "",
        "student_status": "",
        "q": "",
    }

    return render_template(
        "billing/institute_day_overview.html",
        **overview,
        card_view_url=url_for("billing.student_batch_progress_monitor", **base_url_args, view="cards"),
        table_view_url=url_for("billing.student_batch_progress_monitor", **base_url_args, view="table"),
        live_batches_url=url_for("attendance.dashboard", branch_id=filters["branch_id"] or None, trainer_id=filters["trainer_id"] or None),
        day_overview_url=url_for("billing.institute_day_overview", **filters),
    )


@billing_bp.route("/student/check-duplicate", methods=["POST"])
@login_required
def student_check_duplicate():
    """AJAX endpoint: check if a phone number already belongs to a student."""
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    exclude_id = data.get("exclude_id")  # student id to exclude (for edit page)

    if not phone:
        return jsonify({"duplicate": False})

    conn = get_conn()
    cur = conn.cursor()
    if exclude_id:
        cur.execute(
            "SELECT id, student_code, full_name, phone FROM students WHERE phone = ? AND id != ?",
            (phone, exclude_id)
        )
    else:
        cur.execute(
            "SELECT id, student_code, full_name, phone FROM students WHERE phone = ?",
            (phone,)
        )
    existing = cur.fetchone()
    conn.close()

    if existing:
        return jsonify({
            "duplicate": True,
            "student_id": existing["id"],
            "student_code": existing["student_code"],
            "full_name": existing["full_name"],
        })
    return jsonify({"duplicate": False})


@billing_bp.route("/api/pincode-lookup")
@login_required
def pincode_lookup():
    """Backend proxy: resolve Indian pincode to city/state/locality via Google Geocoding API."""
    import re as _re
    import urllib.request
    import json as _json
    from flask import current_app

    pincode = request.args.get("pincode", "").strip()
    if not _re.fullmatch(r"\d{6}", pincode):
        return jsonify({"success": False, "error": "Invalid pincode"})

    api_key = current_app.config.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return jsonify({"success": False, "error": "Maps API not configured"})

    url = (
        "https://maps.googleapis.com/maps/api/geocode/json"
        f"?address={pincode},India&key={api_key}"
    )

    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        return jsonify({"success": False, "error": "Lookup failed"})

    if data.get("status") != "OK" or not data.get("results"):
        return jsonify({"success": False, "error": "Pincode not found"})

    components = data["results"][0].get("address_components", [])

    locality = ""
    city = ""
    state = ""

    for comp in components:
        types = comp.get("types", [])
        name = comp.get("long_name", "")
        if "locality" in types and not locality:
            locality = name
        if "administrative_area_level_3" in types and not city:
            city = name
        if "administrative_area_level_2" in types and not city:
            city = name
        if "administrative_area_level_1" in types:
            state = name

    return jsonify({
        "success": True,
        "locality": locality,
        "city": city,
        "state": state,
    })


@billing_bp.route("/student/new", methods=["GET", "POST"])
@login_required
def student_new():
    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        # Duplicate Prevention Token Check
        form_token = request.form.get("form_token")
        saved_token = session.get("student_form_token")
        if not form_token or form_token != saved_token:
            conn.close()
            flash("This student has already been registered or the request is no longer valid.", "warning")
            return redirect(url_for("billing.students"))
        branch_id = request.form.get("branch_id", "").strip()
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        lead_id_raw = request.form.get("lead_id", "").strip()
        form_lead_id = int(lead_id_raw) if lead_id_raw.isdigit() else None

        # Validate phone number
        import re as _re
        _phone_digits = _re.sub(r'[\s\-\+]', '', phone)
        if not _phone_digits.isdigit() or len(_phone_digits) != 10:
            cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
            branches = cur.fetchall()
            conn.close()
            return render_template(
                "billing/student_form.html",
                student=None,
                branches=branches,
                education_levels=QUALIFICATION_LEVELS.keys(),
                qualification_levels=QUALIFICATION_LEVELS,
                error="Invalid phone number. Please enter a valid 10-digit mobile number.",
                form_data=request.form
            )

        gender = request.form.get("gender", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        pincode = request.form.get("pincode", "").strip()
        locality = request.form.get("locality", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        landmark = request.form.get("landmark", "").strip()
        alternate_phone = request.form.get("alternate_phone", "").strip()
        address_type = request.form.get("address_type", "").strip()
        education_level = request.form.get("education_level", "").strip()
        qualification = request.form.get("qualification", "").strip()
        student_location = request.form.get("student_location", "").strip()
        employment_status = request.form.get("employment_status", "").strip()
        status = request.form.get("status", "active").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip() or None
        parent_name = request.form.get("parent_name", "").strip() or None
        parent_contact = request.form.get("parent_contact", "").strip() or None
        resume_fields = _student_resume_form_values(request.form, education_level, qualification)
        photo_data = request.form.get("photo_data", "").strip()
        required_values = {
            "branch_id": branch_id,
            "full_name": full_name,
            "phone": phone,
            "gender": gender,
            "email": email,
            "date_of_birth": date_of_birth,
            "pincode": pincode,
            "locality": locality,
            "address": address,
            "city": city,
            "state": state,
            "landmark": landmark,
            "alternate_phone": alternate_phone,
            "address_type": address_type,
            "parent_name": parent_name,
            "parent_contact": parent_contact,
            "education_level": education_level,
            "qualification": qualification,
            "student_location": student_location,
            "employment_status": employment_status,
            "status": status,
            **resume_fields,
        }
        missing_required = _student_required_missing_labels(
            required_values,
            resume_fields,
            has_photo=bool(photo_data),
        )
        if missing_required:
            cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
            branches = cur.fetchall()
            conn.close()
            return render_template(
                "billing/student_form.html",
                student=None,
                branches=branches,
                education_levels=QUALIFICATION_LEVELS.keys(),
                qualification_levels=QUALIFICATION_LEVELS,
                error=_student_required_error_message(missing_required),
                form_data=request.form
            )

        # Validate date_of_birth is a real calendar date
        if date_of_birth:
            try:
                datetime.strptime(date_of_birth, "%Y-%m-%d")
            except ValueError:
                cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
                branches = cur.fetchall()
                conn.close()
                return render_template(
                    "billing/student_form.html",
                    student=None,
                    branches=branches,
                    education_levels=QUALIFICATION_LEVELS.keys(),
                    qualification_levels=QUALIFICATION_LEVELS,
                    error="Invalid date of birth. Please enter a valid calendar date.",
                    form_data=request.form
                )

        # Photo is required for new students
        if not photo_data:
            cur.execute("""
                SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name
            """)
            branches = cur.fetchall()
            conn.close()
            return render_template(
                "billing/student_form.html",
                student=None,
                branches=branches,
                education_levels=QUALIFICATION_LEVELS.keys(),
                qualification_levels=QUALIFICATION_LEVELS,
                error="Student photo is required.",
                form_data=request.form
            )

        # Duplicate phone check
        force_save = request.form.get("force_save") == "1"
        if not force_save:
            cur.execute(
                "SELECT id, student_code, full_name FROM students WHERE phone = ?",
                (phone,)
            )
            dup = cur.fetchone()
            if dup:
                cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
                branches = cur.fetchall()
                conn.close()
                return render_template(
                    "billing/student_form.html",
                    student=None,
                    branches=branches,
                    education_levels=QUALIFICATION_LEVELS.keys(),
                    qualification_levels=QUALIFICATION_LEVELS,
                    duplicate_warning={
                        "student_id": dup["id"],
                        "student_code": dup["student_code"],
                        "full_name": dup["full_name"],
                        "phone": phone,
                    },
                    form_data=request.form
                )

        # Invalidate the token immediately so subsequent requests fail
        session.pop("student_form_token", None)

        cur.execute("""
            SELECT student_code
            FROM students
            ORDER BY CAST(student_code AS INTEGER) DESC
            LIMIT 1
        """)
        result = cur.fetchone()

        if result and result["student_code"]:
            try:
                max_reg = int(result["student_code"])
                next_reg_no = max_reg + 1
            except (ValueError, TypeError):
                max_reg = 1515000
                next_reg_no = max_reg + 1
        else:
            max_reg = 1515000
            next_reg_no = max_reg + 1

        # Save photo if provided
        photo_filename = None
        if photo_data:
            photo_filename = save_student_photo(photo_data, str(next_reg_no))

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            INSERT INTO students (
                student_code,
                full_name,
                phone,
                gender,
                email,
                address,
                pincode,
                locality,
                city,
                state,
                landmark,
                alternate_phone,
                address_type,
                education_level,
                qualification,
                student_location,
                employment_status,
                date_of_birth,
                parent_name,
                parent_contact,
                father_name,
                mother_name,
                tenth_institution,
                tenth_board,
                tenth_year,
                tenth_percentage,
                puc_institution,
                puc_board,
                puc_stream,
                puc_year,
                puc_percentage,
                degree_institution,
                degree_university,
                degree_course,
                degree_year,
                degree_percentage,
                joined_date,
                status,
                branch_id,
                photo_filename,
                lead_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(next_reg_no),
            full_name,
            phone,
            gender,
            email,
            address,
            pincode,
            locality,
            city,
            state,
            landmark,
            alternate_phone,
            address_type,
            education_level,
            qualification,
            student_location,
            employment_status,
            date_of_birth,
            parent_name,
            parent_contact,
            resume_fields["father_name"],
            resume_fields["mother_name"],
            resume_fields["tenth_institution"],
            resume_fields["tenth_board"],
            resume_fields["tenth_year"],
            resume_fields["tenth_percentage"],
            resume_fields["puc_institution"],
            resume_fields["puc_board"],
            resume_fields["puc_stream"],
            resume_fields["puc_year"],
            resume_fields["puc_percentage"],
            resume_fields["degree_institution"],
            resume_fields["degree_university"],
            resume_fields["degree_course"],
            resume_fields["degree_year"],
            resume_fields["degree_percentage"],
            now,
            status,
            branch_id,
            photo_filename,
            form_lead_id,
            now,
            now
        ))

        student_id = cur.lastrowid

        # ── Lead linkage ────────────────────────────────────────────
        if form_lead_id:
            # Mark the originating lead as converted
            today_str = now[:10]
            cur.execute(
                "UPDATE leads SET stage = 'Converted', status = 'converted', conversion_date = ?, updated_at = ? WHERE id = ?",
                (today_str, now, form_lead_id)
            )
            conn.commit()
            conn.close()
        else:
            # Auto-create a lead record for this direct admission
            _edu_map = {
                "School": "School Student",
                "Pre-University": "PUC Student",
                "Diploma": "Degree Student",
                "Undergraduate": "Degree Student",
                "Postgraduate": "Graduate",
                "Professional": "Working Professional",
            }
            lead_edu = _edu_map.get(education_level, "")
            cur.execute(
                """INSERT INTO leads
                       (name, phone, gender, education_status, lead_location,
                        stage, status, lead_source, conversion_date, branch_id,
                        assigned_to_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'Converted', 'converted', 'Walk-in', ?, ?, ?, ?, ?)""",
                (full_name, phone, gender, lead_edu, student_location, now[:10], branch_id,
                 session["user_id"], now, now)
            )
            new_lead_id = cur.lastrowid
            cur.execute("UPDATE students SET lead_id = ? WHERE id = ?", (new_lead_id, student_id))
            conn.commit()
            conn.close()
            flash("A lead record was automatically created for this student.", "info")

        _auto_enable_portal(student_id)

        log_activity(
            user_id=session["user_id"],
            branch_id=branch_id,
            action_type="create",
            module_name="students",
            record_id=student_id,
            description=f"Created student {full_name} (Reg No: {next_reg_no})"
        )

        if form_lead_id:
            log_activity(
                user_id=session["user_id"],
                branch_id=branch_id,
                action_type="lead_converted",
                module_name="leads",
                record_id=form_lead_id,
                description=f"Lead converted on {now[:10]} - Student: {full_name} (Reg No: {next_reg_no})",
            )

        # Send welcome SMS with registration number
        try:
            sms_phone = "+91" + phone  # phone is already validated 10-digit
            sms_message = (
                f"Welcome to Global IT Education, {full_name}! "
                f"Your Registration Number is {next_reg_no}. "
                "Keep this number safe for future reference."
            )
            send_sms(sms_phone, sms_message)
        except Exception:
            pass  # Never block registration if SMS fails

        flash("Student added successfully.", "success")
        return redirect(url_for("billing.students"))

    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    # Pre-fill from a lead if ?from_lead=<id> is provided
    prefill_lead = None
    from_lead_raw = request.args.get("from_lead", "").strip()
    if from_lead_raw.isdigit():
        cur.execute(
            "SELECT * FROM leads WHERE id = ? AND is_deleted = 0",
            (int(from_lead_raw),)
        )
        prefill_lead = cur.fetchone()

    # Generate unique idempotency token for new student registration
    import uuid
    session["student_form_token"] = str(uuid.uuid4())

    conn.close()

    return render_template(
        "billing/student_form.html",
        student=None,
        branches=branches,
        education_levels=QUALIFICATION_LEVELS.keys(),
        qualification_levels=QUALIFICATION_LEVELS,
        prefill_lead=prefill_lead
    )

@billing_bp.route("/student/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def student_edit(student_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM students
        WHERE id = ?
    """, (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("billing.students"))

    if request.method == "POST":
        branch_id = request.form.get("branch_id", "").strip()
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()

        # Validate phone number
        import re as _re
        _phone_digits = _re.sub(r'[\s\-\+]', '', phone)
        if not _phone_digits.isdigit() or len(_phone_digits) != 10:
            cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
            branches = cur.fetchall()
            conn.close()
            return render_template(
                "billing/student_form.html",
                student=student,
                branches=branches,
                education_levels=QUALIFICATION_LEVELS.keys(),
                qualification_levels=QUALIFICATION_LEVELS,
                error="Invalid phone number. Please enter a valid 10-digit mobile number.",
                form_data=request.form
            )

        gender = request.form.get("gender", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        pincode = request.form.get("pincode", "").strip()
        locality = request.form.get("locality", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        landmark = request.form.get("landmark", "").strip()
        alternate_phone = request.form.get("alternate_phone", "").strip()
        address_type = request.form.get("address_type", "").strip()
        education_level = request.form.get("education_level", "").strip()
        qualification = request.form.get("qualification", "").strip()
        student_location = request.form.get("student_location", "").strip()
        employment_status = request.form.get("employment_status", "").strip()
        status = request.form.get("status", "active").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip() or None
        parent_name = request.form.get("parent_name", "").strip() or None
        parent_contact = request.form.get("parent_contact", "").strip() or None
        resume_fields = _student_resume_form_values(request.form, education_level, qualification)
        photo_data = request.form.get("photo_data", "").strip()
        try:
            existing_photo_filename = student["photo_filename"] if "photo_filename" in student.keys() else None
        except:
            existing_photo_filename = None
        required_values = {
            "branch_id": branch_id,
            "full_name": full_name,
            "phone": phone,
            "gender": gender,
            "email": email,
            "date_of_birth": date_of_birth,
            "pincode": pincode,
            "locality": locality,
            "address": address,
            "city": city,
            "state": state,
            "landmark": landmark,
            "alternate_phone": alternate_phone,
            "address_type": address_type,
            "parent_name": parent_name,
            "parent_contact": parent_contact,
            "education_level": education_level,
            "qualification": qualification,
            "student_location": student_location,
            "employment_status": employment_status,
            "status": status,
            **resume_fields,
        }
        missing_required = _student_required_missing_labels(
            required_values,
            resume_fields,
            has_photo=bool(photo_data or existing_photo_filename),
        )
        if missing_required:
            cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
            branches = cur.fetchall()
            conn.close()
            return render_template(
                "billing/student_form.html",
                student=student,
                branches=branches,
                education_levels=QUALIFICATION_LEVELS.keys(),
                qualification_levels=QUALIFICATION_LEVELS,
                error=_student_required_error_message(missing_required),
                form_data=request.form
            )

        # Validate date_of_birth is a real calendar date
        if date_of_birth:
            try:
                datetime.strptime(date_of_birth, "%Y-%m-%d")
            except ValueError:
                cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
                branches = cur.fetchall()
                conn.close()
                return render_template(
                    "billing/student_form.html",
                    student=student,
                    branches=branches,
                    education_levels=QUALIFICATION_LEVELS.keys(),
                    qualification_levels=QUALIFICATION_LEVELS,
                    error="Invalid date of birth. Please enter a valid calendar date.",
                    form_data=request.form
                )

        # Save photo if provided
        # Row objects don't have .get() method, use bracket notation instead
        try:
            photo_filename = student["photo_filename"] if "photo_filename" in student.keys() else None
        except:
            photo_filename = None
        
        if photo_data:
            photo_filename = save_student_photo(photo_data, student["student_code"])

        # Duplicate phone check (exclude current student)
        force_save = request.form.get("force_save") == "1"
        if not force_save:
            cur.execute(
                "SELECT id, student_code, full_name FROM students WHERE phone = ? AND id != ?",
                (phone, student_id)
            )
            dup = cur.fetchone()
            if dup:
                cur.execute("SELECT * FROM branches WHERE is_active = 1 ORDER BY branch_name")
                branches = cur.fetchall()
                conn.close()
                return render_template(
                    "billing/student_form.html",
                    student=student,
                    branches=branches,
                    education_levels=QUALIFICATION_LEVELS.keys(),
                    qualification_levels=QUALIFICATION_LEVELS,
                    duplicate_warning={
                        "student_id": dup["id"],
                        "student_code": dup["student_code"],
                        "full_name": dup["full_name"],
                        "phone": phone,
                    },
                    form_data=request.form
                )

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            UPDATE students
            SET branch_id = ?,
                full_name = ?,
                phone = ?,
                gender = ?,
                email = ?,
                address = ?,
                pincode = ?,
                locality = ?,
                city = ?,
                state = ?,
                landmark = ?,
                alternate_phone = ?,
                address_type = ?,
                education_level = ?,
                qualification = ?,
                student_location = ?,
                employment_status = ?,
                date_of_birth = ?,
                parent_name = ?,
                parent_contact = ?,
                father_name = ?,
                mother_name = ?,
                tenth_institution = ?,
                tenth_board = ?,
                tenth_year = ?,
                tenth_percentage = ?,
                puc_institution = ?,
                puc_board = ?,
                puc_stream = ?,
                puc_year = ?,
                puc_percentage = ?,
                degree_institution = ?,
                degree_university = ?,
                degree_course = ?,
                degree_year = ?,
                degree_percentage = ?,
                status = ?,
                photo_filename = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            branch_id,
            full_name,
            phone,
            gender,
            email,
            address,
            pincode,
            locality,
            city,
            state,
            landmark,
            alternate_phone,
            address_type,
            education_level,
            qualification,
            student_location,
            employment_status,
            date_of_birth,
            parent_name,
            parent_contact,
            resume_fields["father_name"],
            resume_fields["mother_name"],
            resume_fields["tenth_institution"],
            resume_fields["tenth_board"],
            resume_fields["tenth_year"],
            resume_fields["tenth_percentage"],
            resume_fields["puc_institution"],
            resume_fields["puc_board"],
            resume_fields["puc_stream"],
            resume_fields["puc_year"],
            resume_fields["puc_percentage"],
            resume_fields["degree_institution"],
            resume_fields["degree_university"],
            resume_fields["degree_course"],
            resume_fields["degree_year"],
            resume_fields["degree_percentage"],
            status,
            photo_filename,
            now,
            student_id
        ))

        conn.commit()
        conn.close()

        log_activity(
            user_id=session["user_id"],
            branch_id=branch_id,
            action_type="update",
            module_name="students",
            record_id=student_id,
            description=f"Updated student {full_name} ({student['student_code']})"
        )

        flash("Student updated successfully.", "success")
        return redirect(url_for("billing.students"))

    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    conn.close()

    return render_template(
        "billing/student_form.html",
        student=student,
        branches=branches,
        education_levels=QUALIFICATION_LEVELS.keys(),
        qualification_levels=QUALIFICATION_LEVELS
    )

@billing_bp.route("/student/<int:student_id>/upload-photo", methods=["POST"])
@login_required
def student_upload_photo(student_id):
    """Quick photo upload from student profile page."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, student_code, full_name FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404

    photo_data = request.form.get("photo_data", "").strip()
    if not photo_data:
        conn.close()
        return jsonify({"success": False, "error": "No photo data received"}), 400

    try:
        photo_filename = save_student_photo(photo_data, student["student_code"])
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute(
            "UPDATE students SET photo_filename = ?, updated_at = ? WHERE id = ?",
            (photo_filename, now, student_id)
        )
        conn.commit()
        log_activity(
            user_id=session["user_id"],
            branch_id=None,
            action_type="update",
            module_name="students",
            record_id=student_id,
            description=f"Updated photo for student {student['full_name']} ({student['student_code']})"
        )
        conn.close()
        return jsonify({"success": True, "photo_filename": photo_filename})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 500


@billing_bp.route("/student/<int:student_id>/save-signature", methods=["POST"])
@login_required
def student_save_signature(student_id):
    """Save student or parent digital signature from profile page."""
    import os, base64
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, student_code, full_name FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404

    sig_type = request.form.get("sig_type", "").strip()   # "student" or "parent"
    sig_data = request.form.get("sig_data", "").strip()   # base64 PNG data URL

    if sig_type not in ("student", "parent"):
        conn.close()
        return jsonify({"success": False, "error": "Invalid signature type"}), 400
    if not sig_data:
        conn.close()
        return jsonify({"success": False, "error": "No signature data"}), 400

    try:
        if ',' in sig_data:
            sig_data = sig_data.split(',')[1]
        sig_bytes = base64.b64decode(sig_data)

        sig_dir = os.path.join("static", "images", "student_signatures")
        os.makedirs(sig_dir, exist_ok=True)

        code = student["student_code"]
        filename = f"{code}_{sig_type}_signature.png"
        filepath = os.path.join(sig_dir, filename)
        with open(filepath, "wb") as f:
            f.write(sig_bytes)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if sig_type == "student":
            cur.execute(
                "UPDATE students SET student_signature_filename=?, student_signature_date=?, updated_at=? WHERE id=?",
                (filename, now, now, student_id)
            )
        else:
            cur.execute(
                "UPDATE students SET parent_signature_filename=?, parent_signature_date=?, updated_at=? WHERE id=?",
                (filename, now, now, student_id)
            )
        conn.commit()
        log_activity(
            user_id=session["user_id"],
            branch_id=None,
            action_type="update",
            module_name="students",
            record_id=student_id,
            description=f"Saved {sig_type} signature for {student['full_name']} ({code})"
        )
        conn.close()
        return jsonify({"success": True, "filename": filename, "signed_at": now})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 500


@billing_bp.route("/student/<int:student_id>/batches-available")
@login_required
def student_batches_available(student_id):
    """Return active batches not already enrolled by this student (JSON)."""
    conn = get_conn()
    cur = conn.cursor()
    # Get student's branch first
    cur.execute("SELECT branch_id FROM students WHERE id = ?", (student_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"batches": []})
    branch_id = row["branch_id"]
    cur.execute("""
        SELECT b.id, b.batch_name, b.start_time, b.end_time,
               c.course_name, br.branch_name
        FROM batches b
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN branches br ON b.branch_id = br.id
        WHERE b.status = 'active'
          AND b.branch_id = ?
          AND b.id NOT IN (
              SELECT batch_id FROM student_batches
              WHERE student_id = ? AND status = 'active'
          )
        ORDER BY b.batch_name
    """, (branch_id, student_id))
    batches = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"batches": batches})

@billing_bp.route("/student/<int:student_id>/add-to-batch", methods=["POST"])
@login_required
def student_add_to_batch(student_id):
    """Enroll student in a batch."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, student_code FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404

    batch_id = request.form.get("batch_id", type=int)
    if not batch_id:
        conn.close()
        return jsonify({"success": False, "error": "No batch selected"}), 400

    cur.execute("SELECT id, batch_name, branch_id FROM batches WHERE id = ? AND status = 'active'", (batch_id,))
    batch = cur.fetchone()
    if not batch:
        conn.close()
        return jsonify({"success": False, "error": "Batch not found or inactive"}), 404

    # Check for duplicate active enrollment
    cur.execute("SELECT id FROM student_batches WHERE student_id = ? AND batch_id = ? AND status = 'active'",
                (student_id, batch_id))
    if cur.fetchone():
        conn.close()
        return jsonify({"success": False, "error": "Student is already enrolled in this batch"}), 409

    now = datetime.now().isoformat(timespec="seconds")
    cur.execute("""
        INSERT INTO student_batches (student_id, batch_id, joined_on, status, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?)
    """, (student_id, batch_id, now.split("T")[0], now, now))
    conn.commit()
    log_activity(
        user_id=session["user_id"],
        branch_id=batch["branch_id"],
        action_type="create",
        module_name="attendance",
        record_id=batch_id,
        description=f"Enrolled student {student['full_name']} ({student['student_code']}) in batch '{batch['batch_name']}'"
    )
    conn.close()
    return jsonify({"success": True, "batch_name": batch["batch_name"]})


def _student_lms_progress_rows(cur, student_id):
    """Return per-program LMS progress summaries for the student profile."""
    cur.execute("""
        SELECT DISTINCT
            lp.id AS program_id,
            lp.course_id,
            lp.program_name,
            COALESCE(c.course_name, lp.program_name) AS course_name,
            COALESCE(NULLIF(lp.updated_at, ''), lp.created_at, '') AS version_sort,
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM lms_student_program_access spa
                    WHERE spa.student_id = ?
                      AND spa.program_id = lp.id
                      AND spa.is_active = 1
                      AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                ) THEN 3
                ELSE 1
            END AS access_priority,
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM lms_student_program_access spa
                    WHERE spa.student_id = ?
                      AND spa.program_id = lp.id
                      AND spa.is_active = 0
                ) THEN 1
                ELSE 0
            END AS is_suspended
        FROM lms_programs lp
        LEFT JOIN courses c ON c.id = lp.course_id
        WHERE lp.is_active = 1
          AND COALESCE(lp.is_deleted, 0) = 0
          AND EXISTS (
              SELECT 1
              FROM lms_student_program_access spa
              WHERE spa.student_id = ?
                AND spa.program_id = lp.id
          )
        ORDER BY course_name, lp.program_name
    """, (student_id, student_id, student_id))
    programs = cur.fetchall()

    progress_rows = []
    for program in programs:
        program_id = program["program_id"]
        cur.execute("""
            SELECT COUNT(*) AS total_topics
            FROM lms_program_chapters pc
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
            JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
            WHERE pc.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
        """, (program_id,))
        master_total = int((cur.fetchone() or {"total_topics": 0})["total_topics"] or 0)

        if master_total > 0:
            total_topics = master_total
            cur.execute("""
                SELECT COUNT(*) AS completed_topics
                FROM lms_master_topic_progress mtp
                JOIN lms_master_topics mt ON mt.id = mtp.master_topic_id
                JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE mtp.student_id = ?
                  AND mtp.program_id = ?
                  AND mtp.is_completed = 1
                  AND pc.program_id = ?
                  AND pc.is_visible = 1
                  AND mc.status = 'active'
                  AND mt.status = 'active'
            """, (student_id, program_id, program_id))
            completed_topics = int((cur.fetchone() or {"completed_topics": 0})["completed_topics"] or 0)
        else:
            cur.execute("""
                SELECT COUNT(*) AS total_topics
                FROM lms_topics lt
                JOIN lms_chapters lc ON lc.id = lt.chapter_id
                WHERE lc.program_id = ?
                  AND lc.is_active = 1
                  AND lt.is_active = 1
            """, (program_id,))
            total_topics = int((cur.fetchone() or {"total_topics": 0})["total_topics"] or 0)

            cur.execute("""
                SELECT COUNT(*) AS completed_topics
                FROM lms_topic_progress tp
                JOIN lms_topics lt ON lt.id = tp.topic_id
                JOIN lms_chapters lc ON lc.id = lt.chapter_id
                WHERE tp.student_id = ?
                  AND lc.program_id = ?
                  AND tp.is_completed = 1
                  AND lt.is_active = 1
            """, (student_id, program_id))
            completed_topics = int((cur.fetchone() or {"completed_topics": 0})["completed_topics"] or 0)

        cur.execute("""
            SELECT MAX(last_activity) AS last_activity
            FROM (
                SELECT MAX(tp.completed_at) AS last_activity
                FROM lms_topic_progress tp
                JOIN lms_topics lt ON lt.id = tp.topic_id
                JOIN lms_chapters lc ON lc.id = lt.chapter_id
                WHERE tp.student_id = ?
                  AND lc.program_id = ?
                  AND tp.is_completed = 1
                UNION ALL
                SELECT MAX(mtp.completed_at) AS last_activity
                FROM lms_master_topic_progress mtp
                WHERE mtp.student_id = ?
                  AND mtp.program_id = ?
                  AND mtp.is_completed = 1
            )
        """, (student_id, program_id, student_id, program_id))
        last_activity = (cur.fetchone() or {"last_activity": None})["last_activity"]

        progress_pct = round((completed_topics / total_topics) * 100, 1) if total_topics else 0
        if total_topics == 0 or completed_topics == 0:
            progress_status = "Not Started"
            progress_class = "not-started"
        elif progress_pct >= 100:
            progress_status = "Completed"
            progress_class = "completed"
        else:
            progress_status = "In Progress"
            progress_class = "in-progress"

        progress_rows.append({
            "program_id": program_id,
            "course_id": program["course_id"],
            "program_name": program["program_name"],
            "course_name": program["course_name"],
            "total_topics": total_topics,
            "completed_topics": completed_topics,
            "progress_pct": progress_pct,
            "progress_status": progress_status,
            "progress_class": progress_class,
            "last_activity": last_activity,
            "access_priority": int(program["access_priority"] or 1),
            "version_sort": program["version_sort"] or "",
            "is_suspended": bool(program["is_suspended"]),
        })

    selected_by_course = {}
    for row in progress_rows:
        key = f"course:{row['course_id']}" if row["course_id"] else f"program:{row['program_id']}"
        current = selected_by_course.get(key)
        row_score = (
            row["access_priority"],
            1 if row["completed_topics"] > 0 else 0,
            row["progress_pct"],
            row["version_sort"],
            row["program_id"],
        )
        current_score = None
        if current:
            current_score = (
                current["access_priority"],
                1 if current["completed_topics"] > 0 else 0,
                current["progress_pct"],
                current["version_sort"],
                current["program_id"],
            )
        if current is None or row_score > current_score:
            selected_by_course[key] = row

    return sorted(
        selected_by_course.values(),
        key=lambda row: (row["course_name"] or "", row["program_name"] or "")
    )


@billing_bp.route("/student/<int:student_id>")
@login_required
def student_profile(student_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            students.*,
            branches.branch_name
        FROM students
        LEFT JOIN branches
            ON students.branch_id = branches.id
        WHERE students.id = ?
    """, (student_id,))
    student = cur.fetchone()

    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("billing.students"))

    cur.execute("""
        SELECT
            invoices.id,
            invoices.invoice_no,
            invoices.invoice_date,
            invoices.total_amount,
            invoices.status,
            IFNULL(SUM(receipts.amount_received), 0) AS paid_amount
        FROM invoices
        LEFT JOIN receipts
            ON receipts.invoice_id = invoices.id
        WHERE invoices.student_id = ?
        GROUP BY invoices.id
        ORDER BY invoices.id DESC
    """, (student_id,))
    invoices = cur.fetchall()

    cur.execute("""
        SELECT
            COUNT(*) AS total_invoices,
            IFNULL(SUM(total_amount), 0) AS total_billed
        FROM invoices
        WHERE student_id = ?
    """, (student_id,))
    invoice_summary = cur.fetchone()

    cur.execute("""
        SELECT
            IFNULL(SUM(receipts.amount_received), 0) AS total_paid
        FROM receipts
        JOIN invoices
            ON receipts.invoice_id = invoices.id
        WHERE invoices.student_id = ?
    """, (student_id,))
    payment_summary = cur.fetchone()

    # Fetch invoice items (courses enrolled)
    cur.execute("""
        SELECT
            invoice_items.id,
            invoice_items.invoice_id,
            invoice_items.description,
            invoice_items.quantity,
            invoice_items.unit_price,
            invoice_items.line_total,
            invoice_items.discount,
            invoices.invoice_no,
            invoices.invoice_date
        FROM invoice_items
        JOIN invoices ON invoice_items.invoice_id = invoices.id
        WHERE invoices.student_id = ?
        ORDER BY invoices.invoice_date DESC, invoice_items.id
    """, (student_id,))
    invoice_items = cur.fetchall()

    # Fetch installment plans
    cur.execute("""
        SELECT
            installment_plans.*,
            invoices.invoice_no
        FROM installment_plans
        JOIN invoices ON installment_plans.invoice_id = invoices.id
        WHERE invoices.student_id = ?
        ORDER BY installment_plans.due_date ASC
    """, (student_id,))
    installment_plans = cur.fetchall()

    installment_summary = {
        "total": len(installment_plans),
        "paid": 0,
        "pending": 0,
    }
    for plan in installment_plans:
        plan_status = (plan["status"] or "").lower()
        if plan_status in ("paid", "completed"):
            installment_summary["paid"] += 1
        else:
            installment_summary["pending"] += 1

    cur.execute("""
        SELECT COALESCE(SUM(bw.amount_written_off), 0) AS total_written_off
        FROM bad_debt_writeoffs bw
        JOIN invoices i ON bw.invoice_id = i.id
        WHERE i.student_id = ?
    """, (student_id,))
    writeoff_summary = cur.fetchone()

    total_invoices = int(invoice_summary["total_invoices"] or 0)
    total_billed = float(invoice_summary["total_billed"] or 0)
    total_paid = float(payment_summary["total_paid"] or 0)
    total_written_off_student = float(writeoff_summary["total_written_off"] or 0) if writeoff_summary else 0.0
    total_balance = total_billed - total_paid - total_written_off_student

    # Fetch batches this student is enrolled in
    cur.execute("""
        SELECT b.id AS batch_id, b.batch_name, b.start_time, b.end_time,
               b.status AS batch_status, c.course_name, sb.status AS enroll_status
        FROM student_batches sb
        JOIN batches b ON sb.batch_id = b.id
        LEFT JOIN courses c ON b.course_id = c.id
        WHERE sb.student_id = ?
        ORDER BY sb.status ASC, b.batch_name ASC
    """, (student_id,))
    student_batches = cur.fetchall()

    current_batch = None
    for batch in student_batches:
        if (batch["enroll_status"] or "").lower() == "active":
            current_batch = batch
            break
    if not current_batch and student_batches:
        current_batch = student_batches[0]

    current_course = None
    if current_batch and current_batch["course_name"]:
        current_course = current_batch["course_name"].strip()

    attendance_summary = {
        "total_marked": 0,
        "present": 0,
        "absent": 0,
        "late": 0,
        "leave": 0,
    }
    attendance_query = """
        WITH collapsed_attendance AS (
            SELECT 
                attendance_date,
                status,
                CASE 
                    WHEN status = 'present' THEN 4
                    WHEN status = 'late' THEN 3
                    WHEN status = 'leave' THEN 2
                    WHEN status = 'absent' THEN 1
                    ELSE 0
                END as priority
            FROM attendance_records
            WHERE student_id = ?
    """
    attendance_params = [student_id]
    if student["branch_id"]:
        attendance_query += " AND branch_id = ?"
        attendance_params.append(student["branch_id"])

    attendance_query += """
        ),
        daily_attendance AS (
            SELECT 
                attendance_date,
                CASE MAX(priority)
                    WHEN 4 THEN 'present'
                    WHEN 3 THEN 'late'
                    WHEN 2 THEN 'leave'
                    WHEN 1 THEN 'absent'
                    ELSE 'absent'
                END as status
            FROM collapsed_attendance
            GROUP BY attendance_date
        )
        SELECT
            COUNT(*) AS total_marked,
            COALESCE(SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END), 0) AS present,
            COALESCE(SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END), 0) AS absent,
            COALESCE(SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END), 0) AS late,
            COALESCE(SUM(CASE WHEN status = 'leave' THEN 1 ELSE 0 END), 0) AS leave
        FROM daily_attendance
    """

    cur.execute(attendance_query, attendance_params)
    attendance_row = cur.fetchone()
    if attendance_row:
        attendance_summary = {
            "total_marked": int(attendance_row["total_marked"] or 0),
            "present": int(attendance_row["present"] or 0),
            "absent": int(attendance_row["absent"] or 0),
            "late": int(attendance_row["late"] or 0),
            "leave": int(attendance_row["leave"] or 0),
        }

    attendance_percentage = 0
    if attendance_summary["total_marked"]:
        attendance_percentage = round((attendance_summary["present"] / attendance_summary["total_marked"]) * 100, 1)

    recent_activity_rows = []

    cur.execute("""
        SELECT
            al.id,
            al.user_id,
            al.branch_id,
            al.action_type,
            al.module_name,
            al.record_id,
            al.description,
            al.created_at,
            u.full_name AS actor_name,
            u.username AS actor_username
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        WHERE al.module_name = 'students' AND al.record_id = ?
        ORDER BY al.id DESC
        LIMIT 5
    """, (student_id,))
    recent_activity_rows.extend(cur.fetchall())

    cur.execute("""
        SELECT
            al.id,
            al.user_id,
            al.branch_id,
            al.action_type,
            al.module_name,
            al.record_id,
            al.description,
            al.created_at,
            u.full_name AS actor_name,
            u.username AS actor_username
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        JOIN invoices i ON i.id = al.record_id
        WHERE al.module_name = 'billing' AND i.student_id = ?
        ORDER BY al.id DESC
        LIMIT 5
    """, (student_id,))
    recent_activity_rows.extend(cur.fetchall())

    if student_batches:
        cur.execute("""
            SELECT
                al.id,
                al.user_id,
                al.branch_id,
                al.action_type,
                al.module_name,
                al.record_id,
                al.description,
                al.created_at,
                u.full_name AS actor_name,
                u.username AS actor_username
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.id
            JOIN student_batches sb ON sb.batch_id = al.record_id
            WHERE al.module_name = 'attendance' AND sb.student_id = ?
            ORDER BY al.id DESC
            LIMIT 5
        """, (student_id,))
        recent_activity_rows.extend(cur.fetchall())

    if student["lead_id"]:
        cur.execute("""
            SELECT
                al.id,
                al.user_id,
                al.branch_id,
                al.action_type,
                al.module_name,
                al.record_id,
                al.description,
                al.created_at,
                u.full_name AS actor_name,
                u.username AS actor_username
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE al.module_name = 'leads' AND al.record_id = ?
            ORDER BY al.id DESC
            LIMIT 5
        """, (student["lead_id"],))
        recent_activity_rows.extend(cur.fetchall())

    recent_activity_map = {}
    for row in recent_activity_rows:
        recent_activity_map[row["id"]] = row
    recent_activity = sorted(recent_activity_map.values(), key=lambda row: row["id"], reverse=True)[:8]

    # Split course sources for explicit labeling in UI
    student_invoiced_courses = []
    for item in invoice_items:
        course_name = (item['description'] or '').strip()
        if course_name and course_name not in student_invoiced_courses:
            student_invoiced_courses.append(course_name)

    if current_course is None and student_invoiced_courses:
        current_course = student_invoiced_courses[0]

    lms_progress_rows = _student_lms_progress_rows(cur, student_id)

    student_batch_courses = []
    for b in student_batches:
        course_name = (b['course_name'] or '').strip()
        if course_name and course_name not in student_batch_courses:
            student_batch_courses.append(course_name)

    # Originating lead (if student was converted from or auto-linked to a lead)
    origin_lead = None
    if student["lead_id"]:
        cur.execute(
            "SELECT id, name, stage, status FROM leads WHERE id = ? AND is_deleted = 0",
            (student["lead_id"],)
        )
        origin_lead = cur.fetchone()

    # Fetch final exam applications and certificates
    cur.execute(
        """
        SELECT 
            app.id AS application_id,
            app.course_id AS program_id,
            app.requested_exam_date,
            app.status AS application_status,
            app.applied_on,
            lp.program_name,
            c.course_name,
            att.score_percent,
            att.correct_count,
            att.total_questions,
            att.submitted_at
        FROM lms_final_exam_applications app
        LEFT JOIN lms_programs lp ON lp.id = app.course_id
        LEFT JOIN courses c ON c.id = lp.course_id
        LEFT JOIN lms_final_exam_attempts att ON att.application_id = app.id
        WHERE app.student_id = ?
        ORDER BY app.applied_on DESC
        """,
        (student_id,)
    )
    exam_applications = cur.fetchall()

    cur.execute(
        """
        SELECT 
            cert.id AS certificate_id,
            cert.certificate_number,
            cert.course_id,
            cert.snapshot_course_name,
            cert.issue_date,
            cert.score,
            cert.snapshot_grade,
            cert.status AS certificate_status
        FROM certificates cert
        WHERE cert.student_id = ?
        ORDER BY cert.issue_date DESC
        """,
        (student_id,)
    )
    certificates = cur.fetchall()

    # Fetch student uploaded documents
    uploaded_docs = cur.execute(
        "SELECT * FROM student_uploaded_documents WHERE student_id = ? ORDER BY category, uploaded_at DESC",
        (student_id,)
    ).fetchall()

    # Fetch pending update requests
    pending_update = cur.execute(
        "SELECT * FROM student_profile_update_requests WHERE student_id = ? AND status = 'PENDING' LIMIT 1",
        (student_id,)
    ).fetchone()

    from modules.students.routes import calculate_profile_score
    profile_score = calculate_profile_score(student, uploaded_docs)

    conn.close()

    return render_template(
        "billing/student_profile.html",
        student=student,
        invoices=invoices,
        invoice_items=invoice_items,
        installment_plans=installment_plans,
        total_invoices=total_invoices,
        total_billed=total_billed,
        total_paid=total_paid,
        total_balance=total_balance,
        student_batches=student_batches,
        student_invoiced_courses=student_invoiced_courses,
        student_batch_courses=student_batch_courses,
        current_batch=current_batch,
        current_course=current_course,
        installment_summary=installment_summary,
        attendance_summary=attendance_summary,
        attendance_percentage=attendance_percentage,
        lms_progress_rows=lms_progress_rows,
        recent_activity=recent_activity,
        origin_lead=origin_lead,
        exam_applications=exam_applications,
        certificates=certificates,
        uploaded_docs=uploaded_docs,
        pending_update=pending_update,
        profile_score=profile_score,
        format_datetime=_format_display_datetime,
        format_date=_format_display_date,
        format_inr=_format_inr,
    )


@billing_bp.route("/lms_admin/student/<int:student_id>/approve-profile-update", methods=["POST"])
@login_required
def approve_profile_update(student_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # 1. Fetch the request
        request_row = cur.execute(
            "SELECT * FROM student_profile_update_requests WHERE student_id = ? AND status = 'PENDING' LIMIT 1",
            (student_id,)
        ).fetchone()
        
        if not request_row:
            flash("No pending update request found for this student.", "danger")
            return redirect(url_for("billing.student_profile", student_id=student_id))
            
        # Parse json
        import json
        requested_data = json.loads(request_row["requested_data"])
        
        # Check approved updates count limit
        student = cur.execute("SELECT profile_approved_updates_count FROM students WHERE id = ?", (student_id,)).fetchone()
        if student["profile_approved_updates_count"] >= 3:
            flash("Student has already reached the maximum limit of 3 approved profile updates.", "danger")
            return redirect(url_for("billing.student_profile", student_id=student_id))
            
        # 2. Build update query
        if requested_data:
            fields = []
            params = []
            for field, val in requested_data.items():
                fields.append(f"{field} = ?")
                params.append(val)
                
            # Add increment to count
            fields.append("profile_approved_updates_count = profile_approved_updates_count + 1")
            params.append(student_id) # for the WHERE clause
            
            query = f"UPDATE students SET {', '.join(fields)} WHERE id = ?"
            cur.execute(query, params)
            
        # 3. Mark request as APPROVED
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute(
            """
            UPDATE student_profile_update_requests
            SET status = 'APPROVED', processed_by = ?, processed_at = ?
            WHERE id = ?
            """,
            (session.get("user_id"), now, request_row["id"])
        )
        
        conn.commit()
        flash("Profile update request has been successfully approved and applied.", "success")
        
        # Log activity
        log_activity(
            user_id=session.get("user_id"),
            branch_id=None,
            action_type="update",
            module_name="students",
            record_id=student_id,
            description=f"Approved and applied profile update request #{request_row['id']}"
        )
    except Exception as e:
        conn.rollback()
        flash(f"Database error: {str(e)}", "danger")
    finally:
        conn.close()
        
    return redirect(url_for("billing.student_profile", student_id=student_id))


@billing_bp.route("/lms_admin/student/<int:student_id>/reject-profile-update", methods=["POST"])
@login_required
def reject_profile_update(student_id):
    rejection_reason = request.form.get("rejection_reason", "").strip()
    if not rejection_reason:
        flash("Please provide a reason for rejection.", "danger")
        return redirect(url_for("billing.student_profile", student_id=student_id))
        
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Fetch the request
        request_row = cur.execute(
            "SELECT id FROM student_profile_update_requests WHERE student_id = ? AND status = 'PENDING' LIMIT 1",
            (student_id,)
        ).fetchone()
        
        if not request_row:
            flash("No pending update request found for this student.", "danger")
            return redirect(url_for("billing.student_profile", student_id=student_id))
            
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute(
            """
            UPDATE student_profile_update_requests
            SET status = 'REJECTED', rejection_reason = ?, processed_by = ?, processed_at = ?
            WHERE id = ?
            """,
            (rejection_reason, session.get("user_id"), now, request_row["id"])
        )
        conn.commit()
        flash("Profile update request has been rejected.", "warning")
        
        # Log activity
        log_activity(
            user_id=session.get("user_id"),
            branch_id=None,
            action_type="update",
            module_name="students",
            record_id=student_id,
            description=f"Rejected profile update request #{request_row['id']}. Reason: {rejection_reason}"
        )
    except Exception as e:
        conn.rollback()
        flash(f"Database error: {str(e)}", "danger")
    finally:
        conn.close()
        
    return redirect(url_for("billing.student_profile", student_id=student_id))


@billing_bp.route("/students/export-csv")
@admin_required
def export_students_csv():
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                students.student_code,
                students.full_name,
                students.phone,
                students.gender,
                students.email,
                students.address,
                students.education_level,
                students.qualification,
                students.student_location,
                students.employment_status,
                students.status,
                branches.branch_name,
                students.created_at
            FROM students
            LEFT JOIN branches
                ON students.branch_id = branches.id
            ORDER BY students.id DESC
        """)
        students_data = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Student Code",
            "Full Name",
            "Phone",
            "Gender",
            "Email",
            "Address",
            "Education Level",
            "Qualification",
            "Student Location",
            "Employment Status",
            "Status",
            "Branch",
            "Created Date"
        ])

        for student in students_data:
            writer.writerow([
                student["student_code"] or "",
                student["full_name"] or "",
                student["phone"] or "",
                student["gender"] or "",
                student["email"] or "",
                student["address"] or "",
                student["education_level"] or "",
                student["qualification"] or "",
                student["student_location"] or "",
                student["employment_status"] or "",
                student["status"] or "",
                student["branch_name"] or "",
                student["created_at"] or ""
            ])

        csv_data = output.getvalue()
        output.close()

        log_activity(
            user_id=session.get("user_id"),
            branch_id=None,
            action_type="export",
            module_name="students",
            record_id=None,
            description="Exported students data to CSV"
        )

        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=students_export.csv"
            }
        )

    except Exception as e:
        flash(f"Error exporting students: {str(e)}", "danger")
        return redirect(url_for("billing.students"))
    
@billing_bp.route("/courses")
@login_required
def courses():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM courses
        ORDER BY
            CASE WHEN course_domain IS NULL OR course_domain = '' THEN 1 ELSE 0 END,
            course_domain,
            CASE WHEN duration_hours IS NULL THEN 9999 ELSE duration_hours END,
            course_name
    """)
    courses = cur.fetchall()
    conn.close()

    # Group by domain for the grouped view
    from collections import OrderedDict
    grouped = OrderedDict()
    for c in courses:
        key = c["course_domain"] or "(No Domain)"
        grouped.setdefault(key, []).append(c)

    return render_template("billing/courses.html", courses=courses, grouped=grouped)


COURSE_DOMAINS = [
    "Accounting",
    "Coding & Programming",
    "Design & Multimedia",
    "Digital Marketing",
    "Hardware & Networking",
    "Office Tools",
    "Spoken English & Communication",
    "Other",
]

COURSE_CATEGORIES = [
    "Short Term",
    "Certificate Course",
    "Bootcamp",
    "Diploma",
    "Other",
]


@billing_bp.route("/course/new", methods=["GET", "POST"])
@login_required
def course_new():
    if request.method == "POST":
        course_name = request.form["course_name"].strip()
        duration = request.form["duration"].strip()
        fee = request.form["fee"].strip()
        course_domain = request.form.get("course_domain", "").strip() or None
        course_category = request.form.get("course_category", "").strip() or None
        show_on_website = 1 if request.form.get("show_on_website") else 0
        duration_hours_raw = request.form.get("duration_hours", "").strip()
        duration_hours = int(duration_hours_raw) if duration_hours_raw.isdigit() else None
        course_slug_raw = request.form.get("course_slug", "").strip().lower()
        import re as _re
        course_slug = _re.sub(r"[^a-z0-9_-]", "", course_slug_raw) or None

        conn = get_conn()
        cur = conn.cursor()

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            INSERT INTO courses (
                course_name,
                duration,
                fee,
                course_domain,
                course_category,
                show_on_website,
                duration_hours,
                course_slug,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            course_name,
            duration,
            fee,
            course_domain,
            course_category,
            show_on_website,
            duration_hours,
            course_slug,
            now,
            now
        ))

        course_id = cur.lastrowid
        conn.commit()
        conn.close()

        log_activity(
            user_id=session["user_id"],
            branch_id=session.get("branch_id"),
            action_type="create",
            module_name="courses",
            record_id=course_id,
            description=f"Created course {course_name}"
        )

        flash("Course added successfully.", "success")
        return redirect(url_for("billing.courses"))

    return render_template("billing/course_form.html", course=None,
                           course_domains=COURSE_DOMAINS, course_categories=COURSE_CATEGORIES)


@billing_bp.route("/course/<int:id>/edit", methods=["GET", "POST"])
@login_required
def course_edit(id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM courses
        WHERE id = ?
    """, (id,))
    course = cur.fetchone()

    if not course:
        conn.close()
        flash("Course not found.", "danger")
        return redirect(url_for("billing.courses"))

    if request.method == "POST":
        course_name = request.form["course_name"].strip()
        duration = request.form["duration"].strip()
        fee = request.form["fee"].strip()
        course_domain = request.form.get("course_domain", "").strip() or None
        course_category = request.form.get("course_category", "").strip() or None
        show_on_website = 1 if request.form.get("show_on_website") else 0
        duration_hours_raw = request.form.get("duration_hours", "").strip()
        duration_hours = int(duration_hours_raw) if duration_hours_raw.isdigit() else None
        course_slug_raw = request.form.get("course_slug", "").strip().lower()
        import re as _re
        course_slug = _re.sub(r"[^a-z0-9_-]", "", course_slug_raw) or None

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            UPDATE courses
            SET course_name = ?,
                duration = ?,
                fee = ?,
                course_domain = ?,
                course_category = ?,
                show_on_website = ?,
                duration_hours = ?,
                course_slug = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            course_name,
            duration,
            fee,
            course_domain,
            course_category,
            show_on_website,
            duration_hours,
            course_slug,
            now,
            id
        ))

        conn.commit()
        conn.close()

        log_activity(
            user_id=session["user_id"],
            branch_id=session.get("branch_id"),
            action_type="update",
            module_name="courses",
            record_id=id,
            description=f"Updated course {course_name}"
        )

        flash("Course updated successfully.", "success")
        return redirect(url_for("billing.courses"))

    conn.close()
    return render_template("billing/course_form.html", course=course,
                           course_domains=COURSE_DOMAINS, course_categories=COURSE_CATEGORIES)


@billing_bp.route("/course/<int:id>/toggle_active", methods=["POST"])
@login_required
@admin_required
def course_toggle_active(id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, course_name, is_active FROM courses WHERE id = ?", (id,))
    course = cur.fetchone()

    if not course:
        conn.close()
        flash("Course not found.", "danger")
        return redirect(url_for("billing.courses"))

    new_status = 0 if course["is_active"] else 1
    label = "activated" if new_status else "deactivated"

    now = datetime.now().isoformat(timespec="seconds")
    cur.execute("UPDATE courses SET is_active = ?, updated_at = ? WHERE id = ?", (new_status, now, id))
    conn.commit()
    conn.close()

    log_activity(
        user_id=session["user_id"],
        branch_id=session.get("branch_id"),
        action_type="update",
        module_name="courses",
        record_id=id,
        description=f"Course '{course['course_name']}' {label}"
    )

    flash(f"Course '{course['course_name']}' has been {label}.", "success")
    return redirect(url_for("billing.courses"))


@billing_bp.route("/course/<int:id>/toggle_website", methods=["POST"])
@login_required
@admin_required
def course_toggle_website(id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, course_name, is_active, show_on_website FROM courses WHERE id = ?", (id,))
    course = cur.fetchone()

    if not course:
        conn.close()
        flash("Course not found.", "danger")
        return redirect(url_for("billing.courses"))

    if not course["is_active"]:
        conn.close()
        flash("Only active courses can be shown on the website.", "warning")
        return redirect(url_for("billing.courses"))

    new_val = 0 if course["show_on_website"] else 1
    label = "added to" if new_val else "removed from"

    now = datetime.now().isoformat(timespec="seconds")
    cur.execute("UPDATE courses SET show_on_website = ?, updated_at = ? WHERE id = ?",
                (new_val, now, id))
    conn.commit()
    conn.close()

    log_activity(
        user_id=session["user_id"],
        branch_id=session.get("branch_id"),
        action_type="update",
        module_name="courses",
        record_id=id,
        description=f"Course '{course['course_name']}' {label} website"
    )

    flash(f"Course '{course['course_name']}' {label} the website.", "success")
    return redirect(url_for("billing.courses"))


@billing_bp.route("/invoices")
@login_required
def invoices():
    search = request.args.get("search", "").strip()

    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()
    current_year = datetime.now().year
    current_month = datetime.now().month
    month_year_filter = f"{current_year}-{current_month:02d}"

    # TODAY STATS
    cur.execute("""
        SELECT 
            COUNT(*) as total_invoices,
            SUM(invoices.total_amount) as total_amount,
            SUM(CASE WHEN invoices.status = 'paid' THEN 1 ELSE 0 END) as paid_count,
            SUM(CASE WHEN invoices.status = 'partially_paid' THEN 1 ELSE 0 END) as partially_paid_count,
            SUM(CASE WHEN invoices.status = 'unpaid' THEN 1 ELSE 0 END) as unpaid_count,
            SUM(invoices.total_amount - IFNULL((
                SELECT SUM(receipts.amount_received) 
                FROM receipts 
                WHERE receipts.invoice_id = invoices.id
            ), 0)) as outstanding_amount
        FROM invoices
        WHERE DATE(invoices.invoice_date) = ?
    """, (today,))
    today_stats = cur.fetchone()

    # MONTH STATS - Using invoice_date instead of created_at
    cur.execute("""
        SELECT 
            COUNT(*) as total_invoices,
            SUM(invoices.total_amount) as total_amount,
            SUM(CASE WHEN invoices.status = 'paid' THEN 1 ELSE 0 END) as paid_count,
            SUM(CASE WHEN invoices.status = 'partially_paid' THEN 1 ELSE 0 END) as partially_paid_count,
            SUM(CASE WHEN invoices.status = 'unpaid' THEN 1 ELSE 0 END) as unpaid_count,
            SUM(invoices.total_amount - IFNULL((
                SELECT SUM(receipts.amount_received) 
                FROM receipts 
                WHERE receipts.invoice_id = invoices.id
            ), 0)) as outstanding_amount
        FROM invoices
        WHERE strftime('%Y-%m', invoices.invoice_date) = ?
    """, (f"{current_year}-{current_month:02d}",))
    month_stats = cur.fetchone()

    # OVERALL STATS
    cur.execute("""
        SELECT 
            COUNT(*) as total_all_invoices,
            SUM(invoices.total_amount) as total_all_amount,
            SUM(CASE WHEN invoices.status = 'paid' THEN 1 ELSE 0 END) as all_paid_count,
            SUM(CASE WHEN invoices.status = 'partially_paid' THEN 1 ELSE 0 END) as all_partially_paid_count,
            SUM(CASE WHEN invoices.status = 'unpaid' THEN 1 ELSE 0 END) as all_unpaid_count,
            SUM(invoices.total_amount - IFNULL((
                SELECT SUM(receipts.amount_received) 
                FROM receipts 
                WHERE receipts.invoice_id = invoices.id
            ), 0)) as all_outstanding_amount
        FROM invoices
    """)
    overall_stats = cur.fetchone()

    query = """
    SELECT
        invoices.id,
        invoices.invoice_no,
        invoices.invoice_date,
        invoices.total_amount,
        invoices.status,
        students.id AS student_id,
        students.student_code,
        students.full_name,
        branches.branch_name,
        IFNULL(SUM(receipts.amount_received), 0) AS paid_amount
    FROM invoices
    JOIN students
        ON invoices.student_id = students.id
    LEFT JOIN branches
        ON invoices.branch_id = branches.id
    LEFT JOIN receipts
        ON receipts.invoice_id = invoices.id
    """

    params = []

    if search:
        query += """
        WHERE
            invoices.invoice_no LIKE ?
            OR students.full_name LIKE ?
            OR students.student_code LIKE ?
        """
        like = f"%{search}%"
        params.extend([like, like, like])

    query += """
    GROUP BY invoices.id
    ORDER BY invoices.id DESC
    """

    cur.execute(query, params)
    invoices = cur.fetchall()

    conn.close()

    return render_template(
        "billing/invoices.html",
        invoices=invoices,
        search=search,
        today_stats=today_stats,
        month_stats=month_stats,
        overall_stats=overall_stats
    )

@billing_bp.route("/invoice/<int:invoice_id>")
@login_required
def invoice_view(invoice_id):
    conn = get_conn()
    cur = conn.cursor()

    # Fetch invoice details with student and branch info
    cur.execute("""
        SELECT
            invoices.id,
            invoices.invoice_no,
            invoices.invoice_date,
            invoices.subtotal,
            invoices.discount_amount,
            invoices.total_amount,
            invoices.status,
            invoices.notes,
            invoices.created_at,
            invoices.sms_sent_at,
            students.id AS student_id,
            students.student_code,
            students.full_name,
            students.phone,
            students.email,
            students.address,
            branches.branch_name
        FROM invoices
        JOIN students ON invoices.student_id = students.id
        LEFT JOIN branches ON invoices.branch_id = branches.id
        WHERE invoices.id = ?
    """, (invoice_id,))
    invoice = cur.fetchone()

    if not invoice:
        conn.close()
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing.invoices"))

    # Fetch invoice items
    cur.execute("""
        SELECT
            id,
            course_id,
            description,
            quantity,
            unit_price,
            discount,
            line_total
        FROM invoice_items
        WHERE invoice_id = ?
        ORDER BY id ASC
    """, (invoice_id,))
    items = cur.fetchall()

    # Fetch installment plans
    cur.execute("""
        SELECT
            id,
            installment_no,
            due_date,
            amount_due,
            amount_paid,
            status,
            remarks
        FROM installment_plans
        WHERE invoice_id = ?
        ORDER BY installment_no ASC
    """, (invoice_id,))
    installments = cur.fetchall()

    # Fetch payments (receipts) with user info
    cur.execute("""
        SELECT
            receipts.id,
            receipts.receipt_no,
            receipts.receipt_date,
            receipts.amount_received,
            receipts.created_at,
            receipts.created_by,
            users.full_name AS created_by_name
        FROM receipts
        JOIN users ON receipts.created_by = users.id
        WHERE receipts.invoice_id = ?
        ORDER BY receipts.id DESC
    """, (invoice_id,))
    payments = cur.fetchall()

    # Calculate totals
    cur.execute("""
        SELECT
            IFNULL(SUM(amount_received), 0) AS total_paid
        FROM receipts
        WHERE invoice_id = ?
    """, (invoice_id,))
    paid_result = cur.fetchone()
    total_paid = float(paid_result["total_paid"] or 0) if paid_result else 0.0

    # Fetch write-off information if exists
    cur.execute("""
        SELECT
            IFNULL(SUM(amount_written_off), 0) AS total_written_off
        FROM bad_debt_writeoffs
        WHERE invoice_id = ?
    """, (invoice_id,))
    writeoff_result = cur.fetchone()
    total_written_off = float(writeoff_result["total_written_off"] or 0) if writeoff_result else 0.0

    # Compute effective status based on actual financials (guards against stale DB status)
    invoice_total = float(invoice["total_amount"] or 0)
    covered = round(total_paid + total_written_off, 2)
    if covered >= round(invoice_total, 2):
        if total_written_off > 0 and total_paid == 0:
            effective_status = "write_off"
        elif total_written_off > 0:
            effective_status = "write_off"
        else:
            effective_status = "paid"
    elif total_written_off > 0:
        effective_status = "partially_written_off"
    elif invoice["status"] in ["write_off", "partially_written_off"]:
        effective_status = invoice["status"]
    else:
        effective_status = invoice["status"]

    # Balance is zero once fully covered by payments + write-offs
    if covered >= round(invoice_total, 2) or effective_status in ["write_off", "partially_written_off"]:
        balance_amount = max(0.0, invoice_total - total_paid - total_written_off)
    else:
        balance_amount = invoice_total - total_paid - total_written_off

    conn.close()

    return render_template(
        "billing/invoice_view.html",
        invoice=invoice,
        items=items,
        installments=installments,
        payments=payments,
        total_paid=total_paid,
        balance_amount=balance_amount,
        total_written_off=total_written_off,
        effective_status=effective_status
    )

@billing_bp.route("/invoice/<int:invoice_id>/print")
@login_required
def invoice_print(invoice_id):
    conn = get_conn()
    cur = conn.cursor()

    # Fetch invoice details with student and branch info
    cur.execute("""
        SELECT
            invoices.id,
            invoices.invoice_no,
            invoices.invoice_date,
            invoices.subtotal,
            invoices.discount_amount,
            invoices.total_amount,
            invoices.status,
            invoices.notes,
            invoices.created_at,
            students.id AS student_id,
            students.student_code,
            students.full_name AS student_name,
            students.phone AS student_phone,
            students.email,
            students.address,
            branches.branch_name
        FROM invoices
        JOIN students ON invoices.student_id = students.id
        LEFT JOIN branches ON invoices.branch_id = branches.id
        WHERE invoices.id = ?
    """, (invoice_id,))
    invoice = cur.fetchone()

    if not invoice:
        conn.close()
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing.invoices"))

    # Fetch invoice items
    cur.execute("""
        SELECT
            id,
            course_id,
            description,
            quantity,
            unit_price,
            discount,
            line_total
        FROM invoice_items
        WHERE invoice_id = ?
        ORDER BY id ASC
    """, (invoice_id,))
    items = cur.fetchall()

    # Fetch installment plans
    cur.execute("""
        SELECT
            id,
            installment_no,
            due_date,
            amount_due,
            amount_paid,
            status,
            remarks
        FROM installment_plans
        WHERE invoice_id = ?
        ORDER BY installment_no ASC
    """, (invoice_id,))
    installments = cur.fetchall()

    # Fetch payments (receipts) with user info - LEFT JOIN to handle no receipts
    cur.execute("""
        SELECT
            receipts.id,
            receipts.receipt_no,
            receipts.receipt_date,
            receipts.amount_received,
            receipts.created_at,
            receipts.created_by,
            IFNULL(users.full_name, 'System') AS created_by_name
        FROM receipts
        LEFT JOIN users ON receipts.created_by = users.id
        WHERE receipts.invoice_id = ?
        ORDER BY receipts.id DESC
    """, (invoice_id,))
    payments = cur.fetchall()

    # Calculate totals
    cur.execute("""
        SELECT
            IFNULL(SUM(amount_received), 0) AS total_paid
        FROM receipts
        WHERE invoice_id = ?
    """, (invoice_id,))
    paid_result = cur.fetchone()
    total_paid = float(paid_result["total_paid"] or 0) if paid_result else 0.0

    balance_amount = float(invoice["total_amount"] or 0) - total_paid
    net_total = float(invoice["total_amount"] or 0)

    # Get prepared by user info
    cur.execute("""
        SELECT full_name FROM users WHERE id = ?
    """, (session.get("user_id"),))
    user_result = cur.fetchone()
    prepared_by = user_result["full_name"] if user_result else "Administrator"

    conn.close()

    pdf_mode = request.args.get('mode') == 'pdf'

    return render_template(
        "billing/invoice_print.html",
        invoice=invoice,
        invoice_items=items,
        installment_plans=installments,
        receipts=payments,
        total_paid=total_paid,
        balance_amount=balance_amount,
        net_total=net_total,
        prepared_by=prepared_by,
        pdf_mode=pdf_mode
    )

@billing_bp.route("/installment/<int:installment_id>/edit", methods=["POST"])
@login_required
@admin_required
def installment_edit(installment_id):
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get current installment details
        cur.execute("""
            SELECT id, invoice_id, amount_paid
            FROM installment_plans
            WHERE id = ?
        """, (installment_id,))
        installment = cur.fetchone()

        if not installment:
            flash("Installment not found.", "danger")
            return redirect(url_for("billing.invoices"))

        invoice_id = installment["invoice_id"]
        amount_paid = float(installment["amount_paid"] or 0)

        # Get form data
        due_date = request.form.get("due_date", "").strip()
        amount_due_raw = request.form.get("amount_due", "0").strip()
        remarks = request.form.get("remarks", "").strip()

        # Validation
        if not due_date:
            flash("Due date is required.", "danger")
            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

        try:
            amount_due = float(amount_due_raw or 0)
        except ValueError:
            flash("Amount due must be a valid number.", "danger")
            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

        if amount_due < amount_paid:
            flash(f"Amount due cannot be less than amount paid (₹{amount_paid:.2f}).", "danger")
            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

        # Update installment
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute("""
            UPDATE installment_plans
            SET
                due_date = ?,
                amount_due = ?,
                remarks = ?,
                updated_at = ?
            WHERE id = ?
        """, (due_date, amount_due, remarks, now, installment_id))

        conn.commit()
        log_activity(
            user_id=session["user_id"],
            branch_id=None,  # Can fetch from invoice if needed
            action_type="update",
            module_name="installment_plans",
            record_id=installment_id,
            description=f"Updated installment plan #{installment_id}"
        )

        flash("Installment updated successfully.", "success")
        
        # Check if redirect_to parameter is set
        redirect_to = request.form.get("redirect_to", "").strip()
        if redirect_to == "receivables":
            return redirect(url_for("billing.receivables"))
        
        return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

    except Exception as e:
        flash(f"Error updating installment: {str(e)}", "danger")
        return redirect(url_for("billing.invoices"))

    finally:
        if conn:
            conn.close()


def _provision_program_access_for_course(cur, student_id, course_id):
    """
    Find the default/active program mapped to the course and grant explicit access
    to the student if they don't already have access.
    """
    cur.execute("""
        SELECT DISTINCT lp.id
        FROM lms_programs lp
        WHERE lp.is_active = 1 AND lp.is_deleted = 0
          AND (
              lp.course_id = ?
              OR EXISTS (
                  SELECT 1 FROM lms_course_program_map cpm 
                  WHERE cpm.program_id = lp.id AND cpm.course_id = ?
              )
          )
    """, (course_id, course_id))
    programs = cur.fetchall()
    
    now_date = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat(timespec="seconds")
    
    for prog in programs:
        program_id = prog['id']
        # Check if the student already has access to this program
        cur.execute("""
            SELECT 1 FROM lms_student_program_access
            WHERE student_id = ? AND program_id = ? AND is_active = 1
        """, (student_id, program_id))
        if not cur.fetchone():
            # Grant access!
            cur.execute("""
                INSERT INTO lms_student_program_access (
                    student_id, program_id, access_start_date, access_status, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', 1, ?, ?)
            """, (student_id, program_id, now_date, now_iso, now_iso))


@billing_bp.route("/invoice/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    student_full_name = None
    
    if request.method == "POST":
        # Duplicate Prevention Token Check
        form_token = request.form.get("form_token")
        saved_token = session.get("invoice_form_token")
        
        # Verify token is valid and matches
        if not form_token or form_token != saved_token:
            flash("This invoice has already been created or the request is no longer valid.", "warning")
            return redirect(url_for("billing.invoices"))

        conn = None
        try:
            conn = get_conn()
            cur = conn.cursor()
            
            student_id = request.form["student_id"]
            invoice_date = request.form["invoice_date"]
            installment_type = request.form["installment_type"]
            notes = request.form.get("notes", "").strip()

            item_course_ids = request.form.getlist("item_course_id[]")
            item_descriptions = request.form.getlist("item_course_name[]")
            item_qtys = request.form.getlist("item_qty[]")
            item_rates = request.form.getlist("item_rate[]")
            item_discounts = request.form.getlist("item_discount[]")

            if not student_id:
                flash("Please select a student.", "danger")
                return redirect(url_for("billing.invoice_new"))

            if not item_course_ids:
                flash("Please add at least one bill item.", "danger")
                return redirect(url_for("billing.invoice_new"))

            cur.execute("""
                SELECT id, branch_id, full_name
                FROM students
                WHERE id = ?
            """, (student_id,))
            student = cur.fetchone()

            if not student:
                flash("Selected student not found.", "danger")
                return redirect(url_for("billing.invoice_new"))

            branch_id = student["branch_id"]

            if not branch_id:
                flash("Selected student does not have a branch assigned.", "danger")
                return redirect(url_for("billing.invoice_new"))

            now = datetime.now().isoformat(timespec="seconds")

            invoice_items_to_save = []
            subtotal = 0.0
            discount_amount = 0.0
            total_amount = 0.0

            for i in range(len(item_course_ids)):
                course_id_raw = (item_course_ids[i] or "").strip()
                qty_raw = (item_qtys[i] or "0").strip()
                rate_raw = (item_rates[i] or "0").strip()
                discount_raw = (item_discounts[i] or "0").strip()

                # Skip empty rows (no course selected)
                if not course_id_raw:
                    continue

                description = (item_descriptions[i] or "").strip() if i < len(item_descriptions) else ""
                qty = float(qty_raw or 0)
                rate = float(rate_raw or 0)
                row_discount = float(discount_raw or 0)

                if qty <= 0:
                    flash(f"Quantity must be greater than 0 in item row {i + 1}.", "danger")
                    return redirect(url_for("billing.invoice_new"))

                if rate < 0:
                    flash(f"Rate cannot be negative in item row {i + 1}.", "danger")
                    return redirect(url_for("billing.invoice_new"))

                gross = qty * rate

                if row_discount < 0:
                    row_discount = 0

                if row_discount > gross:
                    row_discount = gross

                line_total = gross - row_discount

                subtotal += gross
                discount_amount += row_discount
                total_amount += line_total

                course_id = int(course_id_raw) if course_id_raw else None

                invoice_items_to_save.append({
                    "course_id": course_id,
                    "description": description,
                    "quantity": qty,
                    "unit_price": rate,
                    "discount": row_discount,
                    "line_total": line_total
                })

            if not invoice_items_to_save:
                flash("Please enter at least one valid bill item.", "danger")
                return redirect(url_for("billing.invoice_new"))

            # Invalidate the token now that all validations have passed
            session.pop("invoice_form_token", None)

            cur.execute("""
                INSERT INTO invoices (
                    invoice_no,
                    student_id,
                    branch_id,
                    invoice_date,
                    subtotal,
                    discount_type,
                    discount_value,
                    discount_amount,
                    total_amount,
                    installment_type,
                    notes,
                    status,
                    created_by,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "TEMP",
                student_id,
                branch_id,
                invoice_date,
                subtotal,
                "none",
                0,
                discount_amount,
                total_amount,
                installment_type,
                notes,
                "unpaid",
                session["user_id"],
                now,
                now
            ))

            invoice_id = cur.lastrowid

            cur.execute("""
                SELECT invoice_no
                FROM invoices
                WHERE invoice_no NOT LIKE 'INV-%'
                  AND invoice_no NOT LIKE 'TEMP'
                ORDER BY invoice_no DESC
                LIMIT 1
            """)
            result = cur.fetchone()

            if result and result["invoice_no"]:
                existing_no = result["invoice_no"]
                try:
                    parts = existing_no.split("/")
                    if len(parts) >= 2:
                        numeric_part = int(parts[-1])
                        prefix = "/".join(parts[:-1])
                        next_number = numeric_part + 1
                        invoice_no = f"{prefix}/{next_number}"
                    else:
                        invoice_no = f"GIT/B/{invoice_id}"
                except (ValueError, IndexError, TypeError):
                    invoice_no = f"GIT/B/{invoice_id}"
            else:
                invoice_no = f"GIT/B/{invoice_id}"

            cur.execute("""
                UPDATE invoices
                SET invoice_no = ?
                WHERE id = ?
            """, (invoice_no, invoice_id))

            for item in invoice_items_to_save:
                cur.execute("""
                    INSERT INTO invoice_items (
                        invoice_id,
                        course_id,
                        description,
                        quantity,
                        unit_price,
                        discount,
                        line_total,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    item["course_id"],
                    item["description"],
                    item["quantity"],
                    item["unit_price"],
                    item["discount"],
                    item["line_total"],
                    now
                ))

            if installment_type == "full":
                due_date = request.form.get("full_due_date", "").strip()

                if not due_date:
                    flash("Please enter full payment due date.", "danger")
                    return redirect(url_for("billing.invoice_new"))

                cur.execute("""
                    INSERT INTO installment_plans (
                        invoice_id,
                        installment_no,
                        due_date,
                        amount_due,
                        amount_paid,
                        status,
                        remarks,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    1,
                    due_date,
                    total_amount,
                    0,
                    "pending",
                    "Full payment",
                    now,
                    now
                ))

            elif installment_type == "custom":
                installment_count = int(request.form.get("installment_count", 0) or 0)

                if installment_count <= 0:
                    flash("Please enter valid installment count.", "danger")
                    return redirect(url_for("billing.invoice_new"))

                installment_total = 0.0

                for i in range(1, installment_count + 1):
                    due_date = request.form.get(f"due_date_{i}", "").strip()
                    amount_due_raw = request.form.get(f"amount_due_{i}", "0").strip()
                    remarks = request.form.get(f"remarks_{i}", "").strip()

                    amount_due = float(amount_due_raw or 0)

                    if not due_date:
                        flash(f"Due date is required for installment {i}.", "danger")
                        return redirect(url_for("billing.invoice_new"))

                    if amount_due <= 0:
                        flash(f"Amount must be greater than 0 for installment {i}.", "danger")
                        return redirect(url_for("billing.invoice_new"))

                    installment_total += amount_due

                    cur.execute("""
                        INSERT INTO installment_plans (
                            invoice_id,
                            installment_no,
                            due_date,
                            amount_due,
                            amount_paid,
                            status,
                            remarks,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        invoice_id,
                        i,
                        due_date,
                        amount_due,
                        0,
                        "pending",
                        remarks,
                        now,
                        now
                    ))

                if round(installment_total, 2) != round(total_amount, 2):
                    flash("Installment total must exactly match the net invoice total.", "danger")
                    return redirect(url_for("billing.invoice_new"))

            else:
                flash("Invalid installment type selected.", "danger")
                return redirect(url_for("billing.invoice_new"))

            # Provision program access based on courses in the invoice
            for item in invoice_items_to_save:
                if item.get("course_id"):
                    _provision_program_access_for_course(cur, student_id, item["course_id"])

            # Reset student status to active because of new invoice/enrolled course
            cur.execute(
                "UPDATE students SET status = 'active' WHERE id = ?",
                (student_id,)
            )

            conn.commit()

            # Extract student name before closing connection to avoid Row access after close
            student_full_name = str(student['full_name'])

            _auto_enable_portal(student_id)

            log_activity(
                user_id=session["user_id"],
                branch_id=branch_id,
                action_type="create",
                module_name="invoices",
                record_id=invoice_id,
                description=f"Created invoice {invoice_no} for student {student_full_name}"
            )
            try:
                sms_result = _send_invoice_sms_link(
                    invoice_id,
                    user_id=session.get("user_id"),
                    branch_id=branch_id,
                )
                if sms_result.get("success"):
                    flash(f"Invoice created successfully. SMS sent to {sms_result.get('phone')}.", "success")
                else:
                    logger.warning(
                        "Auto-SMS failed for invoice %s: %s",
                        invoice_no,
                        sms_result.get("error", "Unknown error"),
                    )
                    flash("Invoice created successfully.", "success")
            except Exception as sms_exc:
                logger.warning("Auto-SMS failed for invoice %s: %s", invoice_no, sms_exc)
                flash("Invoice created successfully.", "success")
            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

        except ValueError:
            flash("Please enter valid numeric values in invoice rows.", "danger")
            return redirect(url_for("billing.invoice_new"))

        except Exception as e:
            flash(f"Error while creating invoice: {str(e)}", "danger")
            return redirect(url_for("billing.invoice_new"))
        
        finally:
            if conn:
                conn.close()
    
    # Load form data for both GET and successful POST responses
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT students.*, branches.branch_name
        FROM students
        LEFT JOIN branches ON students.branch_id = branches.id
        ORDER BY students.full_name ASC
    """)
    students = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM courses
        WHERE is_active = 1
        ORDER BY course_name ASC
    """)
    courses = cur.fetchall()

    conn.close()
    today = datetime.today().strftime("%Y-%m-%d")
    
    # Convert Row objects to dictionaries for JSON serialization in template
    def row_to_dict(row):
        if row is None:
            return None
        try:
            return dict(row)
        except (TypeError, ValueError):
            return row if isinstance(row, dict) else str(row)

    students_dict = [row_to_dict(student) for student in (students or [])]
    courses_dict = [row_to_dict(course) for course in (courses or [])]

    prefill_student_id = request.args.get('student_id', '', type=int) or None

    # Generate unique idempotency token for new invoice form
    import uuid
    form_token = str(uuid.uuid4())
    session["invoice_form_token"] = form_token

    return render_template(
        "billing/invoice_form_modern.html",
        students=students_dict,
        courses=courses_dict,
        today=today,
        mode="create",
        prefill_student_id=prefill_student_id,
        form_token=form_token
    )

@billing_bp.route("/invoice/<int:invoice_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def invoice_edit(invoice_id):
    conn = get_conn()
    cur = conn.cursor()

    # Fetch the invoice
    cur.execute("""
        SELECT
            invoices.*,
            students.student_code,
            students.full_name,
            students.phone,
            students.email,
            students.address,
            branches.branch_name
        FROM invoices
        JOIN students
            ON invoices.student_id = students.id
        LEFT JOIN branches
            ON invoices.branch_id = branches.id
        WHERE invoices.id = ?
    """, (invoice_id,))
    invoice = cur.fetchone()

    if not invoice:
        conn.close()
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing.invoices"))

    # Check if invoice has any payments
    cur.execute("""
        SELECT IFNULL(SUM(amount_received), 0) AS total_paid
        FROM receipts
        WHERE invoice_id = ?
    """, (invoice_id,))
    total_paid = float(cur.fetchone()["total_paid"] or 0)

    # Fetch invoice items
    cur.execute("""
        SELECT
            invoice_items.*,
            courses.course_name
        FROM invoice_items
        LEFT JOIN courses
            ON invoice_items.course_id = courses.id
        WHERE invoice_items.invoice_id = ?
    """, (invoice_id,))
    items = cur.fetchall()

    # Fetch installment plans
    cur.execute("""
        SELECT *
        FROM installment_plans
        WHERE invoice_id = ?
        ORDER BY installment_no ASC
    """, (invoice_id,))
    installments = cur.fetchall()

    if request.method == "POST":
        try:
            student_id_form = int(request.form.get("student_id", 0))
            invoice_date = request.form["invoice_date"]
            installment_type = request.form.get("installment_type", "").strip()
            notes = request.form.get("notes", "").strip()

            # Validate student exists
            cur.execute("SELECT id FROM students WHERE id = ?", (student_id_form,))
            if not cur.fetchone():
                conn.close()
                flash("Selected student does not exist.", "danger")
                return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

            # Re-check payments
            cur.execute("""
                SELECT IFNULL(SUM(amount_received), 0) AS total_paid
                FROM receipts
                WHERE invoice_id = ?
            """, (invoice_id,))
            total_paid = float(cur.fetchone()["total_paid"] or 0)

            item_course_ids = request.form.getlist("item_course_id[]")
            item_descriptions = request.form.getlist("item_course_name[]")
            item_qtys = request.form.getlist("item_qty[]")
            item_rates = request.form.getlist("item_rate[]")
            item_discounts = request.form.getlist("item_discount[]")

            if not item_course_ids:
                flash("Please add at least one bill item.", "danger")
                conn.close()
                return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

            now = datetime.now().isoformat(timespec="seconds")

            invoice_items_to_save = []
            subtotal = 0.0
            discount_amount = 0.0
            total_amount = 0.0

            for i in range(len(item_course_ids)):
                course_id_raw = (item_course_ids[i] or "").strip()
                qty_raw = (item_qtys[i] or "0").strip()
                rate_raw = (item_rates[i] or "0").strip()
                discount_raw = (item_discounts[i] or "0").strip()

                # Skip empty rows (no course selected)
                if not course_id_raw:
                    continue

                description = (item_descriptions[i] or "").strip() if i < len(item_descriptions) else ""
                qty = float(qty_raw or 0)
                rate = float(rate_raw or 0)
                row_discount = float(discount_raw or 0)

                if qty <= 0:
                    conn.close()
                    flash(f"Quantity must be greater than 0 in item row {i + 1}.", "danger")
                    return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                if rate < 0:
                    conn.close()
                    flash(f"Rate cannot be negative in item row {i + 1}.", "danger")
                    return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                gross = qty * rate

                if row_discount < 0:
                    row_discount = 0

                if row_discount > gross:
                    row_discount = gross

                line_total = gross - row_discount

                subtotal += gross
                discount_amount += row_discount
                total_amount += line_total

                course_id = int(course_id_raw) if course_id_raw else None

                invoice_items_to_save.append({
                    "course_id": course_id,
                    "description": description,
                    "quantity": qty,
                    "unit_price": rate,
                    "discount": row_discount,
                    "line_total": line_total
                })

            if not invoice_items_to_save:
                conn.close()
                flash("Please enter at least one valid bill item.", "danger")
                return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

            # Prevent reducing total below paid amount
            if total_amount < total_paid:
                conn.close()
                flash(f"Cannot reduce invoice total below ₹{total_paid:.2f}", "danger")
                return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

            # Update invoice
            cur.execute("""
                UPDATE invoices
                SET student_id = ?,
                    invoice_date = ?,
                    subtotal = ?,
                    discount_amount = ?,
                    total_amount = ?,
                    installment_type = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                student_id_form,
                invoice_date,
                subtotal,
                discount_amount,
                total_amount,
                installment_type,
                notes,
                now,
                invoice_id
            ))

            # Replace invoice items
            cur.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))

            for item in invoice_items_to_save:
                cur.execute("""
                    INSERT INTO invoice_items (
                        invoice_id,
                        course_id,
                        description,
                        quantity,
                        unit_price,
                        discount,
                        line_total,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    item["course_id"],
                    item["description"],
                    item["quantity"],
                    item["unit_price"],
                    item["discount"],
                    item["line_total"],
                    now
                ))

            # Update installments
            if installment_type == "full":
                due_date = request.form.get("full_due_date", "").strip()

                if not due_date:
                    conn.rollback()
                    conn.close()
                    flash("Please enter full payment due date.", "danger")
                    return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                cur.execute("""
                    UPDATE installment_plans
                    SET due_date = ?,
                        amount_due = ?,
                        updated_at = ?
                    WHERE invoice_id = ? AND installment_no = 1
                """, (due_date, total_amount, now, invoice_id))

            elif installment_type == "custom":
                installment_count = int(request.form.get("installment_count", 0) or 0)

                if installment_count <= 0:
                    conn.rollback()
                    conn.close()
                    flash("Please enter valid installment count.", "danger")
                    return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                installment_total = 0.0

                for i in range(1, installment_count + 1):
                    due_date = request.form.get(f"due_date_{i}", "").strip()
                    amount_due_raw = request.form.get(f"amount_due_{i}", "0").strip()
                    remarks = request.form.get(f"remarks_{i}", "").strip()

                    amount_due = float(amount_due_raw or 0)

                    if not due_date:
                        conn.rollback()
                        conn.close()
                        flash(f"Due date is required for installment {i}.", "danger")
                        return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                    if amount_due <= 0:
                        conn.rollback()
                        conn.close()
                        flash(f"Amount must be greater than 0 for installment {i}.", "danger")
                        return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                    installment_total += amount_due

                    cur.execute("""
                        SELECT id
                        FROM installment_plans
                        WHERE invoice_id = ? AND installment_no = ?
                    """, (invoice_id, i))
                    existing = cur.fetchone()

                    if existing:
                        cur.execute("""
                            UPDATE installment_plans
                            SET due_date = ?,
                                amount_due = ?,
                                remarks = ?,
                                updated_at = ?
                            WHERE invoice_id = ? AND installment_no = ?
                        """, (due_date, amount_due, remarks, now, invoice_id, i))
                    else:
                        cur.execute("""
                            INSERT INTO installment_plans (
                                invoice_id,
                                installment_no,
                                due_date,
                                amount_due,
                                amount_paid,
                                status,
                                remarks,
                                created_at,
                                updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            invoice_id,
                            i,
                            due_date,
                            amount_due,
                            0,
                            "pending",
                            remarks,
                            now,
                            now
                        ))

                cur.execute("""
                    DELETE FROM installment_plans
                    WHERE invoice_id = ? AND installment_no > ?
                """, (invoice_id, installment_count))

                if abs(installment_total - total_amount) > 0.01:
                    conn.rollback()
                    conn.close()
                    flash("Installment total must equal invoice total amount.", "danger")
                    return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

                # Reallocate existing payments
                cur.execute("""
                    SELECT IFNULL(SUM(amount_received), 0) AS total_received
                    FROM receipts
                    WHERE invoice_id = ?
                """, (invoice_id,))
                total_received = float(cur.fetchone()["total_received"] or 0)

                if total_received > 0:
                    cur.execute("""
                        SELECT id, installment_no, amount_due
                        FROM installment_plans
                        WHERE invoice_id = ?
                        ORDER BY installment_no ASC
                    """, (invoice_id,))
                    new_installments = cur.fetchall()

                    remaining_payment = total_received

                    for installment in new_installments:
                        inst_id = installment["id"]
                        inst_amount_due = float(installment["amount_due"] or 0)

                        if remaining_payment <= 0:
                            cur.execute("""
                                UPDATE installment_plans
                                SET amount_paid = ?, status = 'pending', updated_at = ?
                                WHERE id = ?
                            """, (0, now, inst_id))

                        elif remaining_payment >= inst_amount_due:
                            cur.execute("""
                                UPDATE installment_plans
                                SET amount_paid = ?, status = 'paid', remarks = 'Fully paid', updated_at = ?
                                WHERE id = ?
                            """, (inst_amount_due, now, inst_id))
                            remaining_payment -= inst_amount_due

                        else:
                            cur.execute("""
                                UPDATE installment_plans
                                SET amount_paid = ?, status = 'partially_paid', remarks = ?, updated_at = ?
                                WHERE id = ?
                            """, (remaining_payment, f"Partial payment of {remaining_payment}", now, inst_id))
                            remaining_payment = 0

            # Provision program access based on updated courses in the invoice
            for item in invoice_items_to_save:
                if item.get("course_id"):
                    _provision_program_access_for_course(cur, student_id_form, item["course_id"])

            conn.commit()
            conn.close()

            # Log activity
            log_description = f"Updated invoice {invoice['invoice_no']}"

            if student_id_form != invoice["student_id"]:
                tmp_conn = get_conn()
                tmp_cur = tmp_conn.cursor()
                tmp_cur.execute("""
                    SELECT student_code, full_name
                    FROM students
                    WHERE id = ?
                """, (student_id_form,))
                new_student = tmp_cur.fetchone()
                tmp_conn.close()

                if new_student:
                    log_description += f" - Changed student from {invoice['student_code']} to {new_student['student_code']}"

            log_activity(
                user_id=session["user_id"],
                branch_id=invoice["branch_id"],
                action_type="update",
                module_name="invoices",
                record_id=invoice_id,
                description=log_description
            )

            if student_id_form != invoice["student_id"]:
                flash("Invoice updated successfully. Invoice student changed. All payments and installments now linked to new student.", "warning")
            else:
                flash("Invoice updated successfully.", "success")

            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"An error occurred: {str(e)}", "danger")
            return redirect(url_for("billing.invoice_edit", invoice_id=invoice_id))

    # Fetch courses for dropdown
    cur.execute("""
        SELECT *
        FROM courses
        WHERE is_active = 1
        ORDER BY course_name ASC
    """)
    courses = cur.fetchall()

    # Fetch students for dropdown
    cur.execute("""
        SELECT *
        FROM students
        ORDER BY student_code ASC
    """)
    students = cur.fetchall()

    conn.close()

    # Convert Row objects to dictionaries for JSON serialization in template
    def row_to_dict(row):
        if row is None:
            return None
        try:
            return dict(row)
        except (TypeError, ValueError):
            return row if isinstance(row, dict) else str(row)

    items_dict = [row_to_dict(item) for item in (items or [])]
    installments_dict = [row_to_dict(inst) for inst in (installments or [])]
    courses_dict = [row_to_dict(course) for course in (courses or [])]
    students_dict = [row_to_dict(student) for student in (students or [])]
    invoice_dict = row_to_dict(invoice) if invoice else {}

    return render_template(
        "billing/invoice_form_modern.html",
        invoice=invoice_dict,
        items=items_dict,
        installments=installments_dict,
        courses=courses_dict,
        students=students_dict,
        total_paid=total_paid,
        today=datetime.now().date().isoformat(),
        mode="edit"
    )

@billing_bp.route("/receipts")
@login_required
def receipts():
    search = request.args.get("search", "").strip()
    stats_date_str = request.args.get("stats_date", "").strip()

    conn = get_conn()
    cur = conn.cursor()

    # Get today's date and month range
    today = datetime.now().date()
    first_day_of_month = today.replace(day=1)

    # Use selected date for stats, fall back to today
    try:
        from datetime import date as date_type
        stats_date = date_type.fromisoformat(stats_date_str) if stats_date_str else today
    except ValueError:
        stats_date = today

    # Selected date statistics
    cur.execute("""
        SELECT
            COUNT(*) AS total_receipts,
            IFNULL(SUM(amount_received), 0) AS total_amount,
            SUM(CASE WHEN payment_mode = 'cash' THEN 1 ELSE 0 END) AS cash_count,
            SUM(CASE WHEN payment_mode = 'upi' THEN 1 ELSE 0 END) AS upi_count,
            IFNULL(SUM(CASE WHEN payment_mode = 'cash' THEN amount_received ELSE 0 END), 0) AS cash_amount,
            IFNULL(SUM(CASE WHEN payment_mode = 'upi' THEN amount_received ELSE 0 END), 0) AS upi_amount,
            IFNULL(AVG(amount_received), 0) AS avg_amount
        FROM receipts
        WHERE parse_date(receipt_date) = ?
    """, [stats_date.isoformat()])
    date_stats = cur.fetchone()

    # This month's statistics
    cur.execute("""
        SELECT
            COUNT(*) AS total_receipts,
            IFNULL(SUM(amount_received), 0) AS total_amount,
            SUM(CASE WHEN payment_mode = 'cash' THEN 1 ELSE 0 END) AS cash_count,
            SUM(CASE WHEN payment_mode = 'upi' THEN 1 ELSE 0 END) AS upi_count,
            IFNULL(SUM(CASE WHEN payment_mode = 'cash' THEN amount_received ELSE 0 END), 0) AS cash_amount,
            IFNULL(SUM(CASE WHEN payment_mode = 'upi' THEN amount_received ELSE 0 END), 0) AS upi_amount,
            IFNULL(AVG(amount_received), 0) AS avg_amount
        FROM receipts
        WHERE parse_date(receipt_date) >= ? AND parse_date(receipt_date) <= ?
    """, [first_day_of_month.isoformat(), today.isoformat()])
    month_stats = cur.fetchone()

    query = """
    SELECT
        receipts.id,
        receipts.receipt_no,
        receipts.receipt_date,
        receipts.amount_received,
        receipts.payment_mode,
        receipts.notes,
        receipts.invoice_id,
        invoices.invoice_no,
        invoices.branch_id,
        students.full_name,
        students.student_code,
        users.full_name AS created_by_name
    FROM receipts
    JOIN invoices
        ON receipts.invoice_id = invoices.id
    JOIN students
        ON invoices.student_id = students.id
    LEFT JOIN users
        ON receipts.created_by = users.id
    """

    params = []

    if search:
        query += """
        WHERE
            receipts.receipt_no LIKE ?
            OR invoices.invoice_no LIKE ?
            OR students.full_name LIKE ?
            OR students.student_code LIKE ?
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    query += """
    ORDER BY receipts.id DESC
    """

    cur.execute(query, params)
    all_receipts = cur.fetchall()

    conn.close()

    return render_template(
        "billing/receipts.html",
        receipts=all_receipts,
        search=search,
        date_stats=date_stats,
        stats_date=stats_date.isoformat(),
        today=today.isoformat(),
        month_stats=month_stats
    )

@billing_bp.route("/receipt/new", methods=["GET", "POST"])
@login_required
def receipt_new():
    invoice_id = request.args.get("invoice_id", type=int)

    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        try:
            now = datetime.now().isoformat(timespec="seconds")

            amount_received = float(request.form.get("amount_received", 0) or 0)

            if amount_received <= 0:
                flash("Amount must be greater than 0.", "danger")
                conn.close()
                return redirect(url_for("billing.receipt_new", invoice_id=invoice_id))

            # Get invoice details
            cur.execute("""
                SELECT id, total_amount, branch_id, status
                FROM invoices
                WHERE id = ?
            """, (invoice_id,))
            invoice_data = cur.fetchone()
            
            # Prevent payments on written-off invoices
            if invoice_data and invoice_data["status"] in ["write_off", "partially_written_off"]:
                conn.close()
                flash("Cannot record payments for written-off invoices.", "danger")
                return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

            if not invoice_data:
                conn.close()
                flash("Invoice not found.", "danger")
                return redirect(url_for("billing.invoices"))

            # Calculate balance
            cur.execute("""
                SELECT IFNULL(SUM(amount_received), 0) AS total_received
                FROM receipts
                WHERE invoice_id = ?
            """, (invoice_id,))
            total_received = float(cur.fetchone()["total_received"] or 0)
            balance_amount = float(invoice_data["total_amount"] or 0) - total_received

            if amount_received > balance_amount:
                conn.close()
                flash(f"Amount cannot exceed balance ₹{balance_amount:.2f}", "danger")
                return redirect(url_for("billing.receipt_new", invoice_id=invoice_id))

            payment_mode = request.form.get("payment_mode", "cash").strip()
            notes = request.form.get("notes", "").strip()
            receipt_date = request.form.get("receipt_date")

            # Temporary receipt number
            temp_receipt_no = f"TEMP_{uuid.uuid4().hex[:8]}"

            cur.execute("""
                INSERT INTO receipts (
                    receipt_no,
                    invoice_id,
                    receipt_date,
                    amount_received,
                    payment_mode,
                    notes,
                    created_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                temp_receipt_no,
                invoice_id,
                receipt_date,
                amount_received,
                payment_mode,
                notes,
                session.get("user_id"),
                now
            ))

            receipt_id = cur.lastrowid

            # Final receipt number - Keep GIT/ prefix for receipts
            receipt_no = f"GIT/{receipt_id}"

            cur.execute("""
                UPDATE receipts
                SET receipt_no = ?
                WHERE id = ?
            """, (receipt_no, receipt_id))

            # Update invoice status
            cur.execute("""
                SELECT IFNULL(SUM(amount_received), 0) AS total_received
                FROM receipts
                WHERE invoice_id = ?
            """, (invoice_id,))
            total_received = float(cur.fetchone()["total_received"] or 0)

            cur.execute("""
                SELECT IFNULL(SUM(amount_written_off), 0) AS total_written_off
                FROM bad_debt_writeoffs
                WHERE invoice_id = ?
            """, (invoice_id,))
            total_written_off = float(cur.fetchone()["total_written_off"] or 0)

            covered = round(total_received + total_written_off, 2)
            if covered >= round(invoice_data["total_amount"], 2):
                if total_written_off > 0:
                    new_status = "write_off"
                else:
                    new_status = "paid"
            elif total_written_off > 0:
                new_status = "partially_written_off"
            elif total_received > 0:
                new_status = "partially_paid"
            else:
                new_status = "unpaid"

            cur.execute("""
                UPDATE invoices
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (new_status, now, invoice_id))

            # Installment allocation logic (unchanged, ERP compatible)
            cur.execute("""
                SELECT id, installment_no, amount_due
                FROM installment_plans
                WHERE invoice_id = ?
                ORDER BY installment_no ASC
            """, (invoice_id,))
            installments = cur.fetchall()

            remaining_payment = total_received

            for inst in installments:
                inst_id = inst["id"]
                inst_due = inst["amount_due"]

                if remaining_payment <= 0:
                    cur.execute("""
                        UPDATE installment_plans
                        SET amount_paid = 0, status = 'pending', updated_at = ?
                        WHERE id = ?
                    """, (now, inst_id))

                elif remaining_payment >= inst_due:
                    cur.execute("""
                        UPDATE installment_plans
                        SET amount_paid = ?, status = 'paid',
                            remarks = 'Fully paid', updated_at = ?
                        WHERE id = ?
                    """, (inst_due, now, inst_id))
                    remaining_payment -= inst_due

                else:
                    cur.execute("""
                        UPDATE installment_plans
                        SET amount_paid = ?, status = 'partially_paid',
                            remarks = ?, updated_at = ?
                        WHERE id = ?
                    """, (remaining_payment, f"Partial payment of {remaining_payment}", now, inst_id))
                    remaining_payment = 0

            conn.commit()

            # Auto-send receipt SMS if student has a phone number
            try:
                cur2 = conn.cursor()
                cur2.execute("""
                    SELECT students.full_name, students.phone
                    FROM invoices
                    JOIN students ON invoices.student_id = students.id
                    WHERE invoices.id = ?
                """, (invoice_id,))
                student = cur2.fetchone()

                if student and student["phone"]:
                    phone = student["phone"].strip()
                    if not phone.startswith("+"):
                        phone = "+91" + phone.lstrip("0")

                    token = _make_receipt_token(receipt_id)
                    cur2.execute("UPDATE receipts SET sms_token = ? WHERE id = ?", (token, receipt_id))
                    conn.commit()

                    download_url = url_for(
                        "billing.receipt_public_download",
                        token=token,
                        _external=True
                    )
                    first_name = student["full_name"].split()[0]
                    message = (
                        f"Dear {first_name}, payment of Rs.{amount_received:.0f} received "
                        f"against {receipt_no}. Download your receipt: {download_url} "
                        f"- Global IT Education"
                    )
                    sms_result = send_sms(phone, message)
                    if sms_result.get("success"):
                        sms_now = datetime.now().isoformat(timespec="seconds")
                        cur2.execute(
                            "UPDATE receipts SET sms_sent_at = ? WHERE id = ?",
                            (sms_now, receipt_id)
                        )
                        conn.commit()
                        log_activity(
                            user_id=session.get("user_id"),
                            branch_id=invoice_data["branch_id"],
                            action_type="sms",
                            module_name="receipts",
                            record_id=receipt_id,
                            description=f"Receipt SMS auto-sent to {phone} for {receipt_no}"
                        )
            except Exception as sms_exc:
                # SMS failure must never block receipt creation
                logger.warning("Auto-SMS failed for receipt %s: %s", receipt_no, sms_exc)

            conn.close()

            # 🔥 ERP LOGGING
            log_activity(
                user_id=session.get("user_id"),
                branch_id=invoice_data["branch_id"],
                action_type="create",
                module_name="receipts",
                record_id=receipt_id,
                description=f"Created receipt {receipt_no}"
            )

            flash(f"Receipt {receipt_no} recorded successfully.", "success")
            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error recording payment: {str(e)}", "danger")
            return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

    # ---------- GET ----------
    cur.execute("""
        SELECT invoices.*, students.full_name
        FROM invoices
        JOIN students ON invoices.student_id = students.id
        WHERE invoices.id = ?
    """, (invoice_id,))
    invoice = cur.fetchone()

    if not invoice:
        conn.close()
        flash("Invoice not found.", "danger")
        return redirect(url_for("billing.invoices"))

    # Prevent payments on written-off invoices
    if invoice["status"] in ["write_off", "partially_written_off"]:
        conn.close()
        flash("Cannot record payments for written-off invoices.", "danger")
        return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))

    cur.execute("""
        SELECT IFNULL(SUM(amount_received), 0) AS total_paid
        FROM receipts
        WHERE invoice_id = ?
    """, (invoice_id,))
    total_paid = float(cur.fetchone()["total_paid"] or 0)

    # Subtract any write-offs from the displayed balance
    cur.execute("""
        SELECT COALESCE(SUM(amount_written_off), 0) AS total_written_off
        FROM bad_debt_writeoffs WHERE invoice_id = ?
    """, (invoice_id,))
    written_off_result = cur.fetchone()
    total_written_off_new = float(written_off_result["total_written_off"] or 0) if written_off_result else 0.0
    balance_amount = float(invoice["total_amount"] or 0) - total_paid - total_written_off_new

    conn.close()

    return render_template(
        "billing/receipt_new.html",
        invoice=invoice,
        total_paid=total_paid,
        balance_amount=balance_amount
    )

@billing_bp.route("/receipt/<int:receipt_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def receipt_edit(receipt_id):
    conn = get_conn()
    cur = conn.cursor()

    # Fetch the receipt
    cur.execute("""
        SELECT
            receipts.*,
            invoices.invoice_no,
            invoices.student_id,
            invoices.branch_id,
            students.full_name
        FROM receipts
        JOIN invoices
            ON receipts.invoice_id = invoices.id
        JOIN students
            ON invoices.student_id = students.id
        WHERE receipts.id = ?
    """, (receipt_id,))
    receipt = cur.fetchone()

    if not receipt:
        conn.close()
        flash("Receipt not found.", "danger")
        return redirect(url_for("billing.receipts"))

    if request.method == "POST":
        try:
            now = datetime.now().isoformat(timespec="seconds")

            receipt_date = request.form.get("receipt_date", "").strip()
            amount_received = float(request.form.get("amount_received", 0) or 0)
            payment_mode = request.form.get("payment_mode", "cash").strip()
            notes = request.form.get("notes", "").strip()

            if amount_received <= 0:
                flash("Amount must be greater than 0.", "danger")
                conn.close()
                return redirect(url_for("billing.receipt_edit", receipt_id=receipt_id))

            # Get invoice total
            cur.execute("""
                SELECT total_amount
                FROM invoices
                WHERE id = ?
            """, (receipt["invoice_id"],))
            invoice_row = cur.fetchone()
            invoice_total = float(invoice_row["total_amount"] or 0)

            # Get total of all other receipts except current one
            cur.execute("""
                SELECT IFNULL(SUM(amount_received), 0) AS total_received
                FROM receipts
                WHERE invoice_id = ? AND id != ?
            """, (receipt["invoice_id"], receipt_id))
            other_receipts_total = float(cur.fetchone()["total_received"] or 0)

            # Validate total receipts do not exceed invoice total
            if (amount_received + other_receipts_total) > invoice_total:
                conn.close()
                flash(f"Total receipts cannot exceed invoice amount of ₹{invoice_total:.2f}", "danger")
                return redirect(url_for("billing.receipt_edit", receipt_id=receipt_id))

            # Update receipt
            cur.execute("""
                UPDATE receipts
                SET
                    receipt_date = ?,
                    amount_received = ?,
                    payment_mode = ?,
                    notes = ?
                WHERE id = ?
            """, (
                receipt_date,
                amount_received,
                payment_mode,
                notes,
                receipt_id
            ))

            # Recalculate invoice status
            cur.execute("""
                SELECT IFNULL(SUM(amount_received), 0) AS total_received
                FROM receipts
                WHERE invoice_id = ?
            """, (receipt["invoice_id"],))
            total_received = float(cur.fetchone()["total_received"] or 0)

            # Check current invoice status — don't override write-off statuses
            cur.execute("""
                SELECT status,
                       (SELECT COALESCE(SUM(bw.amount_written_off), 0)
                        FROM bad_debt_writeoffs bw WHERE bw.invoice_id = invoices.id) AS total_written_off
                FROM invoices WHERE id = ?
            """, (receipt["invoice_id"],))
            inv_row = cur.fetchone()
            current_status = inv_row["status"] if inv_row else "unpaid"
            total_written_off = float(inv_row["total_written_off"] or 0) if inv_row else 0.0

            # Recalculate status including any write-offs
            covered = round(total_received + total_written_off, 2)
            if covered >= round(invoice_total, 2):
                if total_written_off > 0:
                    new_status = "write_off"
                else:
                    new_status = "paid"
            elif total_written_off > 0:
                new_status = "partially_written_off"
            elif total_received > 0:
                new_status = "partially_paid"
            else:
                new_status = "unpaid"

            cur.execute("""
                UPDATE invoices
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (new_status, now, receipt["invoice_id"]))

            # Reallocate installment payments based on updated receipt total
            cur.execute("""
                SELECT id, installment_no, amount_due
                FROM installment_plans
                WHERE invoice_id = ?
                ORDER BY installment_no ASC
            """, (receipt["invoice_id"],))
            installments_to_update = cur.fetchall()

            remaining_payment = total_received

            for inst in installments_to_update:
                inst_id = inst["id"]
                inst_due = float(inst["amount_due"] or 0)

                if remaining_payment <= 0:
                    cur.execute("""
                        UPDATE installment_plans
                        SET amount_paid = 0, status = 'pending', updated_at = ?
                        WHERE id = ?
                    """, (now, inst_id))
                elif remaining_payment >= inst_due:
                    cur.execute("""
                        UPDATE installment_plans
                        SET amount_paid = ?, status = 'paid',
                            remarks = 'Fully paid', updated_at = ?
                        WHERE id = ?
                    """, (inst_due, now, inst_id))
                    remaining_payment -= inst_due
                else:
                    cur.execute("""
                        UPDATE installment_plans
                        SET amount_paid = ?, status = 'partially_paid',
                            remarks = ?, updated_at = ?
                        WHERE id = ?
                    """, (remaining_payment, f"Partial payment of {remaining_payment}", now, inst_id))
                    remaining_payment = 0

            conn.commit()
            conn.close()

            log_activity(
                user_id=session.get("user_id"),
                branch_id=receipt["branch_id"],
                action_type="update",
                module_name="receipts",
                record_id=receipt_id,
                description=f"Updated receipt {receipt['receipt_no']}"
            )

            flash(f"Receipt {receipt['receipt_no']} updated successfully.", "success")
            return redirect(url_for("billing.receipt_edit", receipt_id=receipt_id))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error while updating receipt: {str(e)}", "danger")
            return redirect(url_for("billing.receipt_edit", receipt_id=receipt_id))

    conn.close()

    return render_template("billing/receipt_edit.html", receipt=receipt)

@billing_bp.route("/receipt/<int:receipt_id>")
@login_required
def receipt_view(receipt_id):
    conn = get_conn()
    cur = conn.cursor()

    # Fetch the receipt with all details
    cur.execute("""
        SELECT
            receipts.*,
            invoices.id AS invoice_id,
            invoices.invoice_no,
            invoices.total_amount,
            invoices.invoice_date,
            invoices.branch_id,
            students.student_code,
            students.full_name,
            students.phone,
            students.email,
            students.address,
            users.full_name AS created_by_name,
            branches.branch_name
        FROM receipts
        JOIN invoices
            ON receipts.invoice_id = invoices.id
        JOIN students
            ON invoices.student_id = students.id
        LEFT JOIN users
            ON receipts.created_by = users.id
        LEFT JOIN branches
            ON invoices.branch_id = branches.id
        WHERE receipts.id = ?
    """, (receipt_id,))
    receipt = cur.fetchone()

    if not receipt:
        conn.close()
        flash("Receipt not found.", "danger")
        return redirect(url_for("billing.receipts"))

    conn.close()

    return render_template("billing/receipt_view.html", receipt=receipt)

@billing_bp.route("/receipt/<int:receipt_id>/print")
@login_required
def receipt_print(receipt_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            receipts.*,
            invoices.id AS invoice_id,
            invoices.invoice_no,
            invoices.total_amount,
            invoices.invoice_date,
            students.student_code,
            students.full_name,
            students.phone,
            students.email,
            users.full_name AS created_by_name
        FROM receipts
        JOIN invoices ON receipts.invoice_id = invoices.id
        JOIN students ON invoices.student_id = students.id
        LEFT JOIN users ON receipts.created_by = users.id
        WHERE receipts.id = ?
    """, (receipt_id,))
    receipt = cur.fetchone()
    conn.close()

    if not receipt:
        flash("Receipt not found.", "danger")
        return redirect(url_for("billing.receipts"))

    pdf_mode = request.args.get('mode') == 'pdf'

    return render_template("billing/receipt_print.html", receipt=receipt, pdf_mode=pdf_mode)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _receipt_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="receipt-download")


def _invoice_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="invoice-download")


def _make_receipt_token(receipt_id: int) -> str:
    return _receipt_serializer().dumps(receipt_id)


def _make_invoice_token(invoice_id: int) -> str:
    return _invoice_serializer().dumps(invoice_id)


def _verify_receipt_token(token: str, max_age_days: int = 30):
    """Returns receipt_id (int) or raises BadSignature / SignatureExpired."""
    return _receipt_serializer().loads(token, max_age=max_age_days * 86400)


def _verify_invoice_token(token: str, max_age_days: int = 30):
    """Returns invoice_id (int) or raises BadSignature / SignatureExpired."""
    return _invoice_serializer().loads(token, max_age=max_age_days * 86400)


def _load_invoice_print_context(invoice_id, prepared_by_user_id=None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                invoices.id,
                invoices.invoice_no,
                invoices.invoice_date,
                invoices.subtotal,
                invoices.discount_amount,
                invoices.total_amount,
                invoices.status,
                invoices.notes,
                invoices.created_at,
                students.id AS student_id,
                students.student_code,
                students.full_name AS student_name,
                students.phone AS student_phone,
                students.email,
                students.address,
                branches.branch_name
            FROM invoices
            JOIN students ON invoices.student_id = students.id
            LEFT JOIN branches ON invoices.branch_id = branches.id
            WHERE invoices.id = ?
        """, (invoice_id,))
        invoice = cur.fetchone()

        if not invoice:
            return None

        cur.execute("""
            SELECT
                id,
                course_id,
                description,
                quantity,
                unit_price,
                discount,
                line_total
            FROM invoice_items
            WHERE invoice_id = ?
            ORDER BY id ASC
        """, (invoice_id,))
        items = cur.fetchall()

        cur.execute("""
            SELECT
                id,
                installment_no,
                due_date,
                amount_due,
                amount_paid,
                status,
                remarks
            FROM installment_plans
            WHERE invoice_id = ?
            ORDER BY installment_no ASC
        """, (invoice_id,))
        installments = cur.fetchall()

        cur.execute("""
            SELECT
                receipts.id,
                receipts.receipt_no,
                receipts.receipt_date,
                receipts.amount_received,
                receipts.created_at,
                receipts.created_by,
                IFNULL(users.full_name, 'System') AS created_by_name
            FROM receipts
            LEFT JOIN users ON receipts.created_by = users.id
            WHERE receipts.invoice_id = ?
            ORDER BY receipts.id DESC
        """, (invoice_id,))
        payments = cur.fetchall()

        cur.execute("""
            SELECT IFNULL(SUM(amount_received), 0) AS total_paid
            FROM receipts
            WHERE invoice_id = ?
        """, (invoice_id,))
        paid_result = cur.fetchone()
        total_paid = float(paid_result["total_paid"] or 0) if paid_result else 0.0

        balance_amount = float(invoice["total_amount"] or 0) - total_paid
        net_total = float(invoice["total_amount"] or 0)

        prepared_by = "Administrator"
        if prepared_by_user_id:
            cur.execute("SELECT full_name FROM users WHERE id = ?", (prepared_by_user_id,))
            user_result = cur.fetchone()
            if user_result:
                prepared_by = user_result["full_name"]

        return {
            "invoice": invoice,
            "invoice_items": items,
            "installment_plans": installments,
            "receipts": payments,
            "total_paid": total_paid,
            "balance_amount": balance_amount,
            "net_total": net_total,
            "prepared_by": prepared_by,
        }
    finally:
        conn.close()


# ── Public receipt download (no login required) ──────────────────────────────

@billing_bp.route("/receipt/download/<token>")
def receipt_public_download(token):
    """Token-protected public link; lets a student view/download their receipt PDF."""
    try:
        receipt_id = _verify_receipt_token(token)
    except SignatureExpired:
        return render_template("billing/receipt_token_expired.html"), 410
    except (BadSignature, Exception):
        return render_template("billing/receipt_token_invalid.html"), 403

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            receipts.*,
            invoices.id AS invoice_id,
            invoices.invoice_no,
            invoices.total_amount,
            invoices.invoice_date,
            students.student_code,
            students.full_name,
            students.phone,
            students.email,
            users.full_name AS created_by_name
        FROM receipts
        JOIN invoices ON receipts.invoice_id = invoices.id
        JOIN students ON invoices.student_id = students.id
        LEFT JOIN users ON receipts.created_by = users.id
        WHERE receipts.id = ?
    """, (receipt_id,))
    receipt = cur.fetchone()
    conn.close()

    if not receipt:
        return "Receipt not found.", 404

    # Render in PDF-auto-download mode so the student gets a file immediately
    return render_template("billing/receipt_print.html", receipt=receipt, pdf_mode=True)


# ── Send Receipt SMS ──────────────────────────────────────────────────────────

@billing_bp.route("/invoice/download/<token>")
def invoice_public_download(token):
    """Token-protected public link; lets a student view/download their invoice PDF."""
    try:
        invoice_id = _verify_invoice_token(token)
    except SignatureExpired:
        return render_template("billing/receipt_token_expired.html"), 410
    except (BadSignature, Exception):
        return render_template("billing/receipt_token_invalid.html"), 403

    context = _load_invoice_print_context(invoice_id)
    if not context:
        return "Invoice not found.", 404

    return render_template("billing/invoice_print.html", **context, pdf_mode=True)


def _send_invoice_sms_link(invoice_id, user_id=None, branch_id=None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                invoices.id,
                invoices.invoice_no,
                invoices.total_amount,
                invoices.sms_token,
                students.full_name,
                students.phone
            FROM invoices
            JOIN students ON invoices.student_id = students.id
            WHERE invoices.id = ?
        """, (invoice_id,))
        invoice = cur.fetchone()

        if not invoice:
            return {"success": False, "error": "Invoice not found."}

        phone = normalize_sms_phone(invoice["phone"])
        if not phone:
            return {"success": False, "error": "Student has no phone number on record."}

        token = invoice["sms_token"]
        if not token:
            token = _make_invoice_token(invoice_id)
            cur.execute("UPDATE invoices SET sms_token = ? WHERE id = ?", (token, invoice_id))
            conn.commit()

        download_url = url_for(
            "billing.invoice_public_download",
            token=token,
            _external=True,
        )

        student_name = (invoice["full_name"] or "Student").split()[0]
        amount = float(invoice["total_amount"] or 0)
        invoice_no = invoice["invoice_no"]
        message = (
            f"Dear {student_name}, invoice {invoice_no} for Rs.{amount:.0f} is ready. "
            f"Download your invoice: {download_url} - Global IT Education"
        )

        result = send_sms(phone, message)
        if result.get("success"):
            sms_now = datetime.now().isoformat(timespec="seconds")
            cur.execute(
                "UPDATE invoices SET sms_sent_at = ? WHERE id = ?",
                (sms_now, invoice_id),
            )
            conn.commit()
            log_activity(
                user_id=user_id,
                branch_id=branch_id,
                action_type="sms",
                module_name="invoices",
                record_id=invoice_id,
                description=f"Invoice SMS sent to {phone} for {invoice_no}",
            )
            return {"success": True, "phone": phone, "invoice_no": invoice_no}

        return {"success": False, "error": result.get("error", "Unknown error")}
    finally:
        conn.close()


@billing_bp.route("/invoice/<int:invoice_id>/send-sms", methods=["POST"])
@login_required
def invoice_send_sms(invoice_id):
    result = _send_invoice_sms_link(
        invoice_id,
        user_id=session.get("user_id"),
        branch_id=session.get("branch_id"),
    )
    if result.get("success"):
        flash(f"Invoice SMS sent to {result.get('phone')}.", "success")
    else:
        flash(f"SMS failed: {result.get('error', 'Unknown error')}", "danger")
    return redirect(url_for("billing.invoice_view", invoice_id=invoice_id))


@billing_bp.route("/receipt/<int:receipt_id>/send-sms", methods=["POST"])
@login_required
def receipt_send_sms(receipt_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            receipts.*,
            invoices.invoice_no,
            invoices.total_amount,
            students.full_name,
            students.phone
        FROM receipts
        JOIN invoices ON receipts.invoice_id = invoices.id
        JOIN students ON invoices.student_id = students.id
        WHERE receipts.id = ?
    """, (receipt_id,))
    receipt = cur.fetchone()

    if not receipt:
        conn.close()
        flash("Receipt not found.", "danger")
        return redirect(url_for("billing.receipts"))

    phone = (receipt["phone"] or "").strip()
    if not phone:
        conn.close()
        flash("Student has no phone number on record.", "warning")
        return redirect(url_for("billing.receipt_view", receipt_id=receipt_id))

    # Generate (or reuse) a token — stored in DB so we can audit it
    token = receipt["sms_token"]
    if not token:
        token = _make_receipt_token(receipt_id)
        cur.execute("UPDATE receipts SET sms_token = ? WHERE id = ?", (token, receipt_id))
        conn.commit()

    # Build the public download URL
    download_url = url_for(
        "billing.receipt_public_download",
        token=token,
        _external=True
    )

    # Format phone to E.164 (assume India +91 if no country code)
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")

    student_name = receipt["full_name"].split()[0]  # first name only
    amount = receipt["amount_received"]
    receipt_no = receipt["receipt_no"]

    message = (
        f"Dear {student_name}, payment of Rs.{amount:.0f} received against {receipt_no}. "
        f"Download your receipt: {download_url} - Global IT Education"
    )

    result = send_sms(phone, message)

    now = datetime.now().isoformat(timespec="seconds")
    if result.get("success"):
        cur.execute(
            "UPDATE receipts SET sms_sent_at = ? WHERE id = ?",
            (now, receipt_id)
        )
        conn.commit()
        log_activity(
            user_id=session.get("user_id"),
            branch_id=None,
            action_type="sms",
            module_name="receipts",
            record_id=receipt_id,
            description=f"Receipt SMS sent to {phone} for {receipt_no}"
        )
        flash(f"Receipt SMS sent to {phone}.", "success")
    else:
        flash(f"SMS failed: {result.get('error', 'Unknown error')}", "danger")

    conn.close()
    return redirect(url_for("billing.receipt_view", receipt_id=receipt_id))


@billing_bp.route("/receivables")
@login_required
def receivables():
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()
    branch_id = request.args.get("branch_id", "").strip()
    trainer_id = request.args.get("trainer_id", "").strip()
    user_role = session.get("role", "staff")

    # Branches for filter
    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    # Trainers for filter dropdown (only for admin)
    available_trainers = []
    if user_role == "admin":
        cur.execute("""
            SELECT DISTINCT u.id, u.full_name
            FROM users u
            JOIN batches bt ON bt.trainer_id = u.id
            WHERE bt.status = 'active'
            ORDER BY u.full_name ASC
        """)
        available_trainers = cur.fetchall()

    # Trainer filter SQL snippet (added to WHERE clause of each query)
    trainer_filter_sql = ""
    trainer_filter_param = []
    if trainer_id:
        trainer_filter_sql = """
          AND s.id IN (
              SELECT DISTINCT sb.student_id
              FROM student_batches sb
              JOIN batches bt ON sb.batch_id = bt.id
              WHERE bt.trainer_id = ? AND sb.status = 'active'
          )
        """
        trainer_filter_param = [trainer_id]

    # Past dues
    past_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            i.branch_id,
            s.id AS student_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            s.photo_filename,
            b.branch_name,
            (ip.amount_due - ip.amount_paid) AS balance_due,
            (SELECT GROUP_CONCAT(bt.batch_name, ', ')
             FROM student_batches sb
             JOIN batches bt ON sb.batch_id = bt.id
             WHERE sb.student_id = s.id AND sb.status = 'active') AS batch_names,
            (SELECT GROUP_CONCAT(DISTINCT u.full_name)
             FROM student_batches sb
             JOIN batches bt ON sb.batch_id = bt.id
             JOIN users u ON bt.trainer_id = u.id
             WHERE sb.student_id = s.id AND sb.status = 'active') AS trainer_names
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        LEFT JOIN branches b
            ON i.branch_id = b.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) < ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
          AND (
            (SELECT COALESCE(SUM(r.amount_received), 0) FROM receipts r WHERE r.invoice_id = i.id)
            + (SELECT COALESCE(SUM(bw.amount_written_off), 0) FROM bad_debt_writeoffs bw WHERE bw.invoice_id = i.id)
          ) < i.total_amount
    """
    past_dues_params = [today]

    if branch_id:
        past_dues_query += " AND i.branch_id = ?"
        past_dues_params.append(branch_id)

    if trainer_filter_sql:
        past_dues_query += trainer_filter_sql
        past_dues_params.extend(trainer_filter_param)

    past_dues_query += " ORDER BY parse_date(ip.due_date) ASC"

    cur.execute(past_dues_query, past_dues_params)
    past_dues = cur.fetchall()

    # Today's dues
    todays_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            i.branch_id,
            s.id AS student_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            s.photo_filename,
            b.branch_name,
            (ip.amount_due - ip.amount_paid) AS balance_due,
            (SELECT GROUP_CONCAT(bt.batch_name, ', ')
             FROM student_batches sb
             JOIN batches bt ON sb.batch_id = bt.id
             WHERE sb.student_id = s.id AND sb.status = 'active') AS batch_names,
            (SELECT GROUP_CONCAT(DISTINCT u.full_name)
             FROM student_batches sb
             JOIN batches bt ON sb.batch_id = bt.id
             JOIN users u ON bt.trainer_id = u.id
             WHERE sb.student_id = s.id AND sb.status = 'active') AS trainer_names
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        LEFT JOIN branches b
            ON i.branch_id = b.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) = ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
          AND (
            (SELECT COALESCE(SUM(r.amount_received), 0) FROM receipts r WHERE r.invoice_id = i.id)
            + (SELECT COALESCE(SUM(bw.amount_written_off), 0) FROM bad_debt_writeoffs bw WHERE bw.invoice_id = i.id)
          ) < i.total_amount
    """
    todays_dues_params = [today]

    if branch_id:
        todays_dues_query += " AND i.branch_id = ?"
        todays_dues_params.append(branch_id)

    if trainer_filter_sql:
        todays_dues_query += trainer_filter_sql
        todays_dues_params.extend(trainer_filter_param)

    todays_dues_query += " ORDER BY s.full_name ASC"

    cur.execute(todays_dues_query, todays_dues_params)
    todays_dues = cur.fetchall()

    # Upcoming dues
    upcoming_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            i.branch_id,
            s.id AS student_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            s.photo_filename,
            b.branch_name,
            (ip.amount_due - ip.amount_paid) AS balance_due,
            (SELECT GROUP_CONCAT(bt.batch_name, ', ')
             FROM student_batches sb
             JOIN batches bt ON sb.batch_id = bt.id
             WHERE sb.student_id = s.id AND sb.status = 'active') AS batch_names,
            (SELECT GROUP_CONCAT(DISTINCT u.full_name)
             FROM student_batches sb
             JOIN batches bt ON sb.batch_id = bt.id
             JOIN users u ON bt.trainer_id = u.id
             WHERE sb.student_id = s.id AND sb.status = 'active') AS trainer_names
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        LEFT JOIN branches b
            ON i.branch_id = b.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) > ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
          AND (
            (SELECT COALESCE(SUM(r.amount_received), 0) FROM receipts r WHERE r.invoice_id = i.id)
            + (SELECT COALESCE(SUM(bw.amount_written_off), 0) FROM bad_debt_writeoffs bw WHERE bw.invoice_id = i.id)
          ) < i.total_amount
    """
    upcoming_dues_params = [today]

    if branch_id:
        upcoming_dues_query += " AND i.branch_id = ?"
        upcoming_dues_params.append(branch_id)

    if trainer_filter_sql:
        upcoming_dues_query += trainer_filter_sql
        upcoming_dues_params.extend(trainer_filter_param)

    upcoming_dues_query += " ORDER BY parse_date(ip.due_date) ASC LIMIT 50"

    cur.execute(upcoming_dues_query, upcoming_dues_params)
    upcoming_dues = cur.fetchall()

    total_past_due = sum(float(row["balance_due"] or 0) for row in past_dues)
    total_today_due = sum(float(row["balance_due"] or 0) for row in todays_dues)
    total_upcoming_due = sum(float(row["balance_due"] or 0) for row in upcoming_dues)

    # Expected receivables for the current month + next two months
    current_month_start = datetime.now().date().replace(day=1)

    def _add_months(base_date, months_to_add):
        month_index = (base_date.month - 1) + months_to_add
        year = base_date.year + (month_index // 12)
        month = (month_index % 12) + 1
        return date(year, month, 1)

    month_starts = [_add_months(current_month_start, offset) for offset in range(3)]
    receivables_window_end = _add_months(current_month_start, 3)

    monthly_expected_query = """
        SELECT
            substr(parse_date(ip.due_date), 1, 7) AS month_key,
            SUM(ip.amount_due - ip.amount_paid) AS total_due,
            COUNT(*) AS item_count
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) >= ?
          AND parse_date(ip.due_date) < ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
          AND (
            (SELECT COALESCE(SUM(r.amount_received), 0) FROM receipts r WHERE r.invoice_id = i.id)
            + (SELECT COALESCE(SUM(bw.amount_written_off), 0) FROM bad_debt_writeoffs bw WHERE bw.invoice_id = i.id)
          ) < i.total_amount
    """
    monthly_expected_params = [
        current_month_start.isoformat(),
        receivables_window_end.isoformat(),
    ]

    if branch_id:
        monthly_expected_query += " AND i.branch_id = ?"
        monthly_expected_params.append(branch_id)

    if trainer_filter_sql:
        monthly_expected_query += trainer_filter_sql
        monthly_expected_params.extend(trainer_filter_param)

    monthly_expected_query += " GROUP BY month_key ORDER BY month_key ASC"

    cur.execute(monthly_expected_query, monthly_expected_params)
    monthly_expected_rows = cur.fetchall()
    monthly_expected_map = {
        row["month_key"]: {
            "total_due": float(row["total_due"] or 0),
            "item_count": int(row["item_count"] or 0),
        }
        for row in monthly_expected_rows
    }

    monthly_expected_receivables = []
    for month_start in month_starts:
        month_key = month_start.strftime("%Y-%m")
        month_data = monthly_expected_map.get(month_key, {})
        monthly_expected_receivables.append({
            "month_key": month_key,
            "month_label": month_start.strftime("%b"),
            "month_year": month_start.year,
            "total_due": float(month_data.get("total_due", 0)),
            "item_count": int(month_data.get("item_count", 0)),
        })

    total_three_month_expected = sum(
        row["total_due"] for row in monthly_expected_receivables
    )

    visible_student_ids = sorted({
        row["student_id"]
        for row in list(past_dues) + list(todays_dues) + list(upcoming_dues)
        if row["student_id"] is not None
    })
    try:
        attendance_base_date = date.fromisoformat(today)
    except Exception:
        attendance_base_date = datetime.now().date()
    receivable_attendance_dates = [
        (attendance_base_date - timedelta(days=i)).isoformat()
        for i in range(6, -1, -1)
    ]
    receivable_attendance_history = {}

    if visible_student_ids:
        date_placeholders = ",".join(["?"] * len(receivable_attendance_dates))
        student_placeholders = ",".join(["?"] * len(visible_student_ids))
        cur.execute(f"""
            SELECT student_id, attendance_date, status
            FROM attendance_records
            WHERE attendance_date IN ({date_placeholders})
              AND student_id IN ({student_placeholders})
        """, receivable_attendance_dates + visible_student_ids)
        for row in cur.fetchall():
            sid = row["student_id"]
            receivable_attendance_history.setdefault(sid, {})[row["attendance_date"]] = row["status"]

        cur.execute(f"""
            SELECT student_id, from_date, to_date
            FROM leave_requests
            WHERE status = 'approved'
              AND student_id IN ({student_placeholders})
              AND date(from_date) <= date(?)
              AND date(to_date) >= date(?)
        """, visible_student_ids + [receivable_attendance_dates[-1], receivable_attendance_dates[0]])
        for row in cur.fetchall():
            sid = row["student_id"]
            student_history = receivable_attendance_history.setdefault(sid, {})
            try:
                leave_start = date.fromisoformat(str(row["from_date"])[:10])
                leave_end = date.fromisoformat(str(row["to_date"])[:10])
            except Exception:
                continue
            for att_date in receivable_attendance_dates:
                current_date = date.fromisoformat(att_date)
                if leave_start <= current_date <= leave_end and att_date not in student_history:
                    student_history[att_date] = "leave"

    # Reminder stats per installment
    all_ids = [r['id'] for r in list(past_dues) + list(todays_dues) + list(upcoming_dues)]
    reminder_stats = {}
    if all_ids:
        placeholders = ','.join(['?'] * len(all_ids))
        cur.execute(f"""
            SELECT installment_id, COUNT(*) as count, MAX(sent_at) as last_sent_at
            FROM reminder_logs
            WHERE installment_id IN ({placeholders})
            GROUP BY installment_id
        """, all_ids)
        reminder_stats = {row['installment_id']: dict(row) for row in cur.fetchall()}

    conn.close()

    return render_template(
        "billing/receivables.html",
        past_dues=past_dues,
        todays_dues=todays_dues,
        upcoming_dues=upcoming_dues,
        total_past_due=total_past_due,
        total_today_due=total_today_due,
        total_upcoming_due=total_upcoming_due,
        monthly_expected_receivables=monthly_expected_receivables,
        total_three_month_expected=total_three_month_expected,
        today=today,
        branches=branches,
        branch_id=branch_id,
        reminder_stats=reminder_stats,
        receivable_attendance_dates=receivable_attendance_dates,
        receivable_attendance_history=receivable_attendance_history,
        available_trainers=available_trainers,
        trainer_id=trainer_id,
        user_role=user_role
    )


@billing_bp.route("/reminder/log", methods=["POST"])
@login_required
def reminder_log():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400

    installment_id = data.get("installment_id")
    invoice_id = data.get("invoice_id")
    student_id = data.get("student_id")
    phone_number = data.get("phone_number", "")
    reminder_type = data.get("reminder_type", "")
    message_text = data.get("message_text", "")
    status = data.get("status", "sent")
    sent_via = data.get("sent_via", "manual")

    if not all([installment_id, invoice_id, student_id, reminder_type, message_text]):
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    user_id = session.get("user_id")

    cur.execute("""
        INSERT INTO reminder_logs (
            student_id, invoice_id, installment_id, phone_number,
            reminder_type, message_text, status, sent_via, sent_by, sent_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (student_id, invoice_id, installment_id, phone_number,
          reminder_type, message_text, status, sent_via, user_id, now))
    conn.commit()
    log_id = cur.lastrowid
    conn.close()

    return jsonify({"success": True, "log_id": log_id, "sent_at": now})


@billing_bp.route("/reminder/send-sms", methods=["POST"])
@login_required
def reminder_send_sms():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400

    installment_id = data.get("installment_id")
    reminder_type = data.get("reminder_type", "")
    message_text = (data.get("message_text") or "").strip()

    if not installment_id or not reminder_type or not message_text:
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            ip.id AS installment_id,
            i.id AS invoice_id,
            i.invoice_no,
            i.branch_id,
            s.id AS student_id,
            s.full_name AS student_name,
            s.phone AS student_phone
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.id = ?
    """, (installment_id,))
    reminder = cur.fetchone()

    if not reminder:
        conn.close()
        return jsonify({"success": False, "error": "Installment not found"}), 404

    phone = normalize_sms_phone(reminder["student_phone"])
    if not phone:
        conn.close()
        return jsonify({"success": False, "error": "Student has no phone number on record"}), 400

    result = send_sms(phone, message_text)
    now = datetime.now().isoformat(timespec="seconds")
    status = "sent" if result.get("success") else "failed"
    user_id = session.get("user_id")

    cur.execute("""
        INSERT INTO reminder_logs (
            student_id, invoice_id, installment_id, phone_number,
            reminder_type, message_text, status, sent_via, sent_by, sent_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        reminder["student_id"],
        reminder["invoice_id"],
        reminder["installment_id"],
        phone,
        reminder_type,
        message_text,
        status,
        "sms",
        user_id,
        now,
    ))
    log_id = cur.lastrowid
    conn.commit()

    if result.get("success"):
        log_activity(
            user_id=user_id,
            branch_id=reminder["branch_id"],
            action_type="sms",
            module_name="receivables",
            record_id=reminder["installment_id"],
            description=f"Fee reminder SMS sent to {phone} for {reminder['invoice_no']}"
        )
        conn.close()
        return jsonify({
            "success": True,
            "log_id": log_id,
            "sent_at": now,
            "message_id": result.get("message_id"),
            "status": result.get("status"),
        })

    error = result.get("error", "SMS failed")
    conn.close()
    return jsonify({
        "success": False,
        "log_id": log_id,
        "sent_at": now,
        "error": error,
    }), 502


@billing_bp.route("/expenses")
@login_required
def expenses():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            expenses.*,
            branches.branch_name,
            expense_categories.category_name,
            users.full_name AS created_by_name
        FROM expenses
        JOIN branches
            ON expenses.branch_id = branches.id
        JOIN expense_categories
            ON expenses.category_id = expense_categories.id
        LEFT JOIN users
            ON expenses.created_by = users.id
        ORDER BY expenses.expense_date DESC, expenses.id DESC
    """)
    expenses = cur.fetchall()

    cur.execute("""
        SELECT IFNULL(SUM(amount), 0) AS total_expense
        FROM expenses
    """)
    total_expense = float(cur.fetchone()["total_expense"] or 0)

    conn.close()

    return render_template(
        "billing/expenses.html",
        expenses=expenses,
        total_expense=total_expense
    )

@billing_bp.route("/expense/new", methods=["GET", "POST"])
@login_required
def expense_new():
    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        try:
            expense_date = request.form.get("expense_date")
            branch_id = request.form.get("branch_id")
            category_id = request.form.get("category_id")
            title = request.form.get("title", "").strip()
            amount = float(request.form.get("amount", 0))
            payment_mode = request.form.get("payment_mode")
            reference_no = request.form.get("reference_no", "").strip()
            notes = request.form.get("notes", "").strip()

            # ✅ Validations
            if not title:
                flash("Expense title is required.", "danger")
                return redirect(url_for("billing.expense_new"))

            if amount <= 0:
                flash("Expense amount must be greater than 0.", "danger")
                return redirect(url_for("billing.expense_new"))

            now = datetime.now().isoformat(timespec="seconds")

            cur.execute("""
                INSERT INTO expenses (
                    expense_date,
                    branch_id,
                    category_id,
                    title,
                    amount,
                    payment_mode,
                    reference_no,
                    notes,
                    created_by,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                expense_date,
                branch_id,
                category_id,
                title,
                amount,
                payment_mode,
                reference_no,
                notes,
                session.get("user_id"),
                now,
                now
            ))

            expense_id = cur.lastrowid
            conn.commit()

            # ✅ Activity Log (ERP Standard)
            log_activity(
                user_id=session.get("user_id"),
                branch_id=branch_id,
                action_type="create",
                module_name="expense",
                record_id=expense_id,
                description=f"Created expense '{title}' of ₹{amount:.2f}"
            )

            flash("Expense recorded successfully.", "success")
            return redirect(url_for("billing.expenses"))

        except Exception as e:
            conn.rollback()
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("billing.expense_new"))

        finally:
            conn.close()

    # ✅ GET Data
    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM expense_categories
        WHERE is_active = 1
        ORDER BY category_name
    """)
    categories = cur.fetchall()

    conn.close()

    today = datetime.today().strftime("%Y-%m-%d")

    return render_template(
        "billing/expense_form.html",
        branches=branches,
        categories=categories,
        today=today
    )

@billing_bp.route("/expense-categories")
@login_required
def expense_categories():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM expense_categories
        ORDER BY category_name ASC
    """)
    categories = cur.fetchall()

    conn.close()

    return render_template(
        "billing/expense_categories.html",
        categories=categories
    )

@billing_bp.route("/expense-category/new", methods=["GET", "POST"])
@login_required
def expense_category_new():

    if request.method == "POST":
        category_name = request.form.get("category_name", "").strip()

        if not category_name:
            flash("Category name is required.", "danger")
            return redirect(url_for("billing.expense_category_new"))

        conn = get_conn()
        cur = conn.cursor()

        # Check duplicate
        cur.execute("""
            SELECT id FROM expense_categories 
            WHERE category_name = ?
        """, (category_name,))
        existing = cur.fetchone()

        if existing:
            conn.close()
            flash("Category already exists.", "danger")
            return redirect(url_for("billing.expense_category_new"))

        try:
            now = datetime.now().isoformat(timespec="seconds")

            cur.execute("""
                INSERT INTO expense_categories (
                    category_name,
                    is_active,
                    created_at
                )
                VALUES (?, ?, ?)
            """, (
                category_name,
                1,
                now
            ))

            category_id = cur.lastrowid
            conn.commit()

            # ✅ ERP logging (as you requested)
            log_activity(
                user_id=session.get("user_id"),
                branch_id=session.get("branch_id"),
                action_type="create",
                module_name="expense_category",
                record_id=category_id,
                description=f"Created expense category '{category_name}'"
            )

            flash("Expense category created successfully.", "success")
            return redirect(url_for("billing.expense_categories"))

        except Exception as e:
            conn.rollback()
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("billing.expense_category_new"))

        finally:
            conn.close()

    return render_template("billing/expense_category_form.html")

@billing_bp.route("/activity-logs", methods=["GET"])
@login_required
def activity_logs():
    if session.get("role") != "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("billing.dashboard"))

    conn = get_conn()
    cur = conn.cursor()

    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    user_id = request.args.get("user_id", "").strip()
    branch_id = request.args.get("branch_id", "").strip()
    module_name = request.args.get("module_name", "").strip()

    today = datetime.today().strftime("%Y-%m-%d")

    if not from_date:
        from_date = today
    if not to_date:
        to_date = today

    cur.execute("""
        SELECT id, full_name, username
        FROM users
        WHERE is_active = 1
        ORDER BY full_name
    """)
    users = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    cur.execute("""
        SELECT DISTINCT module_name
        FROM activity_logs
        ORDER BY module_name
    """)
    modules = cur.fetchall()

    query = """
        SELECT
            activity_logs.*,
            users.full_name,
            users.username,
            branches.branch_name
        FROM activity_logs
        LEFT JOIN users
            ON activity_logs.user_id = users.id
        LEFT JOIN branches
            ON activity_logs.branch_id = branches.id
        WHERE substr(activity_logs.created_at, 1, 10) BETWEEN ? AND ?
    """
    params = [from_date, to_date]

    if user_id:
        query += " AND activity_logs.user_id = ? "
        params.append(user_id)

    if branch_id:
        query += " AND activity_logs.branch_id = ? "
        params.append(branch_id)

    if module_name:
        query += " AND activity_logs.module_name = ? "
        params.append(module_name)

    query += " ORDER BY activity_logs.id DESC "

    cur.execute(query, params)
    logs = cur.fetchall()

    conn.close()

    return render_template(
        "billing/activity_logs.html",
        logs=logs,
        users=users,
        branches=branches,
        modules=modules,
        from_date=from_date,
        to_date=to_date,
        user_id=user_id,
        branch_id=branch_id,
        module_name=module_name
    )


@billing_bp.route("/student/<int:student_id>/toggle-program-access/<int:program_id>", methods=["POST"])
@login_required
@admin_required
def student_toggle_program_access(student_id, program_id):
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("SELECT id, full_name, branch_id FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("billing.students"))
        
    cur.execute("SELECT id, program_name FROM lms_programs WHERE id = ?", (program_id,))
    program = cur.fetchone()
    if not program:
        conn.close()
        flash("LMS program not found.", "danger")
        return redirect(url_for("billing.student_profile", student_id=student_id))
        
    cur.execute("""
        SELECT id, is_active FROM lms_student_program_access
        WHERE student_id = ? AND program_id = ?
    """, (student_id, program_id))
    existing = cur.fetchone()
    
    now_date = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat(timespec="seconds")
    
    if existing:
        new_status = 0 if existing["is_active"] == 1 else 1
        cur.execute("""
            UPDATE lms_student_program_access
            SET is_active = ?, access_status = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, "active" if new_status == 1 else "suspended", now_iso, existing["id"]))
        action = "suspended" if new_status == 0 else "restored"
    else:
        cur.execute("""
            INSERT INTO lms_student_program_access (
                student_id, program_id, access_start_date, access_status, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, 'suspended', 0, ?, ?)
        """, (student_id, program_id, now_date, now_iso, now_iso))
        action = "suspended"
        
    conn.commit()
    conn.close()
    
    log_activity(
        user_id=session["user_id"],
        branch_id=student["branch_id"] or session.get("branch_id"),
        action_type="update",
        module_name="students",
        record_id=student_id,
        description=f"LMS Access for program '{program['program_name']}' was {action} for student {student['full_name']}"
    )
    
    flash(f"LMS Access for '{program['program_name']}' was {action} successfully.", "success")
    return redirect(url_for("billing.student_profile", student_id=student_id))


