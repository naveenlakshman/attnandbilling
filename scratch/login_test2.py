from werkzeug.security import check_password_hash, generate_password_hash
import pymysql

conn = pymysql.connect(
    host='127.0.0.1',
    port=3308,
    user='root',
    password='Password123!',
    database='attn_billing_testing',
    cursorclass=pymysql.cursors.DictCursor
)
cur = conn.cursor()
cur.execute("SELECT id, username, password_hash, role, institute_id FROM users WHERE username = 'test2' OR institute_id = 16")
users = cur.fetchall()
print("USERS:", users)
for u in users:
    print(u['username'], "Password123! valid?:", check_password_hash(u['password_hash'], 'Password123!'))

conn.close()
