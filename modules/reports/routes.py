import io
import csv
from flask import Blueprint, render_template, send_file, flash, redirect, url_for, session
from db import get_conn
from modules.core.utils import login_required, admin_required
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
        "branches": "branches",
        "users": "users",
        "leads": "leads",
        "students": "students",
        "courses": "courses",
        "invoices": "invoices",
        "receipts": "receipts",
        "expenses": "expenses",
        "activity_logs": "activity_logs"
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
