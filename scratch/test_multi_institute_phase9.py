"""Phase 9 MySQL integration checks.

Run in the Docker web container:
    PYTHONPATH=/app python /app/scratch/test_multi_institute_phase9.py
"""

from datetime import datetime
import re
from uuid import uuid4

from app import create_app
from db import get_conn
from services.storage import get_storage_service
from services.subscriptions import (
    PlanLimitExceeded,
    SubscriptionAccessDenied,
    assert_feature_enabled,
    assert_subscription_access,
    lock_and_check_limit,
)


token = uuid4().hex[:10]
slug = f"phase9-{token}"
hostname = f"{slug}.localhost"
now = datetime.now().isoformat(timespec="seconds")
conn = get_conn()
institute_id = None
user_id = None
branch_id = None
storage_path = None
wizard_institute_id = None

try:
    plan = conn.execute(
        "SELECT id FROM subscription_plans WHERE code = 'starter'"
    ).fetchone()
    assert plan, "Starter plan migration was not applied"

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO institutes (
            name, short_name, slug, status, timezone, locale, currency_code,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'active', 'Asia/Kolkata', 'en-IN', 'INR', ?, ?)
        """,
        (f"Phase 9 {token}", "P9", slug, now, now),
    )
    institute_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO institute_subscriptions (
            institute_id, plan_id, status, branch_limit_override,
            staff_limit_override, student_limit_override,
            storage_limit_bytes_override, feature_overrides_json,
            starts_at, created_at, updated_at
        ) VALUES (?, ?, 'active', 1, 1, 0, 10,
                  '{"certificates": false, "crm": true}', ?, ?, ?)
        """,
        (institute_id, plan["id"], now, now, now),
    )
    cur.execute(
        """
        INSERT INTO institute_domains (
            institute_id, hostname, domain_type, is_primary, status,
            verified_at, created_at, updated_at
        ) VALUES (?, ?, 'platform', 1, 'active', ?, ?, ?)
        """,
        (institute_id, hostname, now, now, now),
    )
    conn.commit()

    # Branch creation is serialized against the subscription row.
    lock_and_check_limit(conn, institute_id, "branches")
    cur.execute(
        """
        INSERT INTO branches (
            institute_id, branch_name, branch_code, is_active, created_at
        ) VALUES (?, 'Phase 9 Branch', ?, 1, ?)
        """,
        (institute_id, f"P9{token[:5]}", now),
    )
    branch_id = cur.lastrowid
    conn.commit()
    try:
        lock_and_check_limit(conn, institute_id, "branches")
        raise AssertionError("Second active branch bypassed the plan limit")
    except PlanLimitExceeded:
        conn.rollback()

    # Staff creation uses the same transactional pattern.
    lock_and_check_limit(conn, institute_id, "staff")
    cur.execute(
        """
        INSERT INTO users (
            institute_id, full_name, username, password_hash, role,
            platform_role, branch_id, can_view_all_branches, is_active,
            created_at, updated_at
        ) VALUES (?, 'Phase 9 Admin', ?, 'not-a-login-hash', 'admin',
                  NULL, ?, 1, 1, ?, ?)
        """,
        (institute_id, f"p9_{token}", branch_id, now, now),
    )
    user_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO institute_memberships (
            institute_id, user_id, membership_role, is_active, created_at, updated_at
        ) VALUES (?, ?, 'institute_admin', 1, ?, ?)
        """,
        (institute_id, user_id, now, now),
    )
    conn.commit()
    try:
        lock_and_check_limit(conn, institute_id, "staff")
        raise AssertionError("Second active staff user bypassed the plan limit")
    except PlanLimitExceeded:
        conn.rollback()

    try:
        lock_and_check_limit(conn, institute_id, "students")
        raise AssertionError("Student creation bypassed the zero-student override")
    except PlanLimitExceeded:
        conn.rollback()

    # Storage metadata and upload path both enforce the byte quota.
    conn.execute(
        """
        INSERT INTO tenant_storage_objects (
            institute_id, object_path, size_bytes, content_type, created_at, updated_at
        ) VALUES (?, ?, 8, 'application/octet-stream', ?, ?)
        """,
        (institute_id, f"tenants/{institute_id}/tests/existing.bin", now, now),
    )
    conn.commit()
    try:
        lock_and_check_limit(conn, institute_id, "storage", 3)
        raise AssertionError("Storage exceeded its byte quota")
    except PlanLimitExceeded:
        conn.rollback()

    storage_path = f"tenants/{institute_id}/tests/allowed.bin"
    stored = get_storage_service().upload_file(
        b"12", storage_path, content_type="application/octet-stream"
    )
    assert stored == storage_path
    tracked = conn.execute(
        "SELECT size_bytes FROM tenant_storage_objects WHERE object_path = ?",
        (storage_path,),
    ).fetchone()
    assert tracked and int(tracked["size_bytes"]) == 2

    assert_feature_enabled(conn, institute_id, "crm")
    try:
        assert_feature_enabled(conn, institute_id, "certificates")
        raise AssertionError("Disabled feature was accessible")
    except SubscriptionAccessDenied:
        pass

    conn.execute(
        "UPDATE institute_subscriptions SET status = 'suspended' WHERE institute_id = ?",
        (institute_id,),
    )
    conn.commit()
    try:
        assert_subscription_access(conn, institute_id)
        raise AssertionError("Suspended institute retained access")
    except SubscriptionAccessDenied:
        pass
    conn.execute(
        "UPDATE institute_subscriptions SET status = 'active' WHERE institute_id = ?",
        (institute_id,),
    )
    conn.commit()
    assert_subscription_access(conn, institute_id)

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    owner = conn.execute(
        """SELECT id, institute_id FROM users
           WHERE platform_role = 'platform_owner' AND is_active = 1 LIMIT 1"""
    ).fetchone()
    assert owner, "Platform owner fixture is missing"
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = owner["id"]
        session["institute_id"] = owner["institute_id"]
        session["platform_role"] = "platform_owner"
        session["role"] = "admin"
    response = client.get("/platform/onboarding/new")
    assert response.status_code == 200
    assert b"Step 1 of 9" in response.data
    assert b"Platform Administration" in response.data
    assert b"Manage Institutes" in response.data
    assert b"Add New Institute" in response.data
    response = client.get(f"/platform/institutes/{institute_id}/subscription")
    assert response.status_code == 200
    assert b"Plan, limits and access" in response.data

    # Complete all nine onboarding steps through the platform-owner HTTP UI.
    wizard_token = uuid4().hex[:10]
    response = client.post(
        "/platform/onboarding/new",
        data={
            "name": f"Wizard {wizard_token}",
            "short_name": "WIZ",
            "slug": f"wizard-{wizard_token}",
            "timezone": "Asia/Kolkata",
            "locale": "en-IN",
            "currency_code": "INR",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    match = re.search(r"/platform/onboarding/(\d+)/step/2", response.headers["Location"])
    assert match
    wizard_institute_id = int(match.group(1))
    starter_id = plan["id"]
    steps = [
        (
            2,
            {
                "plan_id": starter_id,
                "subscription_status": "active",
                "trial_days": 0,
            },
        ),
        (3, {"hostname": f"wizard-{wizard_token}.localhost"}),
        (
            4,
            {
                "display_name": f"Wizard {wizard_token}",
                "short_name": "WIZ",
                "tagline": "Phase 9",
                "primary_color": "#2563EB",
                "secondary_color": "#16A34A",
            },
        ),
        (
            5,
            {
                "branch_name": "Main Branch",
                "branch_code": f"W{wizard_token[:5]}",
                "no_of_computers": 1,
            },
        ),
        (
            6,
            {
                "full_name": "Wizard Administrator",
                "username": f"wizard_{wizard_token}",
                "password": "Phase9-Test-Only!",
                "branch_id": "",
            },
        ),
        (
            7,
            {
                "invoice_prefix": "WINV",
                "receipt_prefix": "WRCP",
                "student_prefix": "WSTU",
                "certificate_prefix": "WCERT",
                "date_format": "DD-MMM-YYYY",
            },
        ),
        (
            8,
            {
                "sms_provider": "not-configured",
                "email_provider": "not-configured",
                "storage_provider": "local",
                "storage_ready": "1",
            },
        ),
    ]
    for step_number, data in steps:
        response = client.post(
            f"/platform/onboarding/{wizard_institute_id}/step/{step_number}",
            data=data,
            follow_redirects=False,
        )
        assert response.status_code == 302, (step_number, response.status_code)
    response = client.get(
        f"/platform/onboarding/{wizard_institute_id}/step/9"
    )
    assert response.status_code == 200
    assert b"Activate institute" in response.data
    response = client.post(
        f"/platform/onboarding/{wizard_institute_id}/activate",
        follow_redirects=False,
    )
    assert response.status_code == 302
    conn.rollback()  # End the earlier repeatable-read snapshot before verification.
    activated = conn.execute(
        """SELECT i.status, o.status AS onboarding_status
           FROM institutes i
           JOIN institute_onboarding o ON o.institute_id = i.id
           WHERE i.id = ?""",
        (wizard_institute_id,),
    ).fetchone()
    assert activated["status"] == "active"
    assert activated["onboarding_status"] == "completed"

    print("PHASE9_MYSQL_TESTS=PASS")
finally:
    try:
        if storage_path:
            get_storage_service().delete_file(storage_path)
    except Exception:
        pass
    for cleanup_institute_id in (wizard_institute_id, institute_id):
        if not cleanup_institute_id:
            continue
        conn.rollback()
        conn.execute(
            "DELETE FROM tenant_storage_objects WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute(
            "DELETE FROM institute_memberships WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute("DELETE FROM users WHERE institute_id = ?", (cleanup_institute_id,))
        conn.execute("DELETE FROM branches WHERE institute_id = ?", (cleanup_institute_id,))
        conn.execute(
            "DELETE FROM institute_domains WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute(
            "DELETE FROM institute_integrations WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute(
            "DELETE FROM institute_onboarding WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute(
            "DELETE FROM institute_subscriptions WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute(
            "DELETE FROM institute_branding WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute(
            "DELETE FROM institute_settings WHERE institute_id = ?",
            (cleanup_institute_id,),
        )
        conn.execute("DELETE FROM institutes WHERE id = ?", (cleanup_institute_id,))
        conn.commit()
    conn.close()
