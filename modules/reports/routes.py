import io
import csv
from flask import Blueprint, render_template, send_file, flash, redirect, url_for, session, request
from db import get_conn, log_activity
from modules.core.utils import login_required, admin_required
from werkzeug.security import generate_password_hash
from datetime import datetime

reports_bp = Blueprint("reports", __name__)

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
            writer.writerow([row[col] if row[col] is not None else "" for col in columns])
        
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
            "headers": ["name", "phone", "whatsapp", "gender", "age", "education_status", "stream", "career_goal", "lead_source", "decision_maker", "lead_location", "start_timeframe", "stage", "notes"],
            "rows": [
                ["John Doe", "9876543210", "9876543210", "Male", "25", "Graduate", "Commerce", "Job", "Walk-in", "Self", "Urban", "Immediately", "New Lead", "Interested in Tally"],
                ["Jane Smith", "9123456789", "9123456789", "Female", "22", "School", "Science", "Skill Development", "Referral", "Parents", "Rural", "Within 1 Month", "New Lead", ""],
            ]
        },
        "students": {
            "headers": ["student_code", "full_name", "phone", "email", "gender", "address", "education_level", "qualification", "student_location", "employment_status", "status", "branch_id", "joined_date"],
            "rows": [
                ["1515001", "Student Name", "9876543210", "student@example.com", "Male", "Address", "Undergraduate", "BE", "Urban", "student", "active", "1", "2026-03-21"],
                ["1515002", "Another Student", "9123456789", "student2@example.com", "Female", "Address", "School", "12th", "Rural", "unemployed", "active", "1", "2026-03-21"],
            ]
        },
        "invoices": {
            "headers": ["invoice_number", "student_id", "invoice_date", "subtotal", "discount_type", "discount_value", "discount_amount", "total_amount", "installment_type", "notes", "status", "created_by", "branch_id"],
            "rows": [
                ["GIT/B/001", "1", "2026-03-21", "5000", "percentage", "10", "500", "4500", "full", "Course Fee", "unpaid", "1", "1"],
                ["GIT/B/002", "2", "2026-03-20", "4000", "fixed", "300", "300", "3700", "installment", "Excel training", "unpaid", "1", "1"],
            ]
        },
        "receipts": {
            "headers": ["receipt_number", "student_id", "invoice_id", "amount", "payment_date", "payment_method", "notes"],
            "rows": [
                ["RCP001", "1", "1", "5000", "2026-03-21", "cash", "Full payment"],
                ["RCP002", "2", "2", "2000", "2026-03-20", "bank_transfer", "First installment"],
            ]
        },
        "installments": {
            "headers": ["invoice_id", "installment_number", "due_date", "amount", "status"],
            "rows": [
                ["1", "1", "2026-04-21", "2500", "pending"],
                ["1", "2", "2026-05-21", "2500", "pending"],
            ]
        },
        "expenses": {
            "headers": ["expense_type", "category", "amount", "description", "expense_date", "branch_id"],
            "rows": [
                ["rent", "office", "20000", "Monthly office rent", "2026-03-21", "1"],
                ["utilities", "office", "5000", "Electricity bill", "2026-03-21", "1"],
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
            "headers": ["lead_id", "user_id", "method", "outcome", "note", "next_followup_date"],
            "rows": [
                ["1", "1", "call", "interested", "Discussed course options", "2026-03-28"],
                ["2", "1", "email", "not_interested", "Student declined", ""],
            ]
        },
        "installment_plans": {
            "headers": ["invoice_id", "installment_no", "due_date", "amount_due", "amount_paid", "status", "remarks"],
            "rows": [
                ["1", "1", "2026-04-21", "2500", "2500", "paid", "First payment received"],
                ["1", "2", "2026-05-21", "2500", "0", "pending", ""],
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
        
        conn = get_conn()
        cur = conn.cursor()
        
        rows_imported = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):  # Start from row 2 (row 1 is headers)
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
                    cur.execute("""
                        INSERT INTO leads (
                            name, phone, whatsapp, gender, age, education_status, stream,
                            career_goal, lead_source, decision_maker, lead_location, start_timeframe,
                            stage, notes, status, is_deleted, assigned_to_id, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("name", "").strip(),
                        row.get("phone", "").strip(),
                        row.get("whatsapp", "").strip() or None,
                        row.get("gender", "").strip() or None,
                        int(row.get("age", 0)) if row.get("age") else None,
                        row.get("education_status", "").strip() or None,
                        row.get("stream", "").strip() or None,
                        row.get("career_goal", "").strip() or None,
                        row.get("lead_source", "").strip() or None,
                        row.get("decision_maker", "Self").strip() or "Self",
                        row.get("lead_location", "").strip() or None,
                        row.get("start_timeframe", "").strip() or None,
                        row.get("stage", "New Lead").strip() or "New Lead",
                        row.get("notes", "").strip() or None,
                        "active",
                        0,
                        session.get("user_id"),
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
                    rows_imported += 1
                
                elif table_name == "students":
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
                        row.get("student_location", "").strip() or None,
                        row.get("employment_status", "unemployed").strip() or "unemployed",
                        row.get("status", "active").strip() or "active",
                        int(row.get("branch_id", 1)) if row.get("branch_id") else 1,
                        row.get("joined_date", "").strip() or datetime.now().isoformat(timespec="seconds"),
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
                        
                        # Validate date format
                        try:
                            datetime.strptime(invoice_date, "%Y-%m-%d")
                        except ValueError:
                            errors.append(f"Row {idx}: invalid invoice_date format (use YYYY-MM-DD)")
                            continue
                        
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
                                invoice_number, student_id, invoice_date, subtotal, 
                                discount_type, discount_value, discount_amount, total_amount,
                                installment_type, notes, status, created_by, branch_id, created_at, updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            invoice_number, student_id, invoice_date, subtotal,
                            discount_type, discount_value, discount_amount, total_amount,
                            installment_type, notes, status, created_by, branch_id,
                            datetime.now().isoformat(timespec="seconds"),
                            datetime.now().isoformat(timespec="seconds")
                        ))
                        rows_imported += 1
                    except Exception as e:
                        errors.append(f"Row {idx}: {str(e)}")
                        continue
                
                elif table_name == "receipts":
                    cur.execute("""
                        INSERT INTO receipts (
                            receipt_number, student_id, invoice_id, amount, payment_date, payment_method, notes, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get("receipt_number", "").strip(),
                        int(row.get("student_id", 0)) if row.get("student_id") else 0,
                        int(row.get("invoice_id", 0)) if row.get("invoice_id") else 0,
                        float(row.get("amount", 0)) if row.get("amount") else 0,
                        row.get("payment_date", "").strip() or None,
                        row.get("payment_method", "").strip() or None,
                        row.get("notes", "").strip() or None,
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds")
                    ))
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
                        row.get("due_date", "").strip() or None,
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
                    cur.execute("""
                        INSERT INTO followups (
                            lead_id, user_id, method, outcome, note, next_followup_date, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(row.get("lead_id", 0)) if row.get("lead_id") else 0,
                        int(row.get("user_id")) if row.get("user_id") else session.get("user_id"),
                        row.get("method", "").strip() or None,
                        row.get("outcome", "").strip() or None,
                        row.get("note", "").strip() or None,
                        row.get("next_followup_date", "").strip() or None,
                        datetime.now().isoformat(timespec="seconds")
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
                        row.get("expense_date", "").strip() or datetime.now().isoformat(timespec="seconds"),
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
