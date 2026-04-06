import io
import csv
from flask import Blueprint, render_template, send_file, flash, redirect, url_for, session, request
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, timezone

reports_bp = Blueprint("reports", __name__)


def parse_date(date_str):
    """
    Parse date in multiple formats: DD-MM-YYYY or YYYY-MM-DD
    Returns date in YYYY-MM-DD format for database storage
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Try YYYY-MM-DD format first
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # Try DD-MM-YYYY format
    try:
        parsed = datetime.strptime(date_str, "%d-%m-%Y")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # Try DD/MM/YYYY format
    try:
        parsed = datetime.strptime(date_str, "%d/%m/%Y")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # If all fail, return None indicating invalid format
    return None

@reports_bp.route("/")
@login_required
@admin_required
def dashboard():
    """Analytics and Reports Dashboard"""
    conn = get_conn()
    cur = conn.cursor()
    
    # Get record counts for each table
    stats = {}
    
    tables = [
        ("branches", "Branches"),
        ("users", "Users"),
        ("leads", "Leads"),
        ("students", "Students"),
        ("courses", "Courses"),
        ("invoices", "Invoices"),
        ("receipts", "Receipts"),
        ("expenses", "Expenses"),
        ("expense_categories", "Expense Categories"),
        ("followups", "Followups"),
        ("installment_plans", "Installment Plans"),
        ("invoice_items", "Invoice Items"),
        ("activity_logs", "Activity Logs")
    ]
    
    for table_name, display_name in tables:
        try:
            cur.execute(f"SELECT COUNT(*) as count FROM {table_name}")
            result = cur.fetchone()
            stats[table_name] = {
                "name": display_name,
                "count": result["count"] if result else 0
            }
        except Exception as e:
            stats[table_name] = {
                "name": display_name,
                "count": 0,
                "error": str(e)
            }
    
    conn.close()
    
    return render_template("reports/dashboard.html", stats=stats)


@reports_bp.route("/daily")
@login_required
def daily_report():
    """Daily consolidated report: Leads, Invoices, Receipts, Attendance"""
    IST = timezone(timedelta(hours=5, minutes=30))
    today_default = datetime.now(IST).strftime("%Y-%m-%d")

    report_date = request.args.get("date", today_default).strip()
    # Validate date
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        report_date = today_default

    conn = get_conn()
    cur = conn.cursor()

    # ── Branches ──────────────────────────────────────────────────
    cur.execute("SELECT id, branch_name, branch_code FROM branches WHERE is_active = 1 ORDER BY branch_name")
    branches = cur.fetchall()

    # Branch selection
    can_view_all = session.get("can_view_all_branches", False) or session.get("role") == "admin"
    user_branch_id = session.get("branch_id")
    branch_param = request.args.get("branch_id", "").strip()
    if can_view_all and branch_param:
        selected_branch_id = int(branch_param) if branch_param.isdigit() else None
    else:
        selected_branch_id = user_branch_id

    # ── 1. Today's Leads (global – no branch_id on leads table) ──
    cur.execute("""
        SELECT l.id, l.name, l.phone, l.lead_source, l.stage, l.status, l.created_at,
               u.full_name AS owner_name
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE substr(l.created_at, 1, 10) = ? AND l.is_deleted = 0
        ORDER BY l.created_at DESC
    """, (report_date,))
    new_leads = cur.fetchall()

    # ── 2. Today's Followups due ──────────────────────────────────
    cur.execute("""
        SELECT id, name, phone, stage, status, next_followup_date
        FROM leads
        WHERE next_followup_date = ? AND is_deleted = 0
        ORDER BY name
    """, (report_date,))
    followups_due = cur.fetchall()

    # ── 2b. Today's Followups done (actually logged today) ────────
    cur.execute("""
        SELECT f.id, f.method, f.outcome, f.note, f.created_at,
               l.id AS lead_id, l.name AS lead_name, l.phone AS lead_phone,
               u.full_name AS done_by
        FROM followups f
        JOIN leads l ON f.lead_id = l.id
        LEFT JOIN users u ON f.user_id = u.id
        WHERE substr(f.created_at, 1, 10) = ? AND l.is_deleted = 0
        ORDER BY f.created_at DESC
    """, (report_date,))
    followups_done = cur.fetchall()

    # ── 3. Today's Invoices ───────────────────────────────────────
    invoice_query = """
        SELECT i.id, i.invoice_no, i.invoice_date, i.total_amount, i.status,
               IFNULL((SELECT SUM(r2.amount_received) FROM receipts r2 WHERE r2.invoice_id = i.id), 0) AS paid_amount,
               (i.total_amount - IFNULL((SELECT SUM(r2.amount_received) FROM receipts r2 WHERE r2.invoice_id = i.id), 0)) AS balance_amount,
               s.full_name AS student_name, s.student_code, s.id AS student_id,
               br.branch_name
        FROM invoices i
        JOIN students s ON i.student_id = s.id
        LEFT JOIN branches br ON i.branch_id = br.id
        WHERE parse_date(i.invoice_date) = ?
    """
    invoice_params = [report_date]
    if selected_branch_id:
        invoice_query += " AND i.branch_id = ?"
        invoice_params.append(selected_branch_id)
    invoice_query += " ORDER BY i.created_at DESC"
    cur.execute(invoice_query, invoice_params)
    invoices = cur.fetchall()

    # ── 4. Today's Receipts ───────────────────────────────────────
    receipt_query = """
        SELECT r.id, r.receipt_no, r.receipt_date, r.amount_received, r.payment_mode,
               s.full_name AS student_name, s.student_code, i.invoice_no,
               br.branch_name
        FROM receipts r
        JOIN invoices i ON r.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        LEFT JOIN branches br ON i.branch_id = br.id
        WHERE parse_date(r.receipt_date) = ?
    """
    receipt_params = [report_date]
    if selected_branch_id:
        receipt_query += " AND i.branch_id = ?"
        receipt_params.append(selected_branch_id)
    receipt_query += " ORDER BY r.created_at DESC"
    cur.execute(receipt_query, receipt_params)
    receipts = cur.fetchall()

    # ── 5. Today's Attendance ─────────────────────────────────────
    att_summary = {"present": 0, "absent": 0, "late": 0, "leave": 0, "total": 0}
    att_records = []
    if selected_branch_id:
        cur.execute("""
            SELECT ar.status, COUNT(*) AS cnt
            FROM attendance_records ar
            WHERE ar.attendance_date = ? AND ar.branch_id = ?
            GROUP BY ar.status
        """, (report_date, selected_branch_id))
        for row in cur.fetchall():
            s = row["status"]
            if s in att_summary:
                att_summary[s] = row["cnt"]
            att_summary["total"] += row["cnt"]

        cur.execute("""
            SELECT ar.status, s.full_name AS student_name, s.student_code,
                   b.batch_name
            FROM attendance_records ar
            JOIN students s ON ar.student_id = s.id
            JOIN batches b ON ar.batch_id = b.id
            WHERE ar.attendance_date = ? AND ar.branch_id = ?
            ORDER BY b.batch_name, s.full_name
        """, (report_date, selected_branch_id))
        att_records = cur.fetchall()

    conn.close()

    # Summary totals
    totals = {
        "new_leads": len(new_leads),
        "followups": len(followups_due),
        "followups_done": len(followups_done),
        "invoices": len(invoices),
        "invoice_amount": sum(r["total_amount"] or 0 for r in invoices),
        "receipts": len(receipts),
        "receipt_amount": sum(r["amount_received"] or 0 for r in receipts),
        "attendance": att_summary["total"],
    }

    return render_template(
        "reports/daily.html",
        report_date=report_date,
        branches=branches,
        selected_branch_id=selected_branch_id,
        can_view_all=can_view_all,
        new_leads=new_leads,
        followups_due=followups_due,
        followups_done=followups_done,
        invoices=invoices,
        receipts=receipts,
        att_summary=att_summary,
        att_records=att_records,
        totals=totals,
    )


@reports_bp.route("/daily/download")
@login_required
def daily_report_download():
    """Download daily report as CSV (all sections)"""
    IST = timezone(timedelta(hours=5, minutes=30))
    today_default = datetime.now(IST).strftime("%Y-%m-%d")

    report_date = request.args.get("date", today_default).strip()
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        report_date = today_default

    conn = get_conn()
    cur = conn.cursor()

    can_view_all = session.get("can_view_all_branches", False) or session.get("role") == "admin"
    user_branch_id = session.get("branch_id")
    branch_param = request.args.get("branch_id", "").strip()
    if can_view_all and branch_param:
        selected_branch_id = int(branch_param) if branch_param.isdigit() else None
    else:
        selected_branch_id = user_branch_id

    # ── Branch name for filename ──────────────────────────────────
    branch_label = ""
    if selected_branch_id:
        cur.execute("SELECT branch_name FROM branches WHERE id = ?", (selected_branch_id,))
        br = cur.fetchone()
        if br:
            branch_label = "_" + br["branch_name"].replace(" ", "_")

    # ── New Leads ─────────────────────────────────────────────────
    cur.execute("""
        SELECT l.id, l.name, l.phone, l.lead_source, l.stage, l.status, l.created_at,
               u.full_name AS owner_name
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE substr(l.created_at, 1, 10) = ? AND l.is_deleted = 0
        ORDER BY l.created_at DESC
    """, (report_date,))
    new_leads = cur.fetchall()

    # ── Followups (due) ───────────────────────────────────────────
    cur.execute("""
        SELECT id, name, phone, stage, status, next_followup_date
        FROM leads
        WHERE next_followup_date = ? AND is_deleted = 0
        ORDER BY name
    """, (report_date,))
    followups_due = cur.fetchall()

    # ── Followups done today ──────────────────────────────────────
    cur.execute("""
        SELECT f.id, f.method, f.outcome, f.note, f.created_at,
               l.name AS lead_name, l.phone AS lead_phone,
               u.full_name AS done_by
        FROM followups f
        JOIN leads l ON f.lead_id = l.id
        LEFT JOIN users u ON f.user_id = u.id
        WHERE substr(f.created_at, 1, 10) = ? AND l.is_deleted = 0
        ORDER BY f.created_at DESC
    """, (report_date,))
    followups_done = cur.fetchall()

    # ── Invoices ──────────────────────────────────────────────────
    invoice_query = """
        SELECT i.invoice_no, i.invoice_date, s.full_name AS student_name, s.student_code,
               i.total_amount,
               IFNULL((SELECT SUM(r2.amount_received) FROM receipts r2 WHERE r2.invoice_id = i.id), 0) AS paid_amount,
               (i.total_amount - IFNULL((SELECT SUM(r2.amount_received) FROM receipts r2 WHERE r2.invoice_id = i.id), 0)) AS balance_amount,
               i.status, br.branch_name
        FROM invoices i
        JOIN students s ON i.student_id = s.id
        LEFT JOIN branches br ON i.branch_id = br.id
        WHERE parse_date(i.invoice_date) = ?
    """
    invoice_params = [report_date]
    if selected_branch_id:
        invoice_query += " AND i.branch_id = ?"
        invoice_params.append(selected_branch_id)
    invoice_query += " ORDER BY i.created_at DESC"
    cur.execute(invoice_query, invoice_params)
    invoices = cur.fetchall()

    # ── Receipts ──────────────────────────────────────────────────
    receipt_query = """
        SELECT r.receipt_no, r.receipt_date, s.full_name AS student_name, s.student_code,
               i.invoice_no, r.amount_received, r.payment_mode, br.branch_name
        FROM receipts r
        JOIN invoices i ON r.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        LEFT JOIN branches br ON i.branch_id = br.id
        WHERE parse_date(r.receipt_date) = ?
    """
    receipt_params = [report_date]
    if selected_branch_id:
        receipt_query += " AND i.branch_id = ?"
        receipt_params.append(selected_branch_id)
    receipt_query += " ORDER BY r.created_at DESC"
    cur.execute(receipt_query, receipt_params)
    receipts = cur.fetchall()

    # ── Attendance ────────────────────────────────────────────────
    att_records = []
    if selected_branch_id:
        cur.execute("""
            SELECT s.full_name AS student_name, s.student_code,
                   b.batch_name, ar.status
            FROM attendance_records ar
            JOIN students s ON ar.student_id = s.id
            JOIN batches b ON ar.batch_id = b.id
            WHERE ar.attendance_date = ? AND ar.branch_id = ?
            ORDER BY b.batch_name, s.full_name
        """, (report_date, selected_branch_id))
        att_records = cur.fetchall()

    conn.close()

    # ── Build CSV ─────────────────────────────────────────────────
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Daily Report – {report_date}{(' – ' + br['branch_name']) if selected_branch_id and br else ''}"])
    writer.writerow([])

    # Section 1: New Leads
    writer.writerow(["NEW LEADS"])
    writer.writerow(["#", "Name", "Phone", "Source", "Stage", "Status", "Time"])
    for i, l in enumerate(new_leads, 1):
        writer.writerow([i, l["name"], l["phone"] or "", l["lead_source"] or "",
                         l["stage"] or "", l["status"] or "",
                         (l["created_at"] or "")[11:16]])
    if not new_leads:
        writer.writerow(["No new leads"])
    writer.writerow([])

    # Section 2: Followups
    writer.writerow(["FOLLOWUPS DUE"])
    writer.writerow(["#", "Name", "Phone", "Stage", "Status"])
    for i, f in enumerate(followups_due, 1):
        writer.writerow([i, f["name"], f["phone"] or "", f["stage"] or "", f["status"] or ""])
    if not followups_due:
        writer.writerow(["No followups today"])
    writer.writerow([])

    # Section 2b: Followups Done Today
    writer.writerow(["FOLLOWUPS DONE TODAY"])
    writer.writerow(["#", "Lead Name", "Phone", "Method", "Outcome", "Note", "Done By", "Time (IST)"])
    for i, f in enumerate(followups_done, 1):
        from datetime import datetime as _dt, timedelta as _td
        try:
            t = _dt.fromisoformat(f["created_at"]) + _td(hours=5, minutes=30)
            time_str = t.strftime("%I:%M %p")
        except Exception:
            time_str = (f["created_at"] or "")[11:16]
        writer.writerow([i, f["lead_name"], f["lead_phone"] or "",
                         f["method"] or "", f["outcome"] or "",
                         f["note"] or "", f["done_by"] or "", time_str])
    if not followups_done:
        writer.writerow(["No followups logged today"])
    writer.writerow([])

    # Section 3: Invoices
    writer.writerow(["INVOICES"])
    writer.writerow(["#", "Invoice No.", "Date", "Student", "Reg. No", "Total", "Paid", "Balance", "Status", "Branch"])
    inv_total = inv_paid = inv_balance = 0
    for i, inv in enumerate(invoices, 1):
        writer.writerow([i, inv["invoice_no"], inv["invoice_date"], inv["student_name"],
                         inv["student_code"], inv["total_amount"] or 0,
                         inv["paid_amount"] or 0, inv["balance_amount"] or 0,
                         inv["status"] or "", inv["branch_name"] or ""])
        inv_total += inv["total_amount"] or 0
        inv_paid += inv["paid_amount"] or 0
        inv_balance += inv["balance_amount"] or 0
    if not invoices:
        writer.writerow(["No invoices today"])
    else:
        writer.writerow(["", "", "", "", "TOTAL", inv_total, inv_paid, inv_balance, "", ""])
    writer.writerow([])

    # Section 4: Receipts
    writer.writerow(["RECEIPTS"])
    writer.writerow(["#", "Receipt No.", "Date", "Student", "Reg. No", "Invoice No.", "Amount", "Mode", "Branch"])
    rec_total = 0
    for i, r in enumerate(receipts, 1):
        writer.writerow([i, r["receipt_no"], r["receipt_date"], r["student_name"],
                         r["student_code"], r["invoice_no"],
                         r["amount_received"] or 0, r["payment_mode"] or "", r["branch_name"] or ""])
        rec_total += r["amount_received"] or 0
    if not receipts:
        writer.writerow(["No receipts today"])
    else:
        writer.writerow(["", "", "", "", "", "TOTAL", rec_total, "", ""])
    writer.writerow([])

    # Section 5: Attendance
    writer.writerow(["ATTENDANCE"])
    if att_records:
        writer.writerow(["#", "Student", "Reg. No", "Batch", "Status"])
        for i, a in enumerate(att_records, 1):
            writer.writerow([i, a["student_name"], a["student_code"], a["batch_name"], a["status"]])
    elif not selected_branch_id:
        writer.writerow(["Select a branch to include attendance data"])
    else:
        writer.writerow(["No attendance recorded for this branch today"])

    csv_data = output.getvalue()
    output.close()

    buf = io.BytesIO()
    buf.write(csv_data.encode("utf-8-sig"))  # utf-8-sig adds BOM for Excel compatibility
    buf.seek(0)

    filename = f"daily_report_{report_date}{branch_label}.csv"
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=filename)


@reports_bp.route("/export/<table_name>")
@login_required
@admin_required
def export_csv(table_name):
    """Export any table to CSV"""
    
    # Allowed tables for export
    allowed_tables = {
        "activity_logs": "activity_logs",
        "branches": "branches",
        "courses": "courses",
        "expense_categories": "expense_categories",
        "expenses": "expenses",
        "followups": "followups",
        "installment_plans": "installment_plans",
        "invoice_items": "invoice_items",
        "invoices": "invoices",
        "leads": "leads",
        "receipts": "receipts",
        "students": "students",
        "users": "users"
    }
    
    if table_name not in allowed_tables:
        flash(f"Invalid table: {table_name}", "danger")
        return redirect(url_for("reports.dashboard"))
    
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        # Get all data from the table
        cur.execute(f"SELECT * FROM {allowed_tables[table_name]}")
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            flash(f"No data in {table_name}.", "warning")
            return redirect(url_for("reports.dashboard"))
        
        # Get column names
        columns = [description[0] for description in cur.description]
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(columns)
        
        # Write data
        for row in rows:
            row_data = []
            for col in columns:
                value = row[col]
                
                # Format created_at for followups table to match import format
                if table_name == "followups" and col == "created_at" and value:
                    try:
                        if 'T' in str(value):
                            dt = datetime.fromisoformat(value)
                            value = dt.strftime("%d-%m-%Y %I:%M %p")  # 23-03-2026 02:30 PM
                    except (ValueError, AttributeError):
                        pass
                
                # Format next_followup_date for followups table
                if table_name == "followups" and col == "next_followup_date" and value:
                    try:
                        dt = datetime.strptime(str(value), "%Y-%m-%d")
                        value = dt.strftime("%d-%m-%Y")  # 23-03-2026
                    except (ValueError, AttributeError):
                        pass
                
                row_data.append(value if value is not None else "")
            writer.writerow(row_data)
        
        csv_data = output.getvalue()
        output.close()
        
        # Create response
        response_file = io.BytesIO()
        response_file.write(csv_data.encode())
        response_file.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{table_name}_{timestamp}.csv"
        
        return send_file(
            response_file,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        conn.close()
        flash(f"Error exporting {table_name}: {str(e)}", "danger")
        return redirect(url_for("reports.dashboard"))


@reports_bp.route("/export-leads-detailed")
@login_required
@admin_required
def export_leads_detailed():
    """Export detailed leads report with related data"""
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT 
                leads.id,
                leads.name,
                leads.phone,
                leads.whatsapp,
                leads.gender,
                leads.age,
                leads.education_status,
                leads.stream,
                leads.institute_name,
                leads.career_goal,
                leads.interested_courses,
                leads.lead_source,
                leads.decision_maker,
                leads.lead_location,
                leads.start_timeframe,
                leads.lead_score,
                leads.stage,
                leads.status,
                leads.last_contact_date,
                leads.next_followup_date,
                leads.notes,
                users.full_name as assigned_to,
                leads.created_at,
                leads.updated_at
            FROM leads
            LEFT JOIN users ON leads.assigned_to_id = users.id
            WHERE leads.is_deleted = 0
            ORDER BY leads.created_at DESC
        """)
        
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            flash("No leads data to export.", "warning")
            return redirect(url_for("reports.dashboard"))
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = [
            "ID", "Name", "Phone", "WhatsApp", "Gender", "Age", 
            "Education Status", "Stream", "Institute", "Career Goal",
            "Interested Courses", "Lead Source", "Decision Maker", "Lead Location",
            "Start Timeframe", "Lead Score", "Stage", "Status",
            "Last Contact", "Next Follow-up", "Notes", "Assigned To", "Created", "Updated"
        ]
        writer.writerow(headers)
        
        for row in rows:
            writer.writerow([
                row["id"],
                row["name"],
                row["phone"],
                row["whatsapp"] or "",
                row["gender"] or "",
                row["age"] or "",
                row["education_status"] or "",
                row["stream"] or "",
                row["institute_name"] or "",
                row["career_goal"] or "",
                row["interested_courses"] or "",
                row["lead_source"] or "",
                row["decision_maker"] or "",
                row["lead_location"] or "",
                row["start_timeframe"] or "",
                row["lead_score"] or "",
                row["stage"],
                row["status"],
                row["last_contact_date"] or "",
                row["next_followup_date"] or "",
                row["notes"] or "",
                row["assigned_to"] or "",
                row["created_at"],
                row["updated_at"] or ""
            ])
        
        csv_data = output.getvalue()
        output.close()
        
        response_file = io.BytesIO()
        response_file.write(csv_data.encode())
        response_file.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"leads_detailed_{timestamp}.csv"
        
        return send_file(
            response_file,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        conn.close()
        flash(f"Error exporting leads: {str(e)}", "danger")
        return redirect(url_for("reports.dashboard"))


@reports_bp.route("/export-students-detailed")
@login_required
@admin_required
def export_students_detailed():
    """Export detailed students report"""
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT 
                students.id,
                students.student_code,
                students.full_name,
                students.phone,
                students.email,
                students.gender,
                students.address,
                students.education_level,
                students.qualification,
                students.student_location,
                students.employment_status,
                students.status,
                branches.branch_name,
                students.joined_date,
                students.created_at
            FROM students
            LEFT JOIN branches ON students.branch_id = branches.id
            ORDER BY students.created_at DESC
        """)
        
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            flash("No students data to export.", "warning")
            return redirect(url_for("reports.dashboard"))
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = [
            "ID", "Student Code", "Full Name", "Phone", "Email", "Gender",
            "Address", "Education Level", "Qualification", "Student Location",
            "Employment Status", "Status", "Branch", "Joined Date", "Created"
        ]
        writer.writerow(headers)
        
        for row in rows:
            writer.writerow([
                row["id"],
                row["student_code"],
                row["full_name"],
                row["phone"],
                row["email"] or "",
                row["gender"] or "",
                row["address"] or "",
                row["education_level"] or "",
                row["qualification"] or "",
                row["student_location"] or "",
                row["employment_status"] or "",
                row["status"],
                row["branch_name"] or "",
                row["joined_date"],
                row["created_at"]
            ])
        
        csv_data = output.getvalue()
        output.close()
        
        response_file = io.BytesIO()
        response_file.write(csv_data.encode())
        response_file.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"students_detailed_{timestamp}.csv"
        
        return send_file(
            response_file,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        conn.close()
        flash(f"Error exporting students: {str(e)}", "danger")
        return redirect(url_for("reports.dashboard"))


@reports_bp.route("/import")
@login_required
@admin_required
def import_page():
    """CSV Import Management Page"""
    return render_template("reports/import.html")


@reports_bp.route("/sample/<table_name>")
@login_required
@admin_required
def download_sample(table_name):
    """Download sample CSV file for a table"""
    
    samples = {
        "branches": {
            "headers": ["branch_name", "branch_code", "address", "is_active"],
            "rows": [
                ["Head Office", "HO", "Main branch address", "1"],
                ["Branch 1", "B1", "Branch 1 address", "1"],
            ]
        },
        "courses": {
            "headers": ["course_name", "duration", "fee", "course_type", "is_active"],
            "rows": [
                ["Tally", "45 Days", "5000", "standard", "1"],
                ["Excel Advanced", "30 Days", "4000", "standard", "1"],
            ]
        },
        "leads": {
            "headers": ["name", "phone", "whatsapp", "gender", "age", "education_status", "stream", "institute_name", "career_goal", "interested_courses", "lead_source", "decision_maker", "lead_location", "start_timeframe", "lead_score", "stage", "status", "lost_reason", "last_contact_date", "next_followup_date", "followup_count", "notes", "assigned_to_id"],
            "rows": [
                ["John Doe", "9876543210", "9876543210", "Male", "25", "Graduate", "Commerce", "ABC Institute", "Job", "Tally,Excel", "Walk-in", "Self", "urban", "Immediately", "8", "New Lead", "active", "", "21-03-2026", "28-03-2026", "1", "Interested in Tally", "1"],
                ["Jane Smith", "9123456789", "9123456789", "Female", "22", "School", "Science", "XYZ School", "Skill Development", "Excel,Power BI", "Referral", "Parents", "rural", "Within 1 Month", "7", "Converted", "active", "", "20-03-2026", "27-03-2026", "3", "Converted to student", ""],
            ]
        },
        "students": {
            "headers": ["student_code", "full_name", "phone", "email", "gender", "address", "education_level", "qualification", "student_location", "employment_status", "status", "branch_id", "joined_date"],
            "rows": [
                ["1515001", "Student Name", "9876543210", "student@example.com", "Male", "Address", "Undergraduate", "BE", "urban", "student", "active", "1", "21-03-2026"],
                ["1515002", "Another Student", "9123456789", "student2@example.com", "Female", "Address", "School", "12th", "rural", "unemployed", "active", "1", "21-03-2026"],
            ]
        },
        "invoices": {
            "headers": ["invoice_number", "student_id", "invoice_date", "subtotal", "discount_type", "discount_value", "discount_amount", "total_amount", "installment_type", "notes", "status", "created_by", "branch_id"],
            "rows": [
                ["GIT/B/001", "1", "21-03-2026", "5000", "percentage", "10", "500", "4500", "full", "Course Fee", "unpaid", "1", "1"],
                ["GIT/B/002", "2", "20-03-2026", "4000", "fixed", "300", "300", "3700", "installment", "Excel training", "unpaid", "1", "1"],
            ]
        },
        "receipts": {
            "headers": ["receipt_number", "invoice_id", "receipt_date", "amount_received", "payment_mode", "notes"],
            "rows": [
                ["GIT/RCP/001", "1", "21-03-2026", "5000", "cash", "Full payment"],
                ["GIT/RCP/002", "2", "20-03-2026", "2000", "bank_transfer", "First installment"],
            ]
        },
        "installments": {
            "headers": ["invoice_id", "installment_number", "due_date", "amount", "status"],
            "rows": [
                ["1", "1", "21-04-2026", "2500", "pending"],
                ["1", "2", "21-05-2026", "2500", "pending"],
            ]
        },
        "expenses": {
            "headers": ["expense_type", "category", "amount", "description", "expense_date", "branch_id"],
            "rows": [
                ["rent", "office", "20000", "Monthly office rent", "21-03-2026", "1"],
                ["utilities", "office", "5000", "Electricity bill", "21-03-2026", "1"],
            ]
        },
        "activity_logs": {
            "headers": ["user_id", "branch_id", "action_type", "module_name", "record_id", "description"],
            "rows": [
                ["1", "1", "create", "leads", "1", "Created new lead"],
                ["1", "1", "update", "students", "1", "Updated student record"],
            ]
        },
        "expense_categories": {
            "headers": ["category_name", "is_active"],
            "rows": [
                ["Rent", "1"],
                ["Utilities", "1"],
                ["Office Supplies", "1"],
            ]
        },
        "followups": {
            "headers": ["lead_id", "user_id", "method", "outcome", "note", "next_followup_date", "created_at"],
            "rows": [
                ["1", "", "call", "interested", "Discussed Tally course, interested in classes", "28-03-2026", "23-03-2026 02:30 PM"],
                ["1", "", "whatsapp", "callback_later", "Sent course details, waiting for response", "31-03-2026", "22-03-2026 10:15 AM"],
                ["2", "", "email", "not_interested", "Student declined, pursuing other options", "", "21-03-2026 04:45 PM"],
                ["3", "", "walk_in", "converted", "Student enrolled in Excel course", "", "20-03-2026 09:00 AM"],
            ]
        },
        "installment_plans": {
            "headers": ["invoice_id", "installment_no", "due_date", "amount_due", "amount_paid", "status", "remarks"],
            "rows": [
                ["1", "1", "21-04-2026", "2500", "2500", "paid", "First payment received"],
                ["1", "2", "21-05-2026", "2500", "0", "pending", ""],
            ]
        },
        "invoice_items": {
            "headers": ["invoice_id", "course_id", "description", "quantity", "unit_price", "discount", "line_total"],
            "rows": [
                ["1", "1", "Tally Course", "1", "5000", "0", "5000"],
                ["2", "2", "Excel Advanced", "1", "4000", "200", "3800"],
            ]
        },
        "users": {
            "headers": ["full_name", "username", "role", "phone", "branch_id", "can_view_all_branches", "is_active"],
            "rows": [
                ["Admin User", "admin", "admin", "9876543210", "1", "1", "1"],
                ["Staff User", "staff", "staff", "9123456789", "1", "0", "1"],
            ]
        },
    }
    
    if table_name not in samples:
        flash(f"No sample available for {table_name}", "warning")
        return redirect(url_for("reports.import_page"))
    
    sample = samples[table_name]
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    writer.writerow(sample["headers"])
    
    # Write sample rows
    for row in sample["rows"]:
        writer.writerow(row)
    
    csv_data = output.getvalue()
    output.close()
    
    response_file = io.BytesIO()
    response_file.write(csv_data.encode())
    response_file.seek(0)
    
    filename = f"{table_name}_sample.csv"
    
    return send_file(
        response_file,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


@reports_bp.route("/upload", methods=["POST"])
@login_required
@admin_required
def upload_csv():
    """Handle CSV file upload and import"""
    
    if "csv_file" not in request.files:
        flash("No file selected", "danger")
        return redirect(url_for("reports.import_page"))
    
    file = request.files["csv_file"]
    table_name = request.form.get("table_name", "").strip()
    
    if not file or not file.filename:
        flash("No file selected", "danger")
        return redirect(url_for("reports.import_page"))
    
    if not table_name:
        flash("No table selected", "danger")
        return redirect(url_for("reports.import_page"))
    
    # Allowed tables for import
    allowed_tables = ["activity_logs", "branches", "courses", "expense_categories", "expenses", "followups", "installment_plans", "invoice_items", "invoices", "leads", "receipts", "students", "users"]
    
    if table_name not in allowed_tables:
        flash(f"Invalid table: {table_name}", "danger")
        return redirect(url_for("reports.import_page"))
    
    try:
        # Read file content as bytes and decode to string
        file_content = file.read()
        if not file_content:
            flash("❌ CSV file is empty. Please upload a file with data.", "danger")
            return redirect(url_for("reports.import_page"))
        
        # Decode bytes to string
        try:
            text_content = file_content.decode('utf-8')
        except UnicodeDecodeError:
            flash("❌ File encoding error. Please save your CSV file as UTF-8 format.", "danger")
            return redirect(url_for("reports.import_page"))
        
        # Parse CSV from string content
        stream = io.StringIO(text_content)
        reader = csv.DictReader(stream)
        
        if not reader.fieldnames:
            flash("❌ CSV file has no headers. First row must contain column names.", "danger")
            return redirect(url_for("reports.import_page"))
        
        # Normalize fieldnames (strip whitespace and BOM from headers)
        if reader.fieldnames:
            reader.fieldnames = [name.replace('\ufeff', '').strip() if name else name for name in reader.fieldnames]
        
        conn = get_conn()
        cur = conn.cursor()
        
        rows_imported = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):  # Start from row 2 (row 1 is headers)
            # Normalize row keys (in case of whitespace or BOM in headers)
            normalized_row = {k.replace('\ufeff', '').strip() if k else k: v for k, v in row.items()} if row else {}
            row = normalized_row
            
            # Debug: Log raw row data if empty
            if not row or not any(row.values()):
                error_msg = f"Row {idx}: Empty/blank row detected - skipping"
                errors.append(error_msg)
                continue
            
            try:
                if table_name == "branches":
                    cur.execute("""
                        INSERT INTO branches (branch_name, branch_code, address, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        row.get("branch_name", "").strip(),
                        row.get("branch_code", "").strip(),
                        row.get("address", "").strip(),
                        int(row.get("is_active", 1)),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "courses":
                    cur.execute("""
                        INSERT INTO courses (course_name, duration, fee, course_type, is_active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("course_name", "").strip(),
                        row.get("duration", "").strip(),
                        float(row.get("fee", 0)) if row.get("fee") else 0,
                        row.get("course_type", "standard").strip(),
                        int(row.get("is_active", 1)),
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "leads":
                    # Validate lead_location field
                    lead_location = row.get("lead_location", "").strip() if row.get("lead_location") else None
                    if lead_location and lead_location.lower() not in ['rural', 'urban']:
                        error_msg = f"Row {idx + 1}: lead_location must be 'rural' or 'urban' (got '{lead_location}')"
                        errors.append(error_msg)
                        continue
                    
                    # Normalize location to lowercase
                    if lead_location:
                        lead_location = lead_location.lower()
                    
                    # Handle assigned_to_id (optional, defaults to current user)
                    assigned_to_id = None
                    if row.get("assigned_to_id"):
                        try:
                            assigned_to_id = int(row.get("assigned_to_id"))
                        except (ValueError, TypeError):
                            error_msg = f"Row {idx + 1}: assigned_to_id must be a valid user ID (got '{row.get('assigned_to_id')}')"
                            errors.append(error_msg)
                            continue
                    else:
                        assigned_to_id = session.get("user_id")
                    
                    cur.execute("""
                        INSERT INTO leads (
                            name, phone, whatsapp, gender, age, education_status, stream,
                            institute_name, career_goal, interested_courses, lead_source, decision_maker, 
                            lead_location, start_timeframe, lead_score, stage, status, lost_reason,
                            last_contact_date, next_followup_date, followup_count, notes, 
                            is_deleted, assigned_to_id, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("name", "").strip(),
                        row.get("phone", "").strip(),
                        row.get("whatsapp", "").strip() or None,
                        row.get("gender", "").strip() or None,
                        int(row.get("age", 0)) if row.get("age") else None,
                        row.get("education_status", "").strip() or None,
                        row.get("stream", "").strip() or None,
                        row.get("institute_name", "").strip() or None,
                        row.get("career_goal", "").strip() or None,
                        row.get("interested_courses", "").strip() or None,
                        row.get("lead_source", "").strip() or None,
                        row.get("decision_maker", "Self").strip() or "Self",
                        lead_location,
                        row.get("start_timeframe", "").strip() or None,
                        int(row.get("lead_score", 0)) if row.get("lead_score") else None,
                        row.get("stage", "New Lead").strip() or "New Lead",
                        row.get("status", "active").strip() or "active",
                        row.get("lost_reason", "").strip() or None,
                        parse_date(row.get("last_contact_date", "")) or None,
                        parse_date(row.get("next_followup_date", "")) or None,
                        int(row.get("followup_count", 0)) if row.get("followup_count") else 0,
                        row.get("notes", "").strip() or None,
                        0,
                        assigned_to_id,
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "students":
                    # Validate student_location field
                    student_location = row.get("student_location", "").strip() if row.get("student_location") else None
                    if student_location and student_location.lower() not in ['rural', 'urban']:
                        error_msg = f"Row {idx + 1}: student_location must be 'rural' or 'urban' (got '{student_location}')"
                        errors.append(error_msg)
                        continue
                    
                    # Normalize location to lowercase
                    if student_location:
                        student_location = student_location.lower()
                    
                    cur.execute("""
                        INSERT INTO students (
                            student_code, full_name, phone, email, gender, address,
                            education_level, qualification, student_location, employment_status,
                            status, branch_id, joined_date, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("student_code", "").strip(),
                        row.get("full_name", "").strip(),
                        row.get("phone", "").strip(),
                        row.get("email", "").strip() or None,
                        row.get("gender", "").strip() or None,
                        row.get("address", "").strip() or None,
                        row.get("education_level", "").strip() or None,
                        row.get("qualification", "").strip() or None,
                        student_location,
                        row.get("employment_status", "unemployed").strip() or "unemployed",
                        row.get("status", "active").strip() or "active",
                        int(row.get("branch_id", 1)) if row.get("branch_id") else 1,
                        parse_date(row.get("joined_date", "")) or datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "invoices":
                    try:
                        # Validate required fields for 13-column invoice import
                        invoice_number = row.get("invoice_number", "").strip()
                        student_id = row.get("student_id", "").strip()
                        invoice_date = row.get("invoice_date", "").strip()
                        subtotal = row.get("subtotal", "0").strip()
                        discount_type = row.get("discount_type", "none").strip().lower()
                        discount_value = row.get("discount_value", "0").strip()
                        discount_amount = row.get("discount_amount", "0").strip()
                        total_amount = row.get("total_amount", "0").strip()
                        installment_type = row.get("installment_type", "full").strip().lower()
                        notes = row.get("notes", "").strip()
                        status = row.get("status", "unpaid").strip().lower()
                        created_by = row.get("created_by", "").strip()
                        branch_id = row.get("branch_id", "").strip()
                        
                        # Validation
                        if not invoice_number:
                            errors.append(f"Row {idx}: invoice_number is required")
                            continue
                        if not student_id:
                            errors.append(f"Row {idx}: student_id is required")
                            continue
                        if not invoice_date:
                            errors.append(f"Row {idx}: invoice_date is required")
                            continue
                        
                        # Validate and parse date (supports DD-MM-YYYY or YYYY-MM-DD)
                        parsed_invoice_date = parse_date(invoice_date)
                        if not parsed_invoice_date:
                            errors.append(f"Row {idx}: invalid invoice_date format (use DD-MM-YYYY or YYYY-MM-DD)")
                            continue
                        invoice_date = parsed_invoice_date
                        
                        # Validate numbers
                        try:
                            subtotal = float(subtotal)
                            discount_value = float(discount_value)
                            discount_amount = float(discount_amount)
                            total_amount = float(total_amount)
                        except ValueError as e:
                            errors.append(f"Row {idx}: invalid number format - {str(e)}")
                            continue
                        
                        # Convert IDs
                        try:
                            student_id = int(student_id)
                            created_by = int(created_by)
                            branch_id = int(branch_id)
                        except ValueError:
                            errors.append(f"Row {idx}: student_id, created_by, and branch_id must be valid integers")
                            continue
                        
                        # Insert invoice with all 13 columns
                        cur.execute("""
                            INSERT INTO invoices (
                                invoice_no, student_id, invoice_date, subtotal, 
                                discount_type, discount_value, discount_amount, total_amount,
                                installment_type, notes, status, created_by, branch_id, created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            invoice_number, student_id, invoice_date, subtotal,
                            discount_type, discount_value, discount_amount, total_amount,
                            installment_type, notes, status, created_by, branch_id,
                            datetime.now().isoformat(timespec="seconds")
                        ))
                        rows_imported += 1
                    except Exception as e:
                        errors.append(f"Row {idx}: {str(e)}")
                        continue
                
                elif table_name == "receipts":
                    receipt_invoice_id = int(row.get("invoice_id", 0)) if row.get("invoice_id") else 0
                    receipt_amount = float(row.get("amount_received", 0)) if row.get("amount_received") else 0
                    
                    cur.execute("""
                        INSERT INTO receipts (
                            receipt_no, invoice_id, receipt_date, amount_received, payment_mode, notes, created_by, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("receipt_number", "").strip(),
                        receipt_invoice_id,
                        parse_date(row.get("receipt_date", "")) or None,
                        receipt_amount,
                        row.get("payment_mode", "cash").strip() or "cash",
                        row.get("notes", "").strip() or None,
                        session.get("user_id"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    
                    # Update invoice status based on total receipts
                    if receipt_invoice_id > 0:
                        cur.execute("""
                            SELECT total_amount FROM invoices WHERE id = ?
                        """, (receipt_invoice_id,))
                        invoice_row = cur.fetchone()
                        
                        if invoice_row:
                            invoice_total = float(invoice_row["total_amount"] or 0)
                            
                            cur.execute("""
                                SELECT IFNULL(SUM(amount_received), 0) AS total_received
                                FROM receipts
                                WHERE invoice_id = ?
                            """, (receipt_invoice_id,))
                            total_received = float(cur.fetchone()["total_received"] or 0)
                            
                            # Determine new status
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
                            """, (new_status, datetime.now().isoformat(timespec="seconds"), receipt_invoice_id))
                    
                    rows_imported += 1
                
                elif table_name == "installments":
                    cur.execute("""
                        INSERT INTO installment_plans (
                            invoice_id, installment_no, due_date, amount_due, amount_paid, status, remarks, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(row.get("invoice_id", 0)) if row.get("invoice_id") else 0,
                        int(row.get("installment_number", 0)) if row.get("installment_number") else 0,
                        row.get("due_date", "").strip() or None,
                        float(row.get("amount", 0)) if row.get("amount") else 0,
                        float(row.get("amount_paid", 0)) if row.get("amount_paid") else 0,
                        row.get("status", "pending").strip() or "pending",
                        row.get("remarks", "").strip() or None,
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "installment_plans":
                    cur.execute("""
                        INSERT INTO installment_plans (
                            invoice_id, installment_no, due_date, amount_due, amount_paid, status, remarks, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(row.get("invoice_id", 0)) if row.get("invoice_id") else 0,
                        int(row.get("installment_no", 0)) if row.get("installment_no") else 0,
                        parse_date(row.get("due_date", "")) or None,
                        float(row.get("amount_due", 0)) if row.get("amount_due") else 0,
                        float(row.get("amount_paid", 0)) if row.get("amount_paid") else 0,
                        row.get("status", "pending").strip() or "pending",
                        row.get("remarks", "").strip() or None,
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "activity_logs":
                    cur.execute("""
                        INSERT INTO activity_logs (
                            user_id, branch_id, action_type, module_name, record_id, description, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(row.get("user_id", session.get("user_id"))) if row.get("user_id") else session.get("user_id"),
                        int(row.get("branch_id", session.get("branch_id"))) if row.get("branch_id") else session.get("branch_id"),
                        row.get("action_type", "").strip() or "import",
                        row.get("module_name", "").strip() or "import_export",
                        int(row.get("record_id", 0)) if row.get("record_id") else None,
                        row.get("description", "").strip(),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "expense_categories":
                    cur.execute("""
                        INSERT INTO expense_categories (category_name, is_active, created_at)
                        VALUES (?, ?, ?)
                    """, (
                        row.get("category_name", "").strip(),
                        int(row.get("is_active", 1)),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "followups":
                    # Skip completely empty rows
                    if not any(row.values()):
                        continue
                    
                    # Validate lead_id exists
                    lead_id_str = row.get("lead_id", "").strip()
                    if not lead_id_str:
                        # Show available columns for debugging
                        available_cols = ", ".join([k for k in row.keys() if k])
                        non_empty_values = {k: v for k, v in row.items() if v and v.strip()}
                        error_msg = f"Row {idx}: lead_id is required (available: {available_cols} | data: {non_empty_values})"
                        errors.append(error_msg)
                        continue
                    
                    try:
                        lead_id = int(lead_id_str)
                    except ValueError:
                        error_msg = f"Row {idx + 1}: lead_id must be a valid number (got '{lead_id_str}')"
                        errors.append(error_msg)
                        continue
                    
                    # Check if lead exists
                    cur.execute("SELECT id FROM leads WHERE id = ? AND is_deleted = 0", (lead_id,))
                    if not cur.fetchone():
                        error_msg = f"Row {idx + 1}: Lead ID {lead_id} not found or is deleted"
                        errors.append(error_msg)
                        continue
                    
                    # Validate user_id if provided
                    user_id = session.get("user_id")
                    if row.get("user_id", "").strip():
                        try:
                            user_id = int(row.get("user_id"))
                            cur.execute("SELECT id FROM users WHERE id = ? AND is_active = 1", (user_id,))
                            if not cur.fetchone():
                                error_msg = f"Row {idx + 1}: User ID {user_id} not found or is inactive"
                                errors.append(error_msg)
                                continue
                        except ValueError:
                            error_msg = f"Row {idx + 1}: user_id must be a valid number (got '{row.get('user_id')}')"
                            errors.append(error_msg)
                            continue
                    
                    # Insert followup
                    # Handle created_at: parse from CSV if provided, otherwise use current time
                    created_at_str = row.get("created_at", "").strip()
                    if created_at_str:
                        # Try to parse datetime from CSV (multiple formats supported)
                        try:
                            # Try format with time: DD-MM-YYYY HH:MM AM/PM
                            created_at_parsed = datetime.strptime(created_at_str, "%d-%m-%Y %I:%M %p")
                            created_at_value = created_at_parsed.isoformat()
                        except ValueError:
                            try:
                                # Try format with time: DD-MM-YYYY HH:MM
                                created_at_parsed = datetime.strptime(created_at_str, "%d-%m-%Y %H:%M")
                                created_at_value = created_at_parsed.isoformat()
                            except ValueError:
                                try:
                                    # Try abbreviated month format: DD-Mon-YYYY HH:MM (e.g., 03-Mar-2026 15:09)
                                    created_at_parsed = datetime.strptime(created_at_str, "%d-%b-%Y %H:%M")
                                    created_at_value = created_at_parsed.isoformat()
                                except ValueError:
                                    try:
                                        # Try abbreviated month format with AM/PM: DD-Mon-YYYY HH:MM AM/PM (e.g., 03-Mar-2026 3:09 PM)
                                        created_at_parsed = datetime.strptime(created_at_str, "%d-%b-%Y %I:%M %p")
                                        created_at_value = created_at_parsed.isoformat()
                                    except ValueError:
                                        # Try date only: DD-MM-YYYY
                                        try:
                                            created_at_parsed = datetime.strptime(created_at_str, "%d-%m-%Y")
                                            created_at_value = created_at_parsed.isoformat()
                                        except ValueError:
                                            # Invalid format, use current time
                                            errors.append(f"Row {rows_imported + 1}: Invalid created_at format '{created_at_str}', using current timestamp")
                                            created_at_value = datetime.now().isoformat(timespec="seconds")
                    else:
                        # Empty created_at, use current time
                        created_at_value = datetime.now().isoformat(timespec="seconds")
                    
                    cur.execute("""
                        INSERT INTO followups (
                            lead_id, user_id, method, outcome, note, next_followup_date, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        lead_id,
                        user_id,
                        row.get("method", "").strip() or None,
                        row.get("outcome", "").strip() or None,
                        row.get("note", "").strip() or None,
                        parse_date(row.get("next_followup_date", "")) if row.get("next_followup_date", "").strip() else None,
                        created_at_value
                    ))
                    rows_imported += 1
                
                elif table_name == "invoice_items":
                    cur.execute("""
                        INSERT INTO invoice_items (
                            invoice_id, course_id, description, quantity, unit_price, discount, line_total, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(row.get("invoice_id", 0)) if row.get("invoice_id") else 0,
                        int(row.get("course_id")) if row.get("course_id") else None,
                        row.get("description", "").strip(),
                        int(row.get("quantity", 1)) if row.get("quantity") else 1,
                        float(row.get("unit_price", 0)) if row.get("unit_price") else 0,
                        float(row.get("discount", 0)) if row.get("discount") else 0,
                        float(row.get("line_total", 0)) if row.get("line_total") else 0,
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "users":
                    cur.execute("""
                        INSERT INTO users (
                            full_name, username, password_hash, role, phone, branch_id, 
                            can_view_all_branches, is_active, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("full_name", "").strip(),
                        row.get("username", "").strip(),
                        generate_password_hash(row.get("username", "")),  # Default password = username
                        row.get("role", "staff").strip() or "staff",
                        row.get("phone", "").strip() or None,
                        int(row.get("branch_id")) if row.get("branch_id") else 1,
                        int(row.get("can_view_all_branches", 0)),
                        int(row.get("is_active", 1)),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "expenses":
                    cur.execute("""
                        INSERT INTO expenses (
                            expense_type, category, amount, description, expense_date, branch_id, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("expense_type", "").strip() or "other",
                        row.get("category", "").strip() or None,
                        float(row.get("amount", 0)) if row.get("amount") else 0,
                        row.get("description", "").strip() or None,
                        parse_date(row.get("expense_date", "")) or datetime.now().isoformat(timespec="seconds"),
                        int(row.get("branch_id", 1)) if row.get("branch_id") else 1,
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
            
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
        
        conn.commit()
        
        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="import",
            module_name="reports",
            record_id=None,
            description=f"Imported {rows_imported} rows to {table_name}"
        )
        
        conn.close()
        
        if errors:
            error_message = f"✓ Imported {rows_imported} rows, but {len(errors)} row(s) failed:\n"
            for err in errors[:3]:
                error_message += f"\n  • {err}"
            if len(errors) > 3:
                error_message += f"\n  ... and {len(errors) - 3} more errors"
            flash(error_message, "warning")
        else:
            flash(f"✅ Successfully imported {rows_imported} rows into {table_name}!", "success")
        
        return redirect(url_for("reports.import_page"))
    
    except Exception as e:
        error_detail = str(e)
        
        # Provide helpful error messages
        if "no column named" in error_detail.lower():
            flash(f"❌ Column mismatch error.\n\nThe CSV file has a column that doesn't exist in the {table_name} table.\n\nError: {error_detail}\n\n📋 Tip: Download the sample CSV to see correct column names.", "danger")
        elif "constraint" in error_detail.lower() or "foreign key" in error_detail.lower():
            flash(f"❌ Data relationship error.\n\nA record references data that doesn't exist (e.g., student_id without student).\n\nError: {error_detail}", "danger")
        elif "not null" in error_detail.lower():
            flash(f"❌ Missing required data.\n\nA required field is empty or missing.\n\nError: {error_detail}\n\n📋 Tip: Check that all required columns have values.", "danger")
        else:
            flash(f"❌ Error importing CSV:\n\n{error_detail}\n\n📋 Try downloading a sample CSV and comparing your format.", "danger")
        
        return redirect(url_for("reports.import_page"))
