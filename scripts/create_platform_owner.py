"""Create or rotate a dedicated platform-owner account.

The password must be supplied through PLATFORM_OWNER_PASSWORD so it is not
stored in source code or exposed in command history.
"""

from __future__ import annotations

import argparse
import os
import sys

from werkzeug.security import generate_password_hash

from db import get_conn


def parse_args():
    parser = argparse.ArgumentParser(description="Provision a dedicated platform owner.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument(
        "--host-institute-slug",
        default="global-it-education",
        help="Institute whose verified hostname will be used for login.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    password = os.environ.get("PLATFORM_OWNER_PASSWORD", "")
    if len(password) < 16:
        raise SystemExit("PLATFORM_OWNER_PASSWORD must contain at least 16 characters.")

    conn = get_conn()
    try:
        institute = conn.execute(
            "SELECT id FROM institutes WHERE slug = ? AND status = 'active'",
            (args.host_institute_slug,),
        ).fetchone()
        if not institute:
            raise SystemExit("The requested active host institute was not found.")
        institute_id = institute["id"]

        existing = conn.execute(
            "SELECT * FROM users WHERE institute_id = ? AND username = ?",
            (institute_id, args.username),
        ).fetchone()
        if existing and existing.get("platform_role") != "platform_owner":
            raise SystemExit(
                "That username belongs to an institute user. Choose a dedicated username."
            )

        password_hash = generate_password_hash(password)
        if existing:
            user_id = existing["id"]
            conn.execute(
                """
                UPDATE users
                SET full_name = ?, password_hash = ?, role = 'admin',
                    platform_role = 'platform_owner', branch_id = NULL,
                    can_view_all_branches = 1, is_active = 1, updated_at = NOW()
                WHERE id = ? AND institute_id = ?
                """,
                (args.full_name, password_hash, user_id, institute_id),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    institute_id, full_name, username, password_hash, role,
                    platform_role, branch_id, can_view_all_branches, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'admin', 'platform_owner', NULL, 1, 1, NOW(), NOW())
                """,
                (institute_id, args.full_name, args.username, password_hash),
            )
            user_id = cursor.lastrowid

        membership = conn.execute(
            """SELECT id FROM institute_memberships
               WHERE institute_id = ? AND user_id = ?""",
            (institute_id, user_id),
        ).fetchone()
        if membership:
            conn.execute(
                """UPDATE institute_memberships
                   SET membership_role = 'platform_owner', is_active = 1, updated_at = NOW()
                   WHERE id = ?""",
                (membership["id"],),
            )
        else:
            conn.execute(
                """
                INSERT INTO institute_memberships (
                    institute_id, user_id, membership_role, is_active, created_at, updated_at
                ) VALUES (?, ?, 'platform_owner', 1, NOW(), NOW())
                """,
                (institute_id, user_id),
            )
        conn.commit()
        print(
            f"Platform owner '{args.username}' is active on institute "
            f"'{args.host_institute_slug}'."
        )
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
