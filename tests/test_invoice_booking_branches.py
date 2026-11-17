"""Tests for tenant-scoped invoice booking branches."""

from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from services.invoice_form import load_booking_branches, require_booking_branch


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((" ".join(sql.split()), params))
        return Result(self.rows)


def test_load_booking_branches_is_active_and_tenant_scoped():
    conn = Connection([{"id": 2, "branch_name": "Hoskote"}])

    assert load_booking_branches(conn, 7) == [{"id": 2, "branch_name": "Hoskote"}]
    sql, params = conn.calls[0]
    assert "institute_id = ?" in sql
    assert "is_active = 1" in sql
    assert params == (7,)


def test_require_booking_branch_rechecks_tenant_and_active_state():
    conn = Connection([{"id": 2}])

    assert require_booking_branch(conn, 7, "2") == 2
    sql, params = conn.calls[0]
    assert "id = ? AND institute_id = ? AND is_active = 1" in sql
    assert params == (2, 7)


def test_require_booking_branch_rejects_missing_or_invalid_values():
    for value in (None, "", "abc"):
        try:
            require_booking_branch(Connection([]), 7, value)
        except ValueError as exc:
            assert "Choose an invoice booking branch" in str(exc)
        else:
            raise AssertionError(f"Expected invalid branch value to fail: {value!r}")


def test_require_booking_branch_rejects_other_tenant_or_inactive_branch():
    try:
        require_booking_branch(Connection([]), 7, "2")
    except ValueError as exc:
        assert "active invoice booking branch" in str(exc)
    else:
        raise AssertionError("Expected an unavailable branch to fail")


if __name__ == "__main__":
    test_load_booking_branches_is_active_and_tenant_scoped()
    test_require_booking_branch_rechecks_tenant_and_active_state()
    test_require_booking_branch_rejects_missing_or_invalid_values()
    test_require_booking_branch_rejects_other_tenant_or_inactive_branch()
