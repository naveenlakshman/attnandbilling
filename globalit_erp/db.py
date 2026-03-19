import sqlite3
from datetime import datetime
from config import DB_PATH
from werkzeug.security import generate_password_hash

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def log_activity(user_id, branch_id, action_type, module_name, record_id, description):
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute("""
            INSERT INTO activity_logs (
                user_id,
                branch_id,
                action_type,
                module_name,
                record_id,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            branch_id,
            action_type,
            module_name,
            record_id,
            description,
            now
        ))
        conn.commit()
    finally:
        conn.close()

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

    # ---------- LEADS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            whatsapp TEXT,
            gender TEXT,
            age INTEGER,

            education_status TEXT,
            stream TEXT,
            institute_name TEXT,

            career_goal TEXT,
            interested_courses TEXT,

            lead_source TEXT,
            decision_maker TEXT DEFAULT 'Self',

            start_timeframe TEXT,
            lead_score INTEGER DEFAULT 0,

            stage TEXT DEFAULT 'New Lead',
            status TEXT DEFAULT 'active',
            lost_reason TEXT,

            last_contact_date TEXT,
            next_followup_date TEXT,
            followup_count INTEGER DEFAULT 0,

            notes TEXT,
            is_deleted INTEGER DEFAULT 0,

            assigned_to_id INTEGER,

            created_at TEXT NOT NULL,
            updated_at TEXT,

            FOREIGN KEY (assigned_to_id) REFERENCES users(id)
        )
    """)
    # ---------- FOLLOWUPS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            lead_id INTEGER NOT NULL,
            user_id INTEGER,

            method TEXT,
            outcome TEXT,
            note TEXT,

            next_followup_date TEXT,

            created_at TEXT NOT NULL,

            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        branch_id INTEGER,
        action_type TEXT NOT NULL,
        module_name TEXT NOT NULL,
        record_id INTEGER,
        description TEXT NOT NULL,
        created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()