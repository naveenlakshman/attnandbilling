#!/usr/bin/env python3
import sqlite3

db_path = "instance/database.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Update invoice status
cur.execute("UPDATE invoices SET status = 'write_off' WHERE id = 32")
conn.commit()

# Verify
cur.execute("SELECT id, status FROM invoices WHERE id = 32")
result = cur.fetchone()
print(f"Invoice {result['id']} status updated to: {result['status']}")

conn.close()
