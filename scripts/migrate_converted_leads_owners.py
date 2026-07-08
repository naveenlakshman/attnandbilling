"""
Migration: Assign all existing unassigned converted leads to the user who registered the student.
Run once in production:
    python scripts/migrate_converted_leads_owners.py
"""

import sqlite3
import os

DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'instance', 'database.db')
)

def run():
    print(f"Connecting to database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find converted leads without an owner
    cur.execute("""
        SELECT id, name, created_at
        FROM leads
        WHERE status = 'converted'
          AND assigned_to_id IS NULL
    """)
    unassigned_leads = cur.fetchall()

    print(f"Found {len(unassigned_leads)} unassigned converted leads.")
    updated_count = 0

    for lead in unassigned_leads:
        lead_id = lead["id"]
        lead_name = lead["name"]
        
        # 1. Find the linked student
        cur.execute("SELECT id, full_name FROM students WHERE lead_id = ?", (lead_id,))
        student = cur.fetchone()
        if not student:
            print(f"Lead ID {lead_id} ({lead_name}) has no linked student.")
            continue
            
        student_id = student["id"]
        student_name = student["full_name"]
        
        # 2. Find the student creation log
        cur.execute("""
            SELECT user_id, created_at
            FROM activity_logs
            WHERE module_name = 'students'
              AND record_id = ?
              AND action_type = 'create'
            ORDER BY id ASC
            LIMIT 1
        """, (student_id,))
        log = cur.fetchone()
        
        if not log:
            # Fallback: find any activity log for this student
            cur.execute("""
                SELECT user_id, created_at
                FROM activity_logs
                WHERE module_name = 'students'
                  AND record_id = ?
                ORDER BY id ASC
                LIMIT 1
            """, (student_id,))
            log = cur.fetchone()
            
        if log:
            creator_id = log["user_id"]
            # Fetch creator username/name
            cur.execute("SELECT full_name, username FROM users WHERE id = ?", (creator_id,))
            user = cur.fetchone()
            user_desc = f"{user['full_name']} ({user['username']})" if user else f"User ID {creator_id}"
            
            # 3. Update the lead's owner
            cur.execute("""
                UPDATE leads
                SET assigned_to_id = ?
                WHERE id = ?
            """, (creator_id, lead_id))
            
            print(f"Assigned Lead ID {lead_id} ({lead_name}) -> Owner {user_desc} (registered student {student_name})")
            updated_count += 1
        else:
            print(f"Could not find any student registration activity logs for student {student_name} (ID: {student_id}).")

    conn.commit()
    conn.close()

    print(f"Successfully migrated {updated_count} leads.")

if __name__ == '__main__':
    run()
