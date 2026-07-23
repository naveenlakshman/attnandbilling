"""Phase 1 MySQL/Flask tests for the additive tenant foundation."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import g, jsonify, session

from app import app
from db import clear_company_cache, get_company_profile, get_conn, log_activity
from services.tenant_context import (
    clear_tenant_cache,
    get_current_institute_id,
    tenant_cache_key,
)


TOKEN = uuid.uuid4().hex[:10]
TENANT_SLUG = f"phase1-{TOKEN}"
TENANT_HOST = f"{TENANT_SLUG}.localhost"
UNKNOWN_HOST = f"unknown-{TOKEN}.example"


def add_test_routes():
    @app.get("/__phase1/context")
    def phase1_context_probe():
        tenant = getattr(g, "tenant", None)
        return jsonify({
            "institute_id": tenant.institute_id if tenant else None,
            "source": tenant.resolution_source if tenant else None,
            "session_institute_id": session.get("institute_id"),
        })

    @app.post("/__phase1/log")
    def phase1_log_probe():
        log_activity(None, None, "phase1_probe", "tenant_foundation", None, TOKEN)
        return jsonify({"institute_id": get_current_institute_id()})


def create_second_institute():
    conn = get_conn()
    try:
        institute_id = conn.execute(
            """INSERT INTO institutes
               (name, short_name, slug, status, timezone, locale, currency_code, created_at)
               VALUES (?, ?, ?, 'active', 'Asia/Kolkata', 'en-IN', 'INR', NOW())""",
            (f"Phase 1 Institute {TOKEN}", f"P1 {TOKEN}", TENANT_SLUG),
        ).lastrowid
        conn.execute(
            """INSERT INTO institute_domains
               (institute_id, hostname, domain_type, is_primary, status, verified_at, created_at)
               VALUES (?, ?, 'platform', 1, 'active', NOW(), NOW())""",
            (institute_id, TENANT_HOST),
        )
        conn.execute(
            """INSERT INTO institute_branding
               (institute_id, display_name, short_name, created_at)
               VALUES (?, ?, ?, NOW())""",
            (institute_id, f"Phase 1 Institute {TOKEN}", f"P1 {TOKEN}"),
        )
        conn.execute(
            """INSERT INTO institute_settings
               (institute_id, invoice_prefix, receipt_prefix, student_prefix,
                certificate_prefix, date_format, created_at)
               VALUES (?, 'INV', 'RCP', 'STU', 'CERT', 'DD-MMM-YYYY', NOW())""",
            (institute_id,),
        )
        conn.commit()
        return institute_id
    finally:
        conn.close()


def verify_schema_and_seed():
    expected_tables = {
        "institutes", "institute_domains", "institute_branding",
        "institute_settings", "institute_integrations", "institute_memberships",
        "tenant_migration_runs", "tenant_security_audit",
    }
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE()"
        ).fetchall()
        actual = {row["TABLE_NAME"] for row in rows}
        assert expected_tables <= actual
        global_it = conn.execute("SELECT * FROM institutes WHERE id = 1").fetchone()
        assert global_it and global_it["slug"] == "global-it-education"
        domains = conn.execute(
            "SELECT hostname FROM institute_domains WHERE institute_id = 1"
        ).fetchall()
        assert {row["hostname"] for row in domains} >= {"globaliterp.com", "www.globaliterp.com"}
        membership_count = conn.execute(
            "SELECT COUNT(*) AS n FROM institute_memberships"
        ).fetchone()["n"]
        user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        assert membership_count == user_count
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM activity_logs WHERE institute_id IS NULL"
        ).fetchone()["n"] == 0
    finally:
        conn.close()
    print("phase1_schema_and_global_it_seed=OK")
    print("phase1_membership_and_log_backfill=OK")


def verify_resolution(institute_id):
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, TENANT_RESOLUTION_MODE="observe")
    clear_tenant_cache()
    client = app.test_client(use_cookies=False)

    primary = client.get("/__phase1/context", base_url="https://www.globaliterp.com")
    assert primary.status_code == 200
    assert primary.get_json() == {
        "institute_id": 1, "source": "verified_domain", "session_institute_id": None
    }
    apex = client.get("/__phase1/context", base_url="https://globaliterp.com")
    assert apex.get_json()["institute_id"] == 1
    local = client.get("/__phase1/context", base_url="http://localhost:8080")
    assert local.get_json()["institute_id"] == 1
    assert local.get_json()["source"] == "development_fallback"
    second = client.get("/__phase1/context", base_url=f"https://{TENANT_HOST}")
    assert second.get_json()["institute_id"] == institute_id
    assert second.get_json()["source"] == "verified_domain"
    unknown = client.get("/__phase1/context", base_url=f"https://{UNKNOWN_HOST}")
    assert unknown.status_code == 200
    assert unknown.get_json()["institute_id"] == 1
    assert unknown.get_json()["source"] == "compatibility_fallback"

    assert tenant_cache_key("branding", institute_id=1) != tenant_cache_key(
        "branding", institute_id=institute_id
    )
    print("phase1_verified_domain_and_local_resolution=OK")
    print("phase1_observe_mode_compatibility=OK")
    print("phase1_tenant_cache_namespace=OK")


def verify_parallel_request_isolation(institute_id):
    app.config["TENANT_RESOLUTION_MODE"] = "strict"
    clear_tenant_cache()

    def fetch(host, expected_id):
        local_client = app.test_client(use_cookies=False)
        for _ in range(10):
            response = local_client.get("/__phase1/context", base_url=f"https://{host}")
            assert response.status_code == 200
            assert response.get_json()["institute_id"] == expected_id
        return expected_id

    futures = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for _ in range(8):
            futures.append(executor.submit(fetch, "www.globaliterp.com", 1))
            futures.append(executor.submit(fetch, TENANT_HOST, institute_id))
        resolved_ids = [future.result() for future in futures]
    assert resolved_ids.count(1) == 8
    assert resolved_ids.count(institute_id) == 8
    print("phase1_parallel_request_context_isolation=OK")


def verify_session_strict_mode_and_audit(institute_id):
    app.config["TENANT_RESOLUTION_MODE"] = "observe"
    clear_tenant_cache()
    client = app.test_client()
    with client.session_transaction(base_url="https://www.globaliterp.com") as flask_session:
        flask_session["user_id"] = 1
        flask_session["role"] = "admin"
        flask_session["branch_id"] = 1
    response = client.get("/__phase1/context", base_url="https://www.globaliterp.com")
    assert response.status_code == 200
    with client.session_transaction(base_url="https://www.globaliterp.com") as flask_session:
        assert flask_session["institute_id"] == 1

    app.config["TENANT_RESOLUTION_MODE"] = "strict"
    clear_tenant_cache()
    unknown = app.test_client(use_cookies=False).get(
        "/__phase1/context", base_url=f"https://{UNKNOWN_HOST}"
    )
    assert unknown.status_code == 404
    health = app.test_client(use_cookies=False).get(
        "/healthz", base_url=f"https://{UNKNOWN_HOST}"
    )
    assert health.status_code == 200

    mismatch_client = app.test_client()
    with mismatch_client.session_transaction(base_url=f"https://{TENANT_HOST}") as flask_session:
        flask_session["user_id"] = 1
        flask_session["role"] = "admin"
        flask_session["institute_id"] = 1
    mismatch = mismatch_client.get("/__phase1/context", base_url=f"https://{TENANT_HOST}")
    assert mismatch.status_code == 403

    log_response = app.test_client(use_cookies=False).post(
        "/__phase1/log", base_url=f"https://{TENANT_HOST}"
    )
    assert log_response.status_code == 200
    assert log_response.get_json()["institute_id"] == institute_id
    conn = get_conn()
    try:
        audit = conn.execute(
            "SELECT institute_id FROM activity_logs "
            "WHERE module_name = 'tenant_foundation' AND description = ? "
            "ORDER BY id DESC LIMIT 1",
            (TOKEN,),
        ).fetchone()
        assert audit and audit["institute_id"] == institute_id
        security_events = conn.execute(
            "SELECT event_type FROM tenant_security_audit WHERE request_host IN (?, ?)",
            (UNKNOWN_HOST, TENANT_HOST),
        ).fetchall()
        event_types = {row["event_type"] for row in security_events}
        assert "unknown_tenant_host_denied" in event_types
        assert "tenant_session_mismatch_denied" in event_types
    finally:
        conn.close()
    print("phase1_session_context_compatibility=OK")
    print("phase1_strict_unknown_host_and_mismatch_denied=OK")
    print("phase1_activity_log_context=OK")
    print("phase1_security_denial_audit=OK")


def verify_company_cache_compatibility(institute_id):
    clear_company_cache()
    global_profile = get_company_profile(1)
    second_profile = get_company_profile(institute_id)
    assert global_profile["company_name"] == "Global IT Education"
    assert second_profile["company_name"] == f"Phase 1 Institute {TOKEN}"
    clear_company_cache(institute_id)
    print("phase1_company_cache_is_tenant_keyed_with_phase3_branding=OK")


def cleanup(institute_id):
    app.config["TENANT_RESOLUTION_MODE"] = "observe"
    clear_tenant_cache()
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM activity_logs WHERE module_name = 'tenant_foundation' AND description = ?",
            (TOKEN,),
        )
        conn.execute(
            "DELETE FROM tenant_security_audit WHERE request_host IN (?, ?)",
            (UNKNOWN_HOST, TENANT_HOST),
        )
        if institute_id:
            conn.execute("DELETE FROM institutes WHERE id = ?", (institute_id,))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    institute_id = None
    add_test_routes()
    try:
        verify_schema_and_seed()
        institute_id = create_second_institute()
        clear_tenant_cache()
        verify_resolution(institute_id)
        verify_parallel_request_isolation(institute_id)
        verify_session_strict_mode_and_audit(institute_id)
        verify_company_cache_compatibility(institute_id)
    finally:
        cleanup(institute_id)
    print("phase1_cleanup=OK")
    print("phase1_tenant_foundation=OK")
