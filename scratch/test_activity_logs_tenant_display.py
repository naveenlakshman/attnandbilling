"""Regression checks for tenant-facing billing activity logs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run():
    routes = (ROOT / "modules" / "billing" / "routes.py").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "billing" / "activity_logs.html").read_text(
        encoding="utf-8"
    )

    for tenant_filter in (
        "writeoffs.institute_id = ?",
        "invoices.institute_id = ?",
        "receipts.institute_id = ?",
        "expenses.institute_id = ?",
        "students.institute_id = ?",
    ):
        assert tenant_filter in routes

    assert "AS record_reference" in routes
    assert "Record ID" not in template
    assert "{{ log.id }}" not in template
    assert "{{ log.record_id" not in template
    assert "log.record_reference" in template
    assert "format_ist_datetime('%d-%b-%Y %I:%M %p')" in template
    assert "Date & Time (IST)" in template
    print("Tenant activity-log display checks passed.")


if __name__ == "__main__":
    run()
