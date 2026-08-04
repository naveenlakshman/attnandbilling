"""Regression guardrails for the tenant-owned leads pipeline workflow."""

from pathlib import Path


ROUTES = Path("modules/leads/routes.py").read_text(encoding="utf-8")
HELPERS = Path("modules/leads/helpers.py").read_text(encoding="utf-8")
SERVICES = Path("modules/leads/services.py").read_text(encoding="utf-8")


def test_pipeline_data_and_counselors_are_tenant_scoped():
    assert "AND l.institute_id = ?" in ROUTES
    assert "WHERE institute_id = ? AND is_active = 1" in ROUTES
    assert 'allowed_user_ids = {str(user["id"]) for user in all_users}' in ROUTES
    assert 'selected_user_id = ""' in ROUTES
    assert "u.institute_id = l.institute_id" in ROUTES


def test_reassignment_rejects_foreign_tenant_users_and_leads():
    assert "WHERE id = ? AND institute_id = ?" in ROUTES
    assert "WHERE id = ? AND institute_id = ?\n        \"\"\", (assigned_to_id, current_inst)" in ROUTES
    assert ROUTES.count("WHERE id = ? AND institute_id = ?") >= 3


def test_lead_access_and_stage_updates_scope_in_sql():
    assert "SELECT * FROM leads WHERE id = ? AND institute_id = ?" in HELPERS
    assert "WHERE id = ? AND institute_id = ? AND is_deleted = 0" in HELPERS
    assert "FROM leads WHERE id = ? AND institute_id = ?" in SERVICES
    assert "WHERE id = ? AND institute_id = ?" in SERVICES


def test_activity_actor_lookup_is_tenant_scoped():
    assert "SELECT branch_id FROM users WHERE id = ? AND institute_id = ?" in SERVICES
