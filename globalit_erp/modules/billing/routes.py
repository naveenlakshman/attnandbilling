from flask import Blueprint, render_template, request, session
from datetime import date, datetime
import calendar
from db import get_conn
from modules.core.utils import login_required

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