"""Static regression guardrails for tenant-owned asset management."""

from pathlib import Path

from services.document_numbers import DOCUMENT_TYPES


SOURCE = Path("modules/assets/routes.py").read_text(encoding="utf-8")


def test_asset_numbering_is_supported_by_tenant_sequence_service():
    assert "asset" in DOCUMENT_TYPES
    assert 'allocate_document_number(\n                cur, institute_id, "asset", "AST"' in SOURCE


def test_asset_and_child_writes_include_institute_id():
    assert "INSERT INTO assets (\n                    institute_id," in SOURCE
    assert SOURCE.count("INSERT INTO asset_logs (\n                    institute_id,") >= 4
    assert "INSERT INTO asset_allocation (\n                    institute_id," in SOURCE


def test_asset_routes_resolve_current_institute_and_scope_branches():
    assert SOURCE.count("get_current_institute_id(default=1)") >= 6
    assert "WHERE institute_id = ? AND is_active = 1" in SOURCE
    assert "WHERE assets.id = ? AND assets.institute_id = ?" in SOURCE

