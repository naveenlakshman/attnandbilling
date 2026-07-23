"""Phase 2 MySQL/Flask isolation and Platform Administration tests."""

from __future__ import annotations

import uuid

from app import app
from db import get_conn
from services.tenant_context import clear_tenant_cache
from werkzeug.security import generate_password_hash


TOKEN = uuid.uuid4().hex[:10]
SLUG = f"phase2-{TOKEN}"
HOST = f"{SLUG}.localhost"


def owner_client():
    conn = get_conn()
    try:
        owner = conn.execute(
            """SELECT id, username, institute_id FROM users
               WHERE platform_role = 'platform_owner' AND is_active = 1
               ORDER BY id LIMIT 1"""
        ).fetchone()
        assert owner, "Provision a dedicated platform owner before running Phase 2 tests."
    finally:
        conn.close()
    client = app.test_client()
    with client.session_transaction(base_url="https://www.globaliterp.com") as s:
        s.update(
            user_id=owner["id"],
            username=owner["username"],
            role="admin",
            platform_role="platform_owner",
            institute_id=owner["institute_id"],
            can_view_all_branches=1,
        )
    return client


def tenant_client(institute_id, user_id, host):
    client = app.test_client()
    with client.session_transaction(base_url=f"https://{host}") as s:
        s.update(
            user_id=user_id,
            username=f"admin-{TOKEN}",
            role="admin",
            platform_role=None,
            institute_id=institute_id,
            can_view_all_branches=1,
        )
    return client


