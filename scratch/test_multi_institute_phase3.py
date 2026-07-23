"""Phase 3 branding, domain, and storage isolation tests."""

from __future__ import annotations

import uuid
from io import BytesIO

from app import app
from db import clear_company_cache, get_conn
from modules.platform_admin.routes import _domain_activation
from services.storage import get_storage_service, tenant_storage_path
from services.tenant_context import _bind_request_tenant, clear_tenant_cache


TOKEN = uuid.uuid4().hex[:10]
HOST_A = f"phase3-a-{TOKEN}.localhost"
HOST_B = f"phase3-b-{TOKEN}.localhost"


def create_institute(label, host):
    conn = get_conn()
    try:
        now = "2026-07-23 00:00:00"
        institute_id = conn.execute(
            """INSERT INTO institutes
               (name, short_name, slug, status, timezone, locale, currency_code,
                created_at, updated_at)
               VALUES (?, ?, ?, 'active', 'Asia/Kolkata', 'en-IN', 'INR', ?, ?)""",
            (
                f"Phase 3 {label} {TOKEN}",
                f"P3{label}",
                f"phase3-{label.lower()}-{TOKEN}",
                now,
                now,
            ),
        ).lastrowid
        conn.execute(
            """INSERT INTO institute_domains
               (institute_id, hostname, domain_type, is_primary, status,
                verified_at, created_at, updated_at)
               VALUES (?, ?, 'platform', 1, 'active', ?, ?, ?)""",
            (institute_id, host, now, now, now),
        )
        conn.execute(
            """INSERT INTO institute_branding
               (institute_id, display_name, short_name, tagline, primary_color,
                secondary_color, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                institute_id,
                f"Phase 3 {label} Brand {TOKEN}",
                f"P3{label}",
                f"{label} tenant",
                "#112233" if label == "A" else "#445566",
                "#778899",
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO institute_settings
               (institute_id, invoice_prefix, receipt_prefix, student_prefix,
                certificate_prefix, date_format, created_at, updated_at)
               VALUES (?, 'INV', 'RCP', 'STU', 'CERT', 'DD-MMM-YYYY', ?, ?)""",
            (institute_id, now, now),
        )
        branch_id = conn.execute(
            """INSERT INTO branches
               (institute_id, branch_name, branch_code, is_active,
                no_of_computers, created_at)
               VALUES (?, ?, 'MAIN', 1, 0, ?)""",
            (institute_id, f"{label} Main", now),
        ).lastrowid
        user_id = conn.execute(
            """INSERT INTO users
               (institute_id, full_name, username, password_hash, role,
                branch_id, can_view_all_branches, is_active, created_at, updated_at)
               VALUES (?, ?, ?, 'test-only', 'admin', ?, 1, 1, ?, ?)""",
            (
                institute_id,
                f"{label} Admin",
                f"phase3-{label.lower()}-{TOKEN}",
                branch_id,
                now,
                now,
            ),
        ).lastrowid
        conn.execute(
            """INSERT INTO institute_memberships
               (institute_id, user_id, membership_role, is_active, created_at, updated_at)
               VALUES (?, ?, 'institute_admin', 1, ?, ?)""",
            (institute_id, user_id, now, now),
        )
        conn.commit()
        return institute_id, user_id
    finally:
        conn.close()


def upload_for_host(host, relative_path, payload):
    with app.test_request_context("/", base_url=f"http://{host}:8080"):
        _bind_request_tenant()
        return get_storage_service().upload_file(payload, relative_path)


def authenticated_client(host, institute_id, user_id):
    client = app.test_client()
    with client.session_transaction(base_url=f"http://{host}:8080") as s:
        s.update(
            user_id=user_id,
            username=f"phase3-{TOKEN}",
            role="admin",
            institute_id=institute_id,
            platform_role=None,
            can_view_all_branches=1,
        )
    return client


def verify_domains():
    original_environment = app.config["APP_ENV"]
    try:
        with app.test_request_context("/"):
            app.config["APP_ENV"] = "development"
            assert _domain_activation("phase3.localhost")[0] == "active"
            assert _domain_activation("tenant.example.com")[0] == "pending"
            app.config["APP_ENV"] = "production"
            assert _domain_activation("phase3.localhost")[0] == "pending"
    finally:
        app.config["APP_ENV"] = original_environment
    print("phase3_domain_readiness_rules=OK")


