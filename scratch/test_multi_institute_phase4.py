"""Phase 4 CRM and Student Identity multi-tenant isolation tests."""

import sys
import os
os.environ["DB_TYPE"] = "sqlite"
os.environ["STORAGE_PROVIDER"] = "local"
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import uuid
from io import BytesIO
from werkzeug.security import generate_password_hash

from app import create_app
from db import get_conn, clear_company_cache
from services.storage import get_storage_service
from services.tenant_context import clear_tenant_cache


TOKEN = uuid.uuid4().hex[:10]
HOST_A = f"phase4-a-{TOKEN}.localhost"
HOST_B = f"phase4-b-{TOKEN}.localhost"


def create_test_institute(label, host):
    conn = get_conn()
    try:
        now = "2026-07-23 00:00:00"
        inst_id = conn.execute(
            """INSERT INTO institutes
               (name, short_name, slug, status, timezone, locale, currency_code, created_at, updated_at)
               VALUES (?, ?, ?, 'active', 'Asia/Kolkata', 'en-IN', 'INR', ?, ?)""",
            (f"Phase4 {label} {TOKEN}", f"P4{label}", f"phase4-{label.lower()}-{TOKEN}", now, now),
        ).lastrowid

        conn.execute(
            """INSERT INTO institute_domains
               (institute_id, hostname, domain_type, is_primary, status, verified_at, created_at, updated_at)
               VALUES (?, ?, 'platform', 1, 'active', ?, ?, ?)""",
            (inst_id, host, now, now, now),
        )

        conn.execute(
            """INSERT INTO institute_branding
               (institute_id, display_name, short_name, tagline, primary_color, secondary_color, created_at, updated_at)
               VALUES (?, ?, ?, ?, '#112233', '#445566', ?, ?)""",
            (inst_id, f"Phase4 {label} Brand", f"P4{label}", f"{label} Institute", now, now),
        )

        branch_id = conn.execute(
            """INSERT INTO branches
               (institute_id, branch_name, branch_code, is_active, no_of_computers, created_at)
               VALUES (?, ?, 'MAIN', 1, 10, ?)""",
            (inst_id, f"{label} Main Branch", now),
        ).lastrowid

        user_id = conn.execute(
            """INSERT INTO users
               (institute_id, full_name, username, password_hash, role, branch_id, can_view_all_branches, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'admin', ?, 1, 1, ?, ?)""",
            (inst_id, f"{label} Admin", f"admin_{label.lower()}_{TOKEN}", generate_password_hash("pass123"), branch_id, now, now),
        ).lastrowid

        conn.execute(
            """INSERT INTO institute_memberships
               (institute_id, user_id, membership_role, is_active, created_at, updated_at)
               VALUES (?, ?, 'institute_admin', 1, ?, ?)""",
            (inst_id, user_id, now, now),
        )

        conn.commit()
        return inst_id, branch_id, user_id
    finally:
        conn.close()


def cleanup_test_data(inst_a_id, inst_b_id):
    conn = get_conn()
    try:
        inst_ids = (inst_a_id, inst_b_id)
        for tbl in ["student_uploaded_documents", "student_profile_update_requests", "student_notes", "followups", "leads", "students", "institute_memberships", "users", "branches", "institute_branding", "institute_domains", "institutes"]:
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE institute_id IN (?, ?)", inst_ids)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


