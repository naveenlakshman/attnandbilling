"""Script to add/update 'kavya' as a Platform Owner in platform_accounts table."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
from db import get_conn


def add_kavya_platform_owner():
    username = "kavya"
    full_name = "Kavya"
    password = "Navi@170895"
    password_hash = generate_password_hash(password)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()

    # Ensure table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS platform_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'platform_owner',
            is_active INTEGER NOT NULL DEFAULT 1,
            last_login_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    existing = conn.execute(
        "SELECT id FROM platform_accounts WHERE username = ?",
        (username,),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE platform_accounts
               SET full_name = ?, password_hash = ?, role = 'platform_owner',
                   is_active = 1, updated_at = ?
               WHERE username = ?""",
            (full_name, password_hash, now, username),
        )
        print(f"Updated platform owner '{username}' successfully.")
    else:
        conn.execute(
            """INSERT INTO platform_accounts (
                   full_name, username, password_hash, role, is_active,
                   created_at, updated_at
               ) VALUES (?, ?, ?, 'platform_owner', 1, ?, ?)""",
            (full_name, username, password_hash, now, now),
        )
        print(f"Created platform owner '{username}' successfully.")

    # Also ensure kavya exists in users table for default institute (institute_id=1)
    user_existing = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    ).fetchone()

    if not user_existing:
        conn.execute(
            """INSERT INTO users (
                   institute_id, branch_id, full_name, username, password_hash, role,
                   platform_role, is_active, can_view_all_branches, created_at, updated_at
               ) VALUES (1, 1, ?, ?, ?, 'admin', 'platform_owner', 1, 1, ?, ?)""",
            (full_name, username, password_hash, now, now),
        )
        print(f"Added '{username}' to users table for institute 1.")
    else:
        conn.execute(
            """UPDATE users
               SET password_hash = ?, role = 'admin', platform_role = 'platform_owner', is_active = 1
               WHERE username = ?""",
            (password_hash, username),
        )
        print(f"Updated '{username}' in users table.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    add_kavya_platform_owner()
