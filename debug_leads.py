import sqlite3
from config import DB_PATH

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Get table schema
print("=== LEADS TABLE SCHEMA ===")
cur.execute("PRAGMA table_info(leads)")
columns = cur.fetchall()
for col in columns:
    print(f"{col[1]}: {col[2]}")

print("\n=== SAMPLE DATA ===")
cur.execute("SELECT id, name, stage, status FROM leads LIMIT 5")
rows = cur.fetchall()
for row in rows:
    print(f"ID: {row[0]}, Name: {row[1]}, Stage: {row[2]}, Status: {row[3]}")

print("\n=== CONVERTED COUNTS ===")
cur.execute('SELECT COUNT(*) FROM leads WHERE stage = "Converted"')
count_by_stage = cur.fetchone()[0]
print(f"By Stage='Converted': {count_by_stage}")

cur.execute('SELECT COUNT(*) FROM leads WHERE status = "converted"')
count_by_status = cur.fetchone()[0]
print(f"By Status='converted': {count_by_status}")

conn.close()