def main():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    inst_a_id, branch_a_id, user_a_id = create_test_institute("A", HOST_A)
    inst_b_id, branch_b_id, user_b_id = create_test_institute("B", HOST_B)

    print(f"[*] Created Institute A (ID: {inst_a_id}, Host: {HOST_A})")
    print(f"[*] Created Institute B (ID: {inst_b_id}, Host: {HOST_B})")

    try:
        conn = get_conn()
        now = "2026-07-23 00:00:00"

        # 1. Test overlapping student_code (STU001) in both institutes
        student_a_id = conn.execute(
            """INSERT INTO students
               (institute_id, student_code, full_name, phone, joined_date, status, branch_id, password_hash, portal_enabled, created_at, updated_at)
               VALUES (?, 'STU001', 'Alice InstA', '9876543210', '2026-07-23', 'active', ?, ?, 1, ?, ?)""",
            (inst_a_id, branch_a_id, generate_password_hash("StudentA@123"), now, now),
        ).lastrowid

        student_b_id = conn.execute(
            """INSERT INTO students
               (institute_id, student_code, full_name, phone, joined_date, status, branch_id, password_hash, portal_enabled, created_at, updated_at)
               VALUES (?, 'STU001', 'Bob InstB', '9876543210', '2026-07-23', 'active', ?, ?, 1, ?, ?)""",
            (inst_b_id, branch_b_id, generate_password_hash("StudentB@123"), now, now),
        ).lastrowid
        conn.commit()
        conn.close()

        print("[+] Test 1 PASSED: Created composite unique student_code STU001 in both institutes successfully.")

        # 2. Test student login domain binding
        with app.test_client() as client_a:
            # Login Alice on Host A
            res_a = client_a.post(
                f"http://{HOST_A}/student/login",
                data={"student_code": "STU001", "password": "StudentA@123"},
                follow_redirects=True,
            )
            assert "Invalid Student ID or password" not in res_a.get_data(as_text=True), "Alice login on Host A failed"
            print("[+] Test 2a PASSED: Student A logged in on Host A successfully.")

        with app.test_client() as client_b:
            # Attempt Alice login on Host B with Alice's password
            res_b = client_b.post(
                f"http://{HOST_B}/student/login",
                data={"student_code": "STU001", "password": "StudentA@123"},
                follow_redirects=True,
            )
            html_b = res_b.get_data(as_text=True)
            assert "Invalid Student ID or password" in html_b, "Alice login should fail on Host B"
            print("[+] Test 2b PASSED: Student A login correctly denied on Host B domain.")

        # 3. Test Lead creation and cross-tenant direct-ID access
        conn = get_conn()
        lead_a_id = conn.execute(
            """INSERT INTO leads
               (institute_id, name, phone, whatsapp, stage, status, branch_id, assigned_to_id, created_at, updated_at)
               VALUES (?, 'Lead Alpha', '9988776655', '9988776655', 'New Lead', 'active', ?, ?, ?, ?)""",
            (inst_a_id, branch_a_id, user_a_id, now, now),
        ).lastrowid

        lead_b_id = conn.execute(
            """INSERT INTO leads
               (institute_id, name, phone, whatsapp, stage, status, branch_id, assigned_to_id, created_at, updated_at)
               VALUES (?, 'Lead Beta', '9988776655', '9988776655', 'New Lead', 'active', ?, ?, ?, ?)""",
            (inst_b_id, branch_b_id, user_b_id, now, now),
        ).lastrowid
        conn.commit()
        conn.close()

        print("[+] Test 3 PASSED: Created leads with identical phone number in both institutes.")

        with app.test_client() as client:
            with client.session_transaction(base_url=f"http://{HOST_A}") as sess:
                sess["user_id"] = user_a_id
                sess["role"] = "admin"
                sess["institute_id"] = inst_a_id

            # Access Lead A
            res_lead_a = client.get(f"http://{HOST_A}/leads/{lead_a_id}")
            assert res_lead_a.status_code == 200, f"Expected 200 for Lead A on Host A, got {res_lead_a.status_code}"

            # Attempt direct access to Lead B from Host A -> should get 404/redirect
            res_lead_b_cross = client.get(f"http://{HOST_A}/leads/{lead_b_id}", follow_redirects=False)
            assert res_lead_b_cross.status_code in (302, 404), f"Expected cross-tenant denial for Lead B, got {res_lead_b_cross.status_code}"
            print("[+] Test 4 PASSED: Cross-tenant direct lead access strictly denied.")

            # Test dashboard lead list isolation
            res_list_a = client.get(f"http://{HOST_A}/leads/list")
            html_a = res_list_a.get_data(as_text=True)
            assert "Lead Alpha" in html_a, "Lead Alpha missing from Host A list"
            assert "Lead Beta" not in html_a, "Lead Beta leaked into Host A list"
            print("[+] Test 5 PASSED: Lead list query strictly isolated to current institute.")

        print("\n==================================================")
        print("ALL MULTI-INSTITUTE PHASE 4 TESTS PASSED CLEANLY!")
        print("==================================================\n")

    finally:
        cleanup_test_data(inst_a_id, inst_b_id)
        clear_tenant_cache()
        clear_company_cache()


if __name__ == "__main__":
    main()
