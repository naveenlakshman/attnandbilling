from flask import Blueprint, render_template, request, session, redirect, url_for, flash, Response
from datetime import date, datetime
import calendar
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required
import io
import csv


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

@billing_bp.route("/dashboard")
@login_required
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
        stats=stats
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
        employment_status = request.form.get("employment_status", "").strip()
        status = request.form.get("status", "active").strip()

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
                employment_status,
                joined_date,
                status,
                branch_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(next_reg_no),
            full_name,
            phone,
            gender,
            email,
            address,
            education_level,
            qualification,
            employment_status,
            now,
            status,
            branch_id,
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
        employment_status = request.form.get("employment_status", "").strip()
        status = request.form.get("status", "active").strip()

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
                employment_status = ?,
                status = ?,
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
            employment_status,
            status,
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