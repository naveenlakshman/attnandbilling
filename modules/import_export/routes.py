from flask import Blueprint, render_template, session, flash, send_file, request, redirect, url_for
from functools import wraps
from io import BytesIO
from datetime import datetime
import sqlite3
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from db import get_conn
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
