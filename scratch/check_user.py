import os
import pymysql

conn = pymysql.connect(
    host='127.0.0.1',
    port=3308,
    user='appuser',
    password='Password123!',
    database='attn_billing_testing',
    cursorclass=pymysql.cursors.DictCursor
)
cur = conn.cursor()
cur.execute("SELECT id, username, institute_id, role FROM users WHERE username LIKE '%test%' OR username = 'admin'")
for r in cur.fetchall():
    print(r)
conn.close()
