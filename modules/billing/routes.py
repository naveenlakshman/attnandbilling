from flask import Blueprint, render_template, request, session, redirect, url_for, flash, Response
from datetime import date, datetime, timedelta
import calendar
import uuid
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required
import io
import csv
import os
import base64


QUALIFICATION_LEVELS = {
    "School": [
        "5th Standard",
        "6th Standard",
        "7th Standard",
        "8th Standard",
        "9th Standard",
        "10th Standard / SSLC"
    ],
    "Pre-University": [
        "1st PUC",
        "2nd PUC"
    ],
    "Diploma": [
        "Diploma 1st Year",
        "Diploma 2nd Year",
        "Diploma 3rd Year",
        "Diploma Completed"
    ],
    "Undergraduate": [
        "B.Com",
        "BBA",
        "BBM",
        "BA",
        "BCA",
        "B.Sc",
        "BE",
        "B.Tech",
        "Degree 1st Year",
        "Degree 2nd Year",
        "Degree 3rd Year",
        "Undergraduate Completed"
    ],
    "Technical": [
        "ITI",
        "Polytechnic",
        "Certification Course"
    ],
    "Postgraduate": [
        "M.Com",
        "MBA",
        "MCA",
        "M.Sc",
        "MA",
        "Postgraduate Completed"
    ]
}

billing_bp = Blueprint("billing", __name__)

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

    student_query = "SELECT COUNT(*) AS total_students FROM students"
    student_params = []

    invoice_count_query = "SELECT COUNT(*) AS total_invoices FROM invoices"
    invoice_count_params = []

    sales_query = "SELECT IFNULL(SUM(total_amount), 0) AS total_sales FROM invoices"
    sales_params = []

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
        student_query += " WHERE branch_id = ?"
        student_params.append(branch_id)

        invoice_count_query += " WHERE branch_id = ?"
        invoice_count_params.append(branch_id)

        sales_query += " WHERE (branch_id = ? OR branch_id IS NULL)"
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
    """
    monthly_sales_params = []

    if branch_id:
        monthly_sales_query += " WHERE branch_id = ?"
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
    if status_filter:
        query += " AND students.status = ?"
        params.append(status_filter)

    query += " ORDER BY students.id DESC"

    cur.execute(query, params)
    students = cur.fetchall()

    # Branches for filter dropdown
    cur.execute("""
        SELECT id, branch_name, branch_code
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    conn.close()

    return render_template(
        "billing/students.html",
        students=students,
        branches=branches,
        search_query=search_query,
        branch_filter=branch_filter,
        status_filter=status_filter,
        stats=stats,
        branch_stats=branch_stats
    )

