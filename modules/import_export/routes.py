from flask import Blueprint, render_template, session, flash, send_file, request, redirect, url_for
from functools import wraps
from io import BytesIO, StringIO
from datetime import datetime
import sqlite3
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from db import get_conn, log_activity
from config import DB_PATH
from modules.core.utils import login_required, admin_required

import_export_bp = Blueprint("import_export", __name__)


def get_all_tables_data():
    """
    Retrieves all tables and their data from the database.
    Returns a dictionary where keys are table names and values are lists of dictionaries.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all table names from sqlite_master
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    tables = cursor.fetchall()
    
    tables_data = {}
    
    for table in tables:
        table_name = table[0]
        
        # Get all data from the table
        cursor.execute(f"SELECT * FROM [{table_name}]")
        rows = cursor.fetchall()
        
        # Convert rows to list of dictionaries
        data = []
        if rows:
            columns = [desc[0] for desc in cursor.description]
            for row in rows:
                row_dict = dict(row)
                data.append(row_dict)
        else:
            # If table is empty, still get column names
            cursor.execute(f"PRAGMA table_info([{table_name}])")
            columns = [col[1] for col in cursor.fetchall()]
        
        tables_data[table_name] = {
            'columns': [desc[0] for desc in cursor.description] if rows else columns,
            'data': data
        }
    
    conn.close()
    return tables_data


def create_excel_workbook(tables_data):
    """
    Creates an Excel workbook with multiple sheets, one for each table.
    Each sheet contains the table data with headers.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)  # Remove default sheet
    
    # Define header style
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    for table_name, table_info in tables_data.items():
        # Create a new sheet for each table
        sheet = workbook.create_sheet(title=table_name[:31])  # Excel sheet name limit is 31 chars
        
        # Add headers
        columns = table_info['columns']
        for col_idx, column_name in enumerate(columns, 1):
            cell = sheet.cell(row=1, column=col_idx)
            cell.value = column_name
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
        
        # Add data rows
        for row_idx, row_data in enumerate(table_info['data'], 2):
            for col_idx, column_name in enumerate(columns, 1):
                cell = sheet.cell(row=row_idx, column=col_idx)
                cell.value = row_data.get(column_name)
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=False)
        
        # Adjust column widths
        for col_idx, column_name in enumerate(columns, 1):
            max_length = len(str(column_name))
            for row_data in table_info['data']:
                cell_value = str(row_data.get(column_name, ''))
                if len(cell_value) > max_length:
                    max_length = len(cell_value)
            
            adjusted_width = min(max_length + 2, 50)  # Cap at 50 for readability
            sheet.column_dimensions[sheet.cell(row=1, column=col_idx).column_letter].width = adjusted_width
    
    return workbook


@import_export_bp.route("/")
@login_required
@admin_required
def import_export_dashboard():
    """Import/Export dashboard page"""
    return render_template("import_export/dashboard.html")


@import_export_bp.route("/export/all-tables", methods=["GET"])
@login_required
@admin_required
def export_all_tables():
    """
    Export all database tables to a single Excel workbook.
    Each table is in a separate sheet with the table name as sheet name.
    """
    try:
        # Get all tables and their data
        tables_data = get_all_tables_data()
        
        if not tables_data:
            flash("No tables found in the database.", "warning")
            return redirect(url_for("import_export.import_export_dashboard"))
        
        # Create Excel workbook
        workbook = create_excel_workbook(tables_data)
        
        # Save to bytes
        excel_file = BytesIO()
        workbook.save(excel_file)
        excel_file.seek(0)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Database_Export_{timestamp}.xlsx"
        
        # Send file to user
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        flash(f"Error exporting data: {str(e)}", "danger")
        return redirect(url_for("import_export.import_export_dashboard"))


