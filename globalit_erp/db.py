import sqlite3
from datetime import datetime
from config import DB_PATH
from werkzeug.security import generate_password_hash

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            branch_id INTEGER,
            can_view_all_branches INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        SELECT id FROM users WHERE username = ?
    """, ("admin",))
    existing_admin = cur.fetchone()

    if not existing_admin:
        cur.execute("""
            INSERT INTO users (
                full_name, username, password_hash, role,
                branch_id, can_view_all_branches, is_active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Administrator",
            "admin",
            generate_password_hash("admin123"),
            "admin",
            1,
            1,
            1,
            datetime.now().isoformat(timespec="seconds")
        ))

    conn.commit()
    conn.close()