@billing_bp.route("/student/new", methods=["GET", "POST"])
@login_required
def student_new():
    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        branch_id = request.form["branch_id"]
        full_name = request.form["full_name"].strip()
        phone = request.form["phone"].strip()
        gender = request.form.get("gender", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        education_level = request.form.get("education_level", "").strip()
        qualification = request.form.get("qualification", "").strip()
        student_location = request.form.get("student_location", "").strip()
        employment_status = request.form.get("employment_status", "").strip()
        status = request.form.get("status", "active").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip() or None
        parent_name = request.form.get("parent_name", "").strip() or None
        parent_contact = request.form.get("parent_contact", "").strip() or None
        photo_data = request.form.get("photo_data", "").strip()

        # Get next registration number
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
                education_level,
                qualification,
                student_location,
                employment_status,
                date_of_birth,
                parent_name,
                parent_contact,
                joined_date,
                status,
                branch_id,
                photo_filename,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(next_reg_no),
            full_name,
            phone,
            gender,
            email,
            address,
            education_level,
            qualification,
            student_location,
            employment_status,
            date_of_birth,
            parent_name,
            parent_contact,
            now,
            status,
            branch_id,
            photo_filename,
            now,
            now
        ))

        student_id = cur.lastrowid
        conn.commit()
        conn.close()

        log_activity(
            user_id=session["user_id"],
            branch_id=branch_id,
            action_type="create",
            module_name="students",
            record_id=student_id,
            description=f"Created student {full_name} (Reg No: {next_reg_no})"
        )

        flash("Student added successfully.", "success")
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
        student=None,
        branches=branches,
        education_levels=QUALIFICATION_LEVELS.keys(),
        qualification_levels=QUALIFICATION_LEVELS
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
        branch_id = request.form["branch_id"]
        full_name = request.form["full_name"].strip()
        phone = request.form["phone"].strip()
        gender = request.form.get("gender", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        education_level = request.form.get("education_level", "").strip()
        qualification = request.form.get("qualification", "").strip()
        student_location = request.form.get("student_location", "").strip()
        employment_status = request.form.get("employment_status", "").strip()
        status = request.form.get("status", "active").strip()
        date_of_birth = request.form.get("date_of_birth", "").strip() or None
        parent_name = request.form.get("parent_name", "").strip() or None
        parent_contact = request.form.get("parent_contact", "").strip() or None
        photo_data = request.form.get("photo_data", "").strip()

        # Save photo if provided
        # Row objects don't have .get() method, use bracket notation instead
        try:
            photo_filename = student["photo_filename"] if "photo_filename" in student.keys() else None
        except:
            photo_filename = None
        
        if photo_data:
            photo_filename = save_student_photo(photo_data, student["student_code"])

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            UPDATE students
            SET branch_id = ?,
                full_name = ?,
                phone = ?,
                gender = ?,
                email = ?,
                address = ?,
                education_level = ?,
                qualification = ?,
                student_location = ?,
                employment_status = ?,
                date_of_birth = ?,
                parent_name = ?,
                parent_contact = ?,
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
            education_level,
            qualification,
            student_location,
            employment_status,
            date_of_birth,
            parent_name,
            parent_contact,
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

    total_invoices = int(invoice_summary["total_invoices"] or 0)
    total_billed = float(invoice_summary["total_billed"] or 0)
    total_paid = float(payment_summary["total_paid"] or 0)
    total_balance = total_billed - total_paid

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
        total_balance=total_balance
    )

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
        ORDER BY id DESC
    """)
    courses = cur.fetchall()

    conn.close()

    return render_template("billing/courses.html", courses=courses)


@billing_bp.route("/course/new", methods=["GET", "POST"])
@login_required
def course_new():
    if request.method == "POST":
        course_name = request.form["course_name"].strip()
        duration = request.form["duration"].strip()
        fee = request.form["fee"].strip()

        conn = get_conn()
        cur = conn.cursor()

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            INSERT INTO courses (
                course_name,
                duration,
                fee,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            course_name,
            duration,
            fee,
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

    return render_template("billing/course_form.html", course=None)


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

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            UPDATE courses
            SET course_name = ?,
                duration = ?,
                fee = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            course_name,
            duration,
            fee,
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
    return render_template("billing/course_form.html", course=course)

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

    # For written-off invoices, balance is zero (cannot receive further payments)
    if invoice["status"] in ["write_off", "partially_written_off"]:
        balance_amount = 0.0
    else:
        balance_amount = float(invoice["total_amount"] or 0) - total_paid - total_written_off

    conn.close()

    return render_template(
        "billing/invoice_view.html",
        invoice=invoice,
        items=items,
        installments=installments,
        payments=payments,
        total_paid=total_paid,
        balance_amount=balance_amount,
        total_written_off=total_written_off
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

    return render_template(
        "billing/invoice_print.html",
        invoice=invoice,
        invoice_items=items,
        installment_plans=installments,
        receipts=payments,
        total_paid=total_paid,
        balance_amount=balance_amount,
        net_total=net_total,
        prepared_by=prepared_by
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

@billing_bp.route("/invoice/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    student_full_name = None
    
    if request.method == "POST":
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
                    "line_total": line_total
                })

            if not invoice_items_to_save:
                flash("Please enter at least one valid bill item.", "danger")
                return redirect(url_for("billing.invoice_new"))

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
                        line_total,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    item["course_id"],
                    item["description"],
                    item["quantity"],
                    item["unit_price"],
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

            conn.commit()

            # Extract student name before closing connection to avoid Row access after close
            student_full_name = str(student['full_name'])

            log_activity(
                user_id=session["user_id"],
                branch_id=branch_id,
                action_type="create",
                module_name="invoices",
                record_id=invoice_id,
                description=f"Created invoice {invoice_no} for student {student_full_name}"
            )
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

    return render_template(
        "billing/invoice_form_modern.html",
        students=students_dict,
        courses=courses_dict,
        today=today,
        mode="create"
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
                        line_total,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id,
                    item["course_id"],
                    item["description"],
                    item["quantity"],
                    item["unit_price"],
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

    conn = get_conn()
    cur = conn.cursor()

    # Get today's date and month range
    today = datetime.now().date()
    first_day_of_month = today.replace(day=1)

    # Today's statistics
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
    """, [today.isoformat()])
    today_stats = cur.fetchone()

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
        today_stats=today_stats,
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

            if total_received >= invoice_data["total_amount"]:
                new_status = "paid"
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
                        SET status = 'pending', updated_at = ?
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
    balance_amount = float(invoice["total_amount"] or 0) - total_paid

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

            if total_received >= invoice_total:
                new_status = "paid"
            elif total_received > 0:
                new_status = "partially_paid"
            else:
                new_status = "unpaid"

            cur.execute("""
                UPDATE invoices
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (new_status, now, receipt["invoice_id"]))

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

@billing_bp.route("/receivables")
@login_required
def receivables():
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()
    branch_id = request.args.get("branch_id", "").strip()

    # Branches for filter
    cur.execute("""
        SELECT *
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

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
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            b.branch_name,
            (ip.amount_due - ip.amount_paid) AS balance_due
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
    """
    past_dues_params = [today]

    if branch_id:
        past_dues_query += " AND i.branch_id = ?"
        past_dues_params.append(branch_id)

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
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            b.branch_name,
            (ip.amount_due - ip.amount_paid) AS balance_due
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
    """
    todays_dues_params = [today]

    if branch_id:
        todays_dues_query += " AND i.branch_id = ?"
        todays_dues_params.append(branch_id)

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
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            b.branch_name,
            (ip.amount_due - ip.amount_paid) AS balance_due
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
    """
    upcoming_dues_params = [today]

    if branch_id:
        upcoming_dues_query += " AND i.branch_id = ?"
        upcoming_dues_params.append(branch_id)

    upcoming_dues_query += " ORDER BY parse_date(ip.due_date) ASC LIMIT 50"

    cur.execute(upcoming_dues_query, upcoming_dues_params)
    upcoming_dues = cur.fetchall()

    total_past_due = sum(float(row["balance_due"] or 0) for row in past_dues)
    total_today_due = sum(float(row["balance_due"] or 0) for row in todays_dues)
    total_upcoming_due = sum(float(row["balance_due"] or 0) for row in upcoming_dues)

    conn.close()

    return render_template(
        "billing/receivables.html",
        past_dues=past_dues,
        todays_dues=todays_dues,
        upcoming_dues=upcoming_dues,
        total_past_due=total_past_due,
        total_today_due=total_today_due,
        total_upcoming_due=total_upcoming_due,
        today=today,
        branches=branches,
        branch_id=branch_id
    )

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