@import_export_bp.route("/invoices/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_invoices():
    """
    Import invoices from CSV file.
    Expected columns: invoice_number, student_id, invoice_date, subtotal, discount_type, 
                     discount_value, discount_amount, total_amount, installment_type, 
                     notes, status, created_by, branch_id
    """
    if request.method == "POST":
        try:
            # Check if file is present
            if 'csv_file' not in request.files:
                flash("No file selected", "danger")
                return redirect(url_for("import_export.import_invoices"))
            
            file = request.files['csv_file']
            
            if file.filename == '':
                flash("No file selected", "danger")
                return redirect(url_for("import_export.import_invoices"))
            
            if not file.filename.endswith('.csv'):
                flash("Please upload a CSV file", "danger")
                return redirect(url_for("import_export.import_invoices"))
            
            # Read and parse CSV
            stream = StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_data = csv.DictReader(stream)
            
            if not csv_data:
                flash("CSV file is empty", "danger")
                return redirect(url_for("import_export.import_invoices"))
            
            conn = get_conn()
            cur = conn.cursor()
            
            imported_count = 0
            errors = []
            row_number = 1
            
            # Validate required columns
            required_columns = {
                'invoice_number', 'student_id', 'invoice_date', 'subtotal',
                'discount_type', 'discount_value', 'discount_amount', 'total_amount',
                'installment_type', 'status', 'created_by', 'branch_id'
            }
            
            if not csv_data.fieldnames:
                flash("CSV file has no headers", "danger")
                conn.close()
                return redirect(url_for("import_export.import_invoices"))
            
            csv_columns = set(csv_data.fieldnames)
            missing_columns = required_columns - csv_columns
            
            if missing_columns:
                flash(f"Missing required columns: {', '.join(missing_columns)}", "danger")
                conn.close()
                return redirect(url_for("import_export.import_invoices"))
            
            # Process each row
            for row in csv_data:
                row_number += 1
                
                try:
                    # Validate and clean data
                    invoice_number = row.get('invoice_number', '').strip()
                    student_id = row.get('student_id', '').strip()
                    invoice_date = row.get('invoice_date', '').strip()
                    subtotal = row.get('subtotal', '0').strip()
                    discount_type = row.get('discount_type', 'none').strip().lower()
                    discount_value = row.get('discount_value', '0').strip()
                    discount_amount = row.get('discount_amount', '0').strip()
                    total_amount = row.get('total_amount', '0').strip()
                    installment_type = row.get('installment_type', 'full').strip().lower()
                    notes = row.get('notes', '').strip()
                    status = row.get('status', 'unpaid').strip().lower()
                    created_by = row.get('created_by', '').strip()
                    branch_id = row.get('branch_id', '').strip()
                    
                    # Validation errors
                    if not invoice_number:
                        errors.append(f"Row {row_number}: invoice_number is required")
                        continue
                    
                    if not student_id:
                        errors.append(f"Row {row_number}: student_id is required")
                        continue
                    
                    if not invoice_date:
                        errors.append(f"Row {row_number}: invoice_date is required")
                        continue
                    
                    # Validate invoice_date format
                    try:
                        datetime.strptime(invoice_date, "%Y-%m-%d")
                    except ValueError:
                        errors.append(f"Row {row_number}: invalid invoice_date format (use YYYY-MM-DD)")
                        continue
                    
                    # Validate student exists
                    cur.execute("SELECT id FROM students WHERE id = ?", (student_id,))
                    if not cur.fetchone():
                        errors.append(f"Row {row_number}: student_id {student_id} does not exist")
                        continue
                    
                    # Validate created_by (user) exists
                    if not created_by:
                        errors.append(f"Row {row_number}: created_by (user ID) is required")
                        continue
                    
                    cur.execute("SELECT id FROM users WHERE id = ?", (created_by,))
                    if not cur.fetchone():
                        errors.append(f"Row {row_number}: user {created_by} does not exist")
                        continue
                    
                    # Validate branch exists
                    if branch_id:
                        cur.execute("SELECT id FROM branches WHERE id = ?", (branch_id,))
                        if not cur.fetchone():
                            errors.append(f"Row {row_number}: branch_id {branch_id} does not exist")
                            continue
                    
                    # Validate numeric fields
                    try:
                        subtotal = float(subtotal)
                        discount_value = float(discount_value)
                        discount_amount = float(discount_amount)
                        total_amount = float(total_amount)
                    except ValueError:
                        errors.append(f"Row {row_number}: invalid numeric values for amounts")
                        continue
                    
                    # Validate discount_type
                    if discount_type not in ('none', 'fixed', 'percentage'):
                        errors.append(f"Row {row_number}: discount_type must be 'none', 'fixed', or 'percentage'")
                        continue
                    
                    # Validate installment_type
                    if installment_type not in ('full', 'custom'):
                        errors.append(f"Row {row_number}: installment_type must be 'full' or 'custom'")
                        continue
                    
                    # Validate status
                    if status not in ('unpaid', 'partially_paid', 'paid', 'cancelled'):
                        errors.append(f"Row {row_number}: status must be 'unpaid', 'partially_paid', 'paid', or 'cancelled'")
                        continue
                    
                    # Check if invoice_number already exists
                    cur.execute("SELECT id FROM invoices WHERE invoice_no = ?", (invoice_number,))
                    if cur.fetchone():
                        errors.append(f"Row {row_number}: invoice_number {invoice_number} already exists")
                        continue
                    
                    # Insert invoice
                    now = datetime.now().isoformat()
                    cur.execute("""
                        INSERT INTO invoices 
                        (invoice_no, student_id, invoice_date, subtotal, discount_type, 
                         discount_value, discount_amount, total_amount, installment_type, 
                         notes, status, created_by, branch_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        invoice_number, student_id, invoice_date, subtotal, discount_type,
                        discount_value, discount_amount, total_amount, installment_type,
                        notes if notes else None, status, created_by, branch_id if branch_id else None, now
                    ))
                    
                    # Log the import activity
                    log_activity(
                        session['user_id'],
                        'INVOICE_IMPORTED',
                        f'Invoice {invoice_number} imported for student {student_id}'
                    )
                    
                    imported_count += 1
                    
                except Exception as e:
                    errors.append(f"Row {row_number}: {str(e)}")
            
            conn.commit()
            conn.close()
            
            # Provide feedback
            flashmsg = f"Successfully imported {imported_count} invoice(s)"
            if errors:
                if imported_count > 0:
                    flash(flashmsg + f". {len(errors)} error(s) occurred: " + "; ".join(errors[:5]), "warning")
                else:
                    flash("Failed to import invoices: " + "; ".join(errors[:5]), "danger")
            else:
                flash(flashmsg, "success")
            
            return redirect(url_for("import_export.import_invoices"))
        
        except Exception as e:
            flash(f"Error importing invoices: {str(e)}", "danger")
            return redirect(url_for("import_export.import_invoices"))
    
    # GET request - show import form
    return render_template("import_export/import_invoices.html")


@import_export_bp.route("/invoices/template", methods=["GET"])
@login_required
@admin_required
def download_invoice_template():
    """
    Download a CSV template for invoice import with all required columns.
    
    All 13 columns are required:
    1. invoice_number - Format: GIT/B/1, GIT/B/2, etc.
    2. student_id - Existing student ID
    3. invoice_date - YYYY-MM-DD format
    4. subtotal - Amount before discounts
    5. discount_type - none, fixed, or percentage
    6. discount_value - Discount amount or percentage
    7. discount_amount - Calculated discount amount
    8. total_amount - Final total after discounts
    9. installment_type - full or custom
    10. notes - Optional notes/remarks
    11. status - unpaid, partially_paid, paid, or cancelled
    12. created_by - User ID who created invoice
    13. branch_id - Branch ID
    """
    try:
        # Create CSV in memory
        output_string = StringIO()
        
        # CSV headers - All 13 columns REQUIRED
        headers = [
            'invoice_number',
            'student_id',
            'invoice_date',
            'subtotal',
            'discount_type',
            'discount_value',
            'discount_amount',
            'total_amount',
            'installment_type',
            'notes',
            'status',
            'created_by',
            'branch_id'
        ]
        
        writer = csv.writer(output_string)
        # Write headers
        writer.writerow(headers)
        
        # Write example rows with comments
        writer.writerow(['# Example Row 1 - No discount'])
        writer.writerow([
            'GIT/B/1', '1', '2026-04-21', '5000', 'none',
            '0', '0', '5000', 'full', 'Course Fee', 'pending', '1', '1'
        ])
        
        writer.writerow(['# Example Row 2 - Percentage discount (5%)'])
        writer.writerow([
            'GIT/B/2', '2', '2026-04-15', '4000', 'percentage',
            '5', '200', '3800', 'full', '', 'paid', '1', '1'
        ])
        
        writer.writerow(['# Example Row 3 - Fixed discount (500)'])
        writer.writerow([
            'GIT/B/3', '3', '2026-04-10', '3500', 'fixed',
            '500', '500', '3000', 'custom', 'Monthly installments', 'partially_paid', '1', '1'
        ])
        
        # Get CSV content
        output_string.seek(0)
        csv_content = output_string.getvalue()
        
        # Create BytesIO object for sending
        output = BytesIO()
        output.write(csv_content.encode('utf-8-sig'))  # UTF-8 with BOM for Excel compatibility
        output.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"Invoice_Import_Template_{timestamp}.csv"
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        flash(f"Error generating template: {str(e)}", "danger")
        return redirect(url_for("import_export.import_invoices"))