def verify_schema():
    conn = get_conn()
    try:
        for table, column in (
            ("branches", "institute_id"),
            ("users", "institute_id"),
            ("users", "platform_role"),
        ):
            assert conn.execute(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?""",
                (table, column),
            ).fetchone()
        assert conn.execute(
            "SELECT COUNT(*) n FROM branches WHERE institute_id IS NULL"
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) n FROM users WHERE institute_id IS NULL"
        ).fetchone()["n"] == 0
    finally:
        conn.close()
    print("phase2_schema_and_backfill=OK")


def verify_platform_role_separation():
    conn = get_conn()
    try:
        institute_admin = conn.execute(
            """SELECT u.id, u.username, u.institute_id
               FROM users u
               JOIN institute_memberships im
                 ON im.user_id = u.id AND im.institute_id = u.institute_id
               WHERE u.platform_role IS NULL
                 AND im.membership_role = 'institute_admin'
                 AND u.is_active = 1 AND im.is_active = 1
               ORDER BY u.id LIMIT 1"""
        ).fetchone()
        assert institute_admin
    finally:
        conn.close()

    client = tenant_client(
        institute_admin["institute_id"],
        institute_admin["id"],
        "www.globaliterp.com",
    )
    denied = client.get("/platform/institutes", base_url="https://www.globaliterp.com")
    assert denied.status_code == 403
    users_page = client.get("/users", base_url="https://www.globaliterp.com")
    assert users_page.status_code == 200
    assert b"platform_owner" not in users_page.data
    print("phase2_institute_admin_cannot_manage_platform=OK")
    print("phase2_platform_identity_hidden_from_tenant_user_crud=OK")


def create_tenant():
    response = owner_client().post(
        "/platform/institutes/new",
        base_url="https://www.globaliterp.com",
        data={
            "name": f"Phase 2 Institute {TOKEN}",
            "short_name": f"P2 {TOKEN}",
            "slug": SLUG,
            "hostname": HOST,
            "timezone": "Asia/Kolkata",
            "locale": "en-IN",
            "currency_code": "INR",
            "tagline": "Isolation test",
            "primary_color": "#2563eb",
            "secondary_color": "#16a34a",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    conn = get_conn()
    try:
        institute = conn.execute(
            "SELECT * FROM institutes WHERE slug = ?", (SLUG,)
        ).fetchone()
        assert institute
        institute_id = institute["id"]
        conn.execute(
            """UPDATE institute_domains SET status = 'active', verified_at = NOW()
               WHERE institute_id = ? AND hostname = ?""",
            (institute_id, HOST),
        )
        conn.commit()
        return institute_id
    finally:
        conn.close()


def verify_platform_crud(institute_id):
    client = owner_client()
    base = "https://www.globaliterp.com"
    listing = client.get("/platform/institutes", base_url=base)
    assert listing.status_code == 200 and SLUG.encode() in listing.data
    detail = client.get(f"/platform/institutes/{institute_id}", base_url=base)
    assert detail.status_code == 200
    branch = client.post(
        f"/platform/institutes/{institute_id}/branches/new",
        base_url=base,
        data={
            "branch_name": f"Main {TOKEN}",
            "branch_code": "MAIN",
            "address": "Phase 2",
            "no_of_computers": "5",
        },
    )
    assert branch.status_code == 302
    admin = client.post(
        f"/platform/institutes/{institute_id}/administrators/new",
        base_url=base,
        data={
            "full_name": f"Tenant Admin {TOKEN}",
            "username": "shared-admin",
            "password": "Phase2-Test-Only!",
        },
    )
    assert admin.status_code == 302
    conn = get_conn()
    try:
        branch_id = conn.execute(
            "SELECT id FROM branches WHERE institute_id = ? AND branch_code = 'MAIN'",
            (institute_id,),
        ).fetchone()["id"]
        user = conn.execute(
            "SELECT id FROM users WHERE institute_id = ? AND username = 'shared-admin'",
            (institute_id,),
        ).fetchone()
        assert user
        membership = conn.execute(
            """SELECT membership_role FROM institute_memberships
               WHERE institute_id = ? AND user_id = ?""",
            (institute_id, user["id"]),
        ).fetchone()
        assert membership["membership_role"] == "institute_admin"
    finally:
        conn.close()
    print("phase2_platform_institute_branch_admin_crud=OK")
    return branch_id, user["id"]


def verify_isolation(institute_id, user_id):
    conn = get_conn()
    try:
        global_branch = conn.execute(
            "SELECT id FROM branches WHERE institute_id = 1 ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO branches
               (institute_id, branch_name, branch_code, address, is_active, no_of_computers, created_at)
               VALUES (1, ?, 'MAIN', 'Global tenant', 1, 0, NOW())""",
            (f"Global duplicate {TOKEN}",),
        )
        conn.execute(
            """INSERT INTO users
               (institute_id, full_name, username, password_hash, role, is_active,
                can_view_all_branches, created_at)
               VALUES (1, ?, 'shared-admin', ?, 'staff', 1, 0, NOW())""",
            (f"Global duplicate {TOKEN}", generate_password_hash("Global-Test-Only!")),
        )
        global_user_id = conn.execute(
            "SELECT id FROM users WHERE institute_id = 1 AND full_name = ?",
            (f"Global duplicate {TOKEN}",),
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO institute_memberships
               (institute_id, user_id, membership_role, is_active, created_at, updated_at)
               VALUES (1, ?, 'staff', 1, NOW(), NOW())""",
            (global_user_id,),
        )
        conn.commit()
    finally:
        conn.close()

    clear_tenant_cache()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, TENANT_RESOLUTION_MODE="strict")
    client = tenant_client(institute_id, user_id, HOST)
    branches = client.get("/branches", base_url=f"https://{HOST}")
    assert branches.status_code == 200
    assert f"Main {TOKEN}".encode() in branches.data
    assert f"Global duplicate {TOKEN}".encode() not in branches.data
    foreign_edit = client.post(
        f"/branches/{global_branch}/edit",
        base_url=f"https://{HOST}",
        data={"branch_name": "CROSS TENANT", "branch_code": "BAD"},
    )
    assert foreign_edit.status_code in (302, 404)
    denied_platform = client.get("/platform/institutes", base_url=f"https://{HOST}")
    assert denied_platform.status_code == 403
    tenant_login = app.test_client().post(
        "/login",
        base_url=f"https://{HOST}",
        data={"username": "shared-admin", "password": "Phase2-Test-Only!"},
    )
    assert tenant_login.status_code == 302
    global_login = app.test_client().post(
        "/login",
        base_url="https://www.globaliterp.com",
        data={"username": "shared-admin", "password": "Global-Test-Only!"},
    )
    assert global_login.status_code == 302
    print("phase2_duplicate_codes_and_usernames_per_tenant=OK")
    print("phase2_hostname_scoped_login=OK")
    print("phase2_branch_direct_object_isolation=OK")
    print("phase2_platform_owner_authorization=OK")


def cleanup(institute_id):
    app.config["TENANT_RESOLUTION_MODE"] = "observe"
    clear_tenant_cache()
    conn = get_conn()
    try:
        conn.execute(
            """DELETE im FROM institute_memberships im
               JOIN users u ON u.id = im.user_id
               WHERE u.institute_id = 1 AND u.full_name = ?""",
            (f"Global duplicate {TOKEN}",),
        )
        conn.execute(
            "DELETE FROM users WHERE institute_id = 1 AND full_name = ?",
            (f"Global duplicate {TOKEN}",),
        )
        conn.execute(
            "DELETE FROM branches WHERE institute_id = 1 AND branch_name = ?",
            (f"Global duplicate {TOKEN}",),
        )
        if institute_id:
            conn.execute("DELETE FROM institute_memberships WHERE institute_id = ?", (institute_id,))
            conn.execute("DELETE FROM users WHERE institute_id = ?", (institute_id,))
            conn.execute("DELETE FROM branches WHERE institute_id = ?", (institute_id,))
            conn.execute("DELETE FROM institute_domains WHERE institute_id = ?", (institute_id,))
            conn.execute("DELETE FROM institute_branding WHERE institute_id = ?", (institute_id,))
            conn.execute("DELETE FROM institute_settings WHERE institute_id = ?", (institute_id,))
            conn.execute("DELETE FROM institutes WHERE id = ?", (institute_id,))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    tenant_id = None
    try:
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, TENANT_RESOLUTION_MODE="observe")
        verify_schema()
        verify_platform_role_separation()
        tenant_id = create_tenant()
        branch_id, admin_id = verify_platform_crud(tenant_id)
        verify_isolation(tenant_id, admin_id)
        print("PHASE2_MYSQL_TESTS=PASS")
    finally:
        cleanup(tenant_id)
