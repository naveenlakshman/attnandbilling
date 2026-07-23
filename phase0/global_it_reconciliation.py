"""Read-only Global IT baseline metrics for the multi-institute migration."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from db import get_conn


REGISTRY_PATH = Path(__file__).with_name("table_ownership_registry.json")

METRIC_QUERIES = {
    "active_branches": "SELECT COUNT(*) AS value FROM branches WHERE is_active = 1",
    "active_users": "SELECT COUNT(*) AS value FROM users WHERE is_active = 1",
    "active_students": "SELECT COUNT(*) AS value FROM students WHERE status = 'active'",
    "active_leads": "SELECT COUNT(*) AS value FROM leads WHERE status = 'active' AND is_deleted = 0",
    "active_batches": "SELECT COUNT(*) AS value FROM batches WHERE status = 'active'",
    "invoice_total": "SELECT COALESCE(SUM(total_amount), 0) AS value FROM invoices",
    "receipt_total": "SELECT COALESCE(SUM(amount_received), 0) AS value FROM receipts",
    "expense_total": "SELECT COALESCE(SUM(amount), 0) AS value FROM expenses",
    "bad_debt_total": "SELECT COALESCE(SUM(amount_written_off), 0) AS value FROM bad_debt_writeoffs",
    "attendance_records": "SELECT COUNT(*) AS value FROM attendance_records",
    "published_lms_programs": "SELECT COUNT(*) AS value FROM lms_programs WHERE is_published = 1 AND is_active = 1 AND is_deleted = 0",
    "lms_master_chapters": "SELECT COUNT(*) AS value FROM lms_master_chapters",
    "lms_master_topics": "SELECT COUNT(*) AS value FROM lms_master_topics",
    "lms_assignments": "SELECT COUNT(*) AS value FROM lms_assignments",
    "lms_submissions": "SELECT COUNT(*) AS value FROM lms_assignment_submissions",
    "certificates": "SELECT COUNT(*) AS value FROM certificates",
}


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def collect_baseline():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    tables = sorted(registry["tables"])
    conn = get_conn()
    try:
        table_counts = {}
        for table in tables:
            # Table names come only from the version-controlled allowlist above.
            row = conn.execute(f"SELECT COUNT(*) AS value FROM `{table}`").fetchone()
            table_counts[table] = int(row["value"] or 0)

        metrics = {}
        for name, query in METRIC_QUERIES.items():
            row = conn.execute(query).fetchone()
            metrics[name] = _json_value(row["value"])

        schema_row = conn.execute(
            "SELECT COUNT(*) AS value FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'institute_id'"
        ).fetchone()
        institute_table = conn.execute(
            "SELECT COUNT(*) AS value FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'institutes'"
        ).fetchone()
    finally:
        conn.close()

    result = {
        "baseline_version": 1,
        "scope": "Current single-institute Global IT dataset",
        "privacy": "Aggregate values only; no PII or credentials",
        "schema": {
            "registered_table_count": len(tables),
            "tables_with_institute_id": int(schema_row["value"] or 0),
            "institutes_table_exists": bool(institute_table["value"]),
        },
        "metrics": metrics,
        "table_counts": table_counts,
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=_json_value)
    result["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result


if __name__ == "__main__":
    print(json.dumps(collect_baseline(), indent=2, sort_keys=True, default=_json_value))
