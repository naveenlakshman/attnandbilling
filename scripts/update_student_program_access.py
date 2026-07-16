import os
import sys
import sqlite3
from datetime import datetime

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_PATH

def main():
    commit = "--commit" in sys.argv
    
    # Parse arguments
    student_code = "1516702"
    target_program_id = 13
    
    for i, arg in enumerate(sys.argv):
        if arg == "--student" and i + 1 < len(sys.argv):
            student_code = sys.argv[i + 1]
        elif arg == "--program" and i + 1 < len(sys.argv):
            target_program_id = int(sys.argv[i + 1])
            
    print("=" * 60)
    print("  Update Student LMS Program Access")
    print("=" * 60)
    print(f"Database Path: {DB_PATH}")
    print(f"Mode: {'COMMIT (Applying Changes)' if commit else 'DRY RUN (No Changes)'}")
    print(f"Target Student Code: {student_code}")
    print(f"Target Program ID: {target_program_id}")
    print("-" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file does not exist at {DB_PATH}")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 1. Fetch Student details
    cur.execute("SELECT id, student_code, full_name FROM students WHERE student_code = ?", (student_code,))
    student = cur.fetchone()
    if not student:
        print(f"Error: Student with code '{student_code}' not found in database.")
        conn.close()
        sys.exit(1)
        
    student_id = student['id']
    print(f"Found Student: {student['full_name']} (ID: {student_id})")
    
    # 2. Fetch Target Program details
    cur.execute("SELECT id, program_name FROM lms_programs WHERE id = ?", (target_program_id,))
    program = cur.fetchone()
    if not program:
        print(f"Error: Program with ID {target_program_id} not found in database.")
        conn.close()
        sys.exit(1)
        
    print(f"Target Program: {program['program_name']} (ID: {target_program_id})")
    print("-" * 60)
    
    # 3. Find current access records
    cur.execute("""
        SELECT spa.*, lp.program_name 
        FROM lms_student_program_access spa
        JOIN lms_programs lp ON lp.id = spa.program_id
        WHERE spa.student_id = ?
    """, (student_id,))
    current_records = cur.fetchall()
    
    print("Current Program Access Records:")
    if not current_records:
        print("  No records found.")
    for r in current_records:
        status_str = "Active" if r['is_active'] == 1 else "Suspended"
        print(f"  - Program: {r['program_name']} (ID: {r['program_id']}) -> Status: {status_str} (Record ID: {r['id']})")
    print("-" * 60)
    
    # 4. Prepare updates
    now_date = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat(timespec="seconds")
    
    # We want to:
    # A. Suspend any other programs that are currently active
    records_to_suspend = [r for r in current_records if r['program_id'] != target_program_id and r['is_active'] == 1]
    
    # B. Activate or Insert target program
    target_record = next((r for r in current_records if r['program_id'] == target_program_id), None)
    
    print("Proposed Actions:")
    if not records_to_suspend and target_record and target_record['is_active'] == 1:
        print("  Student already has active access to target program and no other programs are active. No changes needed.")
        conn.close()
        sys.exit(0)
        
    for r in records_to_suspend:
        print(f"  [SUSPEND] Suspend access to program: {r['program_name']} (Record ID: {r['id']})")
        
    if target_record:
        if target_record['is_active'] == 0:
            print(f"  [ACTIVATE] Reactivate existing access record for program: {program['program_name']} (Record ID: {target_record['id']})")
        else:
            print(f"  [KEEP] Keep active access to program: {program['program_name']} (Record ID: {target_record['id']})")
    else:
        print(f"  [INSERT] Create new active access record for program: {program['program_name']}")
        
    print("-" * 60)
    
    if commit:
        # Perform Suspensions
        for r in records_to_suspend:
            cur.execute("""
                UPDATE lms_student_program_access 
                SET is_active = 0, access_status = 'suspended', updated_at = ?
                WHERE id = ?
            """, (now_iso, r['id']))
            
        # Perform Activation/Insertion
        if target_record:
            if target_record['is_active'] == 0:
                cur.execute("""
                    UPDATE lms_student_program_access
                    SET is_active = 1, access_status = 'active', updated_at = ?
                    WHERE id = ?
                """, (now_iso, target_record['id']))
        else:
            cur.execute("""
                INSERT INTO lms_student_program_access (
                    student_id, program_id, access_start_date, access_status, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', 1, ?, ?)
            """, (student_id, target_program_id, now_date, now_iso, now_iso))
            
        conn.commit()
        print("SUCCESS: Database changes committed successfully!")
    else:
        print("Dry Run complete. No changes were saved to the database.")
        print("To execute this update, run the script with the --commit flag:")
        print("python scripts/update_student_program_access.py --commit")
        
    conn.close()

if __name__ == '__main__':
    main()
