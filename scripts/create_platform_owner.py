"""Create or rotate a dedicated, institute-independent platform account."""

from __future__ import annotations

import argparse
import os
import sys

from werkzeug.security import generate_password_hash

from db import get_conn


def parse_args():
    parser = argparse.ArgumentParser(description="Provision a platform owner.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    password = os.environ.get("PLATFORM_OWNER_PASSWORD", "")
    if len(password) < 16:
        raise SystemExit("PLATFORM_OWNER_PASSWORD must contain at least 16 characters.")
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM platform_accounts WHERE username = ?",
            (args.username,),
        ).fetchone()
        password_hash = generate_password_hash(password)
        if existing:
            conn.execute(
                """UPDATE platform_accounts
                   SET full_name = ?, password_hash = ?, role = 'platform_owner',
                       is_active = 1, updated_at = NOW()
                   WHERE id = ?""",
                (args.full_name, password_hash, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO platform_accounts (
                       full_name, username, password_hash, role, is_active,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, 'platform_owner', 1, NOW(), NOW())""",
                (args.full_name, args.username, password_hash),
            )
        conn.commit()
        print(f"Platform owner '{args.username}' is active.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
