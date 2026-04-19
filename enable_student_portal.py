"""
Run this once to enable portal access for a student.
Usage: .venv\Scripts\python enable_student_portal.py
"""
from werkzeug.security import generate_password_hash
import sqlite3

conn = sqlite3.connect('instance/database.db')
conn.row_factory = sqlite3.Row

students = conn.execute("SELECT id, full_name, student_code, portal_enabled FROM students ORDER BY id").fetchall()
print("\nAll students:")
print(f"{'ID':<5} {'Name':<30} {'Code':<15} {'Portal Enabled'}")
print("-" * 60)
for s in students:
    print(f"{s['id']:<5} {s['full_name']:<30} {s['student_code']:<15} {s['portal_enabled']}")

print("\nEnabling portal for ALL students (password = their student_code)...")
for s in students:
    ph = generate_password_hash(s['student_code'])
    conn.execute(
        "UPDATE students SET password_hash = ?, portal_enabled = 1 WHERE id = ?",
        (ph, s['id'])
    )
    print(f"  ✓ {s['full_name']} ({s['student_code']}) — password set to: {s['student_code']}")

conn.commit()
conn.close()
print("\nDone! Login at: http://127.0.0.1:5000/student/login")
print("Use Student ID as both username and password.")
