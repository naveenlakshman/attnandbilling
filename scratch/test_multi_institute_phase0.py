"""Phase 0 characterization harness for the current single-institute application.

Known gaps are asserted intentionally. A passing Phase 0 run proves the harness can
detect the current unsafe assumptions; it does not claim multi-tenant isolation.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import app
from db import get_conn
from services.storage import map_local_path_to_gcs_path


PHASE0_DIR = Path(os.environ.get("PHASE0_DIR", Path(__file__).with_name("phase0")))
if not PHASE0_DIR.exists():
    PHASE0_DIR = Path("/tmp/phase0")


def load_json(name):
    return json.loads((PHASE0_DIR / name).read_text(encoding="utf-8"))


def classify_endpoint(endpoint, registry):
    exact = registry["exact_endpoint_rules"].get(endpoint)
    if exact:
        return exact
    blueprint = endpoint.split(".", 1)[0] if "." in endpoint else endpoint
    return registry["blueprint_rules"].get(blueprint)


def dotted_value(document, dotted_path):
    value = document
    for part in dotted_path.split("."):
        value = value[part]
    return value


def validate_registries():
    ownership = load_json("table_ownership_registry.json")
    route_scopes = load_json("route_scope_rules.json")
    fixture = load_json("two_institute_fixture.json")

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        ).fetchall()
    finally:
        conn.close()
    actual_tables = {row["TABLE_NAME"] for row in rows}
    registered_tables = set(ownership["tables"])
    assert actual_tables == registered_tables, {
        "missing_from_registry": sorted(actual_tables - registered_tables),
        "stale_registry_entries": sorted(registered_tables - actual_tables),
    }

    unclassified = []
    for rule in app.url_map.iter_rules():
        if not classify_endpoint(rule.endpoint, route_scopes):
            unclassified.append((rule.rule, rule.endpoint))
    assert not unclassified, {"unclassified_routes": sorted(unclassified)}

    left, right = fixture["institutes"]
    for path in fixture["required_overlaps"]:
        assert dotted_value(left, path) == dotted_value(right, path), path
    assert left["slug"] != right["slug"] and left["host"] != right["host"]

    print(f"phase0_table_registry={len(registered_tables)}_TABLES_OK")
    print(f"phase0_route_registry={len(list(app.url_map.iter_rules()))}_ROUTES_OK")
    print("phase0_overlapping_fixture=OK")


def characterize_known_gaps():
    token = uuid.uuid4().hex[:10]
    prefix = f"__tenant_phase0_{token}__"
    branch_a = branch_b = admin_a = admin_b = student_a = student_b = None
    conn = get_conn()
    try:
        institute_table = conn.execute(
            "SELECT COUNT(*) AS n FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'institutes'"
        ).fetchone()["n"]
        tenant_columns = conn.execute(
            "SELECT TABLE_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'institute_id'"
        ).fetchall()
        tenant_column_tables = {row["TABLE_NAME"] for row in tenant_columns}
        if institute_table == 0:
            assert tenant_column_tables == set()
            print("KNOWN_GAP_DETECTED=no_institutes_table_or_tenant_columns")
        else:
            assert institute_table == 1
            assert tenant_column_tables == {
                "activity_logs", "institute_domains", "institute_branding",
                "institute_settings", "institute_integrations",
                "institute_memberships", "tenant_migration_runs",
                "tenant_security_audit",
            }
            print("PHASE1_FOUNDATION_DETECTED=institutes_and_activity_context")

        now = "2026-07-22T00:00:00"
        branch_a = conn.execute(
            "INSERT INTO branches (branch_name, branch_code, is_active, created_at, no_of_computers) "
            "VALUES (?, ?, 1, ?, 0)",
            (f"{prefix} Academy A", f"A{token}", now),
        ).lastrowid
        branch_b = conn.execute(
            "INSERT INTO branches (branch_name, branch_code, is_active, created_at, no_of_computers) "
            "VALUES (?, ?, 1, ?, 0)",
            (f"{prefix} Academy B", f"B{token}", now),
        ).lastrowid

        # Duplicate credentials/codes can exist in the schema, while authentication
        # performs a global lookup with no domain/institute discriminator.
        shared_username = f"{prefix}_admin"
        for branch_id, password in ((branch_a, "Phase0-A!1"), (branch_b, "Phase0-B!1")):
            cursor = conn.execute(
                "INSERT INTO users (full_name, username, password_hash, role, branch_id, "
                "can_view_all_branches, is_active, created_at) VALUES (?, ?, ?, 'admin', ?, 1, 1, ?)",
                (f"{prefix} Admin", shared_username, generate_password_hash(password), branch_id, now),
            )
            if admin_a is None:
                admin_a = cursor.lastrowid
            else:
                admin_b = cursor.lastrowid

        shared_student_code = f"P0{token}".upper()
        for branch_id, phone in ((branch_a, "9000000001"), (branch_b, "9000000002")):
            cursor = conn.execute(
                "INSERT INTO students (student_code, full_name, phone, joined_date, status, branch_id, "
                "password_hash, portal_enabled, created_at) VALUES (?, ?, ?, ?, 'active', ?, ?, 1, ?)",
                (shared_student_code, f"{prefix} Student", phone, "2026-07-22", branch_id,
                 generate_password_hash(shared_student_code), now),
            )
            if student_a is None:
                student_a = cursor.lastrowid
            else:
                student_b = cursor.lastrowid
        conn.commit()

        assert conn.execute("SELECT COUNT(*) AS n FROM users WHERE username = ?", (shared_username,)).fetchone()["n"] == 2
        assert conn.execute("SELECT COUNT(*) AS n FROM students WHERE student_code = ?", (shared_student_code,)).fetchone()["n"] == 2
    finally:
        conn.close()

    try:
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = admin_a
            session["role"] = "admin"
            session["branch_id"] = branch_a
            session["can_view_all_branches"] = 1
        response = client.get("/branches")
        assert response.status_code == 200
        assert f"{prefix} Academy A".encode() in response.data
        assert f"{prefix} Academy B".encode() in response.data

        fixture = load_json("two_institute_fixture.json")
        paths = [
            map_local_path_to_gcs_path(f"uploads/student_documents/{row['storage_filename']}")
            for row in fixture["institutes"]
        ]
        assert paths[0] == paths[1] == "documents/identity-document.pdf"

        print("KNOWN_GAP_DETECTED=global_duplicate_staff_username_namespace")
        print("KNOWN_GAP_DETECTED=global_duplicate_student_code_namespace")
        print("KNOWN_GAP_DETECTED=admin_can_list_other_logical_institute_branch")
        print("KNOWN_GAP_DETECTED=storage_keys_have_no_institute_prefix")
    finally:
        cleanup_ids = {
            "users": [admin_a, admin_b],
            "students": [student_a, student_b],
            "branches": [branch_a, branch_b],
        }
        conn = get_conn()
        try:
            for table in ("users", "students", "branches"):
                ids = [value for value in cleanup_ids[table] if value is not None]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(ids))
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    validate_registries()
    characterize_known_gaps()
    print("phase0_isolation_characterization=OK")
    print("phase0_cleanup=OK")
