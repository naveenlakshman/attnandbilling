import os
import sys
import sqlite3

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_PATH

def main():
    commit = "--commit" in sys.argv
    
    print("=" * 60)
    print("  Revoke 'Advance Excel' Access from 'DFA' Students")
    print("=" * 60)
    print(f"Database Path: {DB_PATH}")
    print(f"Mode: {'COMMIT (Applying Changes)' if commit else 'DRY RUN (No Changes)'}")
    print("-" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file does not exist at {DB_PATH}")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 1. Dynamically find DFA Course ID
    course_name_pattern = 'DFA - DIPLOMA IN FINANCIAL ACCOUNTING'
    cur.execute("SELECT id, course_name FROM courses WHERE course_name = ?", (course_name_pattern,))
    dfa_course = cur.fetchone()
    if not dfa_course:
        # Fallback to search
        cur.execute("SELECT id, course_name FROM courses WHERE course_name LIKE '%DFA%'")
        dfa_course = cur.fetchone()
        
    if not dfa_course:
        print("Error: Could not find DFA course in database.")
        conn.close()
        sys.exit(1)
        
    dfa_course_id = dfa_course['id']
    print(f"Found DFA Course: ID={dfa_course_id}, Name='{dfa_course['course_name']}'")
    
    # 2. Dynamically find Advance Excel Program ID
    program_name_pattern = 'Advance Excel'
    cur.execute("SELECT id, program_name FROM lms_programs WHERE program_name = ?", (program_name_pattern,))
    excel_program = cur.fetchone()
    if not excel_program:
        cur.execute("SELECT id, program_name FROM lms_programs WHERE program_name LIKE '%Excel%'")
        excel_program = cur.fetchone()
        
    if not excel_program:
        print("Error: Could not find Advance Excel program in database.")
        conn.close()
        sys.exit(1)
        
    excel_program_id = excel_program['id']
    print(f"Found Excel Program: ID={excel_program_id}, Name='{excel_program['program_name']}'")
    
    # 3. Find all students who purchased DFA
    cur.execute("""
        SELECT DISTINCT s.id, s.student_code, s.full_name
        FROM students s
        JOIN invoices inv ON inv.student_id = s.id
        JOIN invoice_items ii ON ii.invoice_id = inv.id
        WHERE ii.course_id = ?
        ORDER BY s.full_name ASC
    """, (dfa_course_id,))
    dfa_students = cur.fetchall()
    
    dfa_student_ids = [s['id'] for s in dfa_students]
    print(f"Total DFA Students found: {len(dfa_student_ids)}")
    
    if not dfa_student_ids:
        print("No DFA students found. Nothing to do.")
        conn.close()
        sys.exit(0)
        
    # 4. Find which of these students have active/existing Advance Excel access
    placeholders = ",".join("?" for _ in dfa_student_ids)
    query = f"""
        SELECT spa.id as access_id, spa.student_id, s.student_code, s.full_name, spa.access_start_date, spa.is_active
        FROM lms_student_program_access spa
        JOIN students s ON s.id = spa.student_id
        WHERE spa.program_id = ? AND spa.student_id IN ({placeholders})
    """
    params = [excel_program_id] + dfa_student_ids
    affected_access = cur.execute(query, params).fetchall()
    
    print(f"DFA Students with 'Advance Excel' access entries: {len(affected_access)}")
    print("-" * 60)
    
    if not affected_access:
        print("No DFA students have 'Advance Excel' access records in lms_student_program_access.")
        conn.close()
        sys.exit(0)
        
    for idx, row in enumerate(affected_access, 1):
        status_str = "Active" if row['is_active'] == 1 else "Suspended"
        print(f"{idx}. {row['full_name']} ({row['student_code']}) - Access ID: {row['access_id']}, Start Date: {row['access_start_date']}, Status: {status_str}")
        
    print("-" * 60)
    
    if commit:
        access_ids_to_delete = [row['access_id'] for row in affected_access]
        del_placeholders = ",".join("?" for _ in access_ids_to_delete)
        cur.execute(f"DELETE FROM lms_student_program_access WHERE id IN ({del_placeholders})", access_ids_to_delete)
        conn.commit()
        print(f"SUCCESS: Permanently deleted {len(access_ids_to_delete)} access record(s) from lms_student_program_access.")
    else:
        print("Dry Run complete. No records were modified.")
        print("To apply these changes, run the script with the --commit flag:")
        print("python scripts/remove_excel_access_dfa.py --commit")
        
    conn.close()

if __name__ == '__main__':
    main()
