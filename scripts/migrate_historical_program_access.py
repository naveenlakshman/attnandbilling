import os
import sys
import sqlite3
from datetime import datetime

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_PATH

def main():
    commit = "--commit" in sys.argv
    target_student_code = None
    
    for i, arg in enumerate(sys.argv):
        if arg == "--student" and i + 1 < len(sys.argv):
            target_student_code = sys.argv[i + 1]
            
    print("=" * 60)
    print("  Migrate Historical Invoice LMS Program Access")
    print("=" * 60)
    print(f"Database Path: {DB_PATH}")
    print(f"Mode: {'COMMIT (Applying Changes)' if commit else 'DRY RUN (No Changes)'}")
    if target_student_code:
        print(f"Filter: Only for student code '{target_student_code}'")
    else:
        print("Filter: All active/existing student invoices")
    print("-" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file does not exist at {DB_PATH}")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Fetch student ID if target specified
    target_student_id = None
    if target_student_code:
        cur.execute("SELECT id, full_name FROM students WHERE student_code = ?", (target_student_code,))
        student = cur.fetchone()
        if not student:
            print(f"Error: Student with code '{target_student_code}' not found.")
            conn.close()
            sys.exit(1)
        target_student_id = student['id']
        print(f"Targeting Student: {student['full_name']} (ID: {target_student_id})")
        print("-" * 60)
        
    # Query invoice items for active students
    query = """
        SELECT DISTINCT inv.student_id, s.full_name, s.student_code, ii.course_id, c.course_name
        FROM invoice_items ii
        JOIN invoices inv ON inv.id = ii.invoice_id
        JOIN students s ON s.id = inv.student_id
        JOIN courses c ON c.id = ii.course_id
        WHERE s.status = 'active'
    """
    params = []
    if target_student_id:
        query += " AND inv.student_id = ?"
        params.append(target_student_id)
        
    invoice_purchases = cur.execute(query, params).fetchall()
    
    print(f"Found {len(invoice_purchases)} purchased course items from invoices.")
    print("-" * 60)
    
    now_date = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat(timespec="seconds")
    
    provisions_proposed = 0
    provisions_executed = 0
    
    for row in invoice_purchases:
        student_id = row['student_id']
        student_code = row['student_code']
        student_name = row['full_name']
        course_id = row['course_id']
        course_name = row['course_name']
        
        # Find mapped active programs
        programs = cur.execute("""
            SELECT DISTINCT lp.id, lp.program_name
            FROM lms_programs lp
            WHERE lp.is_active = 1 AND lp.is_deleted = 0
              AND (
                  lp.course_id = ?
                  OR EXISTS (
                      SELECT 1 FROM lms_course_program_map cpm 
                      WHERE cpm.program_id = lp.id AND cpm.course_id = ?
                  )
              )
        """, (course_id, course_id)).fetchall()
        
        for prog in programs:
            program_id = prog['id']
            program_name = prog['program_name']
            
            # Check if access already exists
            existing = cur.execute("""
                SELECT id, is_active FROM lms_student_program_access
                WHERE student_id = ? AND program_id = ?
            """, (student_id, program_id)).fetchone()
            
            if not existing:
                provisions_proposed += 1
                print(f"  [CREATE] Grant {student_name} ({student_code}) access to program '{program_name}' (ID: {program_id}) based on course '{course_name}'")
                if commit:
                    cur.execute("""
                        INSERT INTO lms_student_program_access (
                            student_id, program_id, access_start_date, access_status, is_active, created_at, updated_at
                        ) VALUES (?, ?, ?, 'active', 1, ?, ?)
                    """, (student_id, program_id, now_date, now_iso, now_iso))
                    provisions_executed += 1
            elif existing['is_active'] == 0:
                # If they had suspended access but have an invoice, we don't automatically override manual suspension.
                pass
                
    print("-" * 60)
    if commit:
        conn.commit()
        print(f"SUCCESS: Committed {provisions_executed} new program access records to the database!")
    else:
        print(f"Dry Run complete. {provisions_proposed} program access records would be created.")
        print("To apply these changes, run with the --commit flag:")
        if target_student_code:
            print(f"python scripts/migrate_historical_program_access.py --student {target_student_code} --commit")
        else:
            print("python scripts/migrate_historical_program_access.py --commit")
            
    conn.close()

if __name__ == '__main__':
    main()