def verify_branding_and_storage(institute_a, user_a, institute_b, user_b):
    clear_tenant_cache()
    clear_company_cache()
    storage = get_storage_service()

    logo_a = upload_for_host(HOST_A, "branding/logos/shared.png", b"A-logo")
    logo_b = upload_for_host(HOST_B, "branding/logos/shared.png", b"B-logo")
    private_a = upload_for_host(HOST_A, "documents/shared.txt", b"A-private")
    private_b = upload_for_host(HOST_B, "documents/shared.txt", b"B-private")
    assert logo_a == f"tenants/{institute_a}/branding/logos/shared.png"
    assert logo_b == f"tenants/{institute_b}/branding/logos/shared.png"
    assert private_a != private_b

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE institute_branding SET logo_path = ? WHERE institute_id = ?",
            (logo_a, institute_a),
        )
        conn.execute(
            "UPDATE institute_branding SET logo_path = ? WHERE institute_id = ?",
            (logo_b, institute_b),
        )
        conn.commit()
    finally:
        conn.close()
    clear_company_cache()

    public_a = app.test_client(use_cookies=False).get(
        f"/tenant-files/{logo_a}", base_url=f"http://{HOST_A}:8080"
    )
    public_b = app.test_client(use_cookies=False).get(
        f"/tenant-files/{logo_b}", base_url=f"http://{HOST_B}:8080"
    )
    assert public_a.status_code == 200 and public_a.data == b"A-logo"
    assert public_b.status_code == 200 and public_b.data == b"B-logo"
    assert app.test_client(use_cookies=False).get(
        f"/tenant-files/{logo_a}", base_url=f"http://{HOST_B}:8080"
    ).status_code == 404
    conn = get_conn()
    try:
        owner = conn.execute(
            """SELECT id, institute_id FROM users
               WHERE platform_role = 'platform_owner' AND is_active = 1
               ORDER BY id LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()
    owner_client = app.test_client()
    with owner_client.session_transaction(base_url="http://www.globaliterp.com") as s:
        s.update(
            user_id=owner["id"],
            role="admin",
            platform_role="platform_owner",
            institute_id=owner["institute_id"],
        )
    assert owner_client.get(
        f"/tenant-files/{logo_a}", base_url="http://www.globaliterp.com"
    ).status_code == 200

    client_a = authenticated_client(HOST_A, institute_a, user_a)
    assert client_a.get(
        f"/tenant-files/{private_a}", base_url=f"http://{HOST_A}:8080"
    ).data == b"A-private"
    assert client_a.get(
        f"/tenant-files/{private_b}", base_url=f"http://{HOST_A}:8080"
    ).status_code == 404
    assert app.test_client(use_cookies=False).get(
        f"/tenant-files/{private_a}", base_url=f"http://{HOST_A}:8080"
    ).status_code == 404

    login_a = app.test_client(use_cookies=False).get(
        "/login", base_url=f"http://{HOST_A}:8080"
    )
    login_b = app.test_client(use_cookies=False).get(
        "/login", base_url=f"http://{HOST_B}:8080"
    )
    assert f"Phase 3 A Brand {TOKEN}".encode() in login_a.data
    assert f"Phase 3 B Brand {TOKEN}".encode() in login_b.data
    assert f"/tenant-files/{logo_a}".encode() in login_a.data
    assert f"/tenant-files/{logo_b}".encode() in login_b.data

    branding_update = client_a.post(
        "/institute/branding",
        base_url=f"http://{HOST_A}:8080",
        data={
            "display_name": f"Phase 3 A Self Service {TOKEN}",
            "short_name": "P3A",
            "tagline": "Updated by institute admin",
            "primary_color": "#123456",
            "secondary_color": "#654321",
            "logo": (BytesIO(b"test-png-payload"), "brand.png"),
        },
        content_type="multipart/form-data",
    )
    assert branding_update.status_code == 302
    conn = get_conn()
    try:
        updated_brand = conn.execute(
            "SELECT display_name, logo_path FROM institute_branding WHERE institute_id = ?",
            (institute_a,),
        ).fetchone()
    finally:
        conn.close()
    assert updated_brand["display_name"] == f"Phase 3 A Self Service {TOKEN}"
    assert updated_brand["logo_path"].startswith(
        f"tenants/{institute_a}/branding/logos/"
    )
    assert updated_brand["logo_path"] != logo_a

    with app.test_request_context("/", base_url=f"http://{HOST_B}:8080"):
        _bind_request_tenant()
        try:
            storage.delete_file(private_a)
            raise AssertionError("Cross-tenant delete unexpectedly succeeded")
        except PermissionError:
            pass
    with app.test_request_context("/", base_url=f"http://{HOST_A}:8080"):
        _bind_request_tenant()
        assert storage.file_exists(private_a)

    with app.test_request_context("/", base_url="http://www.globaliterp.com"):
        _bind_request_tenant()
        legacy = tenant_storage_path(f"documents/phase3-{TOKEN}.txt")
        assert legacy == f"documents/phase3-{TOKEN}.txt"

    print("phase3_distinct_branding_by_domain=OK")
    print("phase3_institute_admin_branding_self_service=OK")
    print("phase3_tenant_prefixed_storage=OK")
    print("phase3_private_file_delivery=OK")
    print("phase3_cross_tenant_read_delete_denied=OK")
    print("phase3_global_it_legacy_path_compatibility=OK")
    return [logo_a, logo_b, private_a, private_b, updated_brand["logo_path"]]


def cleanup(institute_ids, paths):
    clear_tenant_cache()
    clear_company_cache()
    storage = get_storage_service()
    for path in paths:
        try:
            storage.delete_file(path)
        except Exception:
            pass
    conn = get_conn()
    try:
        for institute_id in institute_ids:
            if not institute_id:
                continue
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, TENANT_RESOLUTION_MODE="strict")
    ids = []
    paths = []
    try:
        verify_domains()
        institute_a, user_a = create_institute("A", HOST_A)
        institute_b, user_b = create_institute("B", HOST_B)
        ids = [institute_a, institute_b]
        paths = verify_branding_and_storage(
            institute_a, user_a, institute_b, user_b
        )
        print("PHASE3_MYSQL_TESTS=PASS")
    finally:
        cleanup(ids, paths)
