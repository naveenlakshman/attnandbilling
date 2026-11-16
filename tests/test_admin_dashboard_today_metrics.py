from pathlib import Path

from modules.core.routes import _admin_dashboard_today_metrics


class _Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return next(self.rows)


def test_today_metrics_are_date_and_institute_scoped():
    cur = _Cursor(
        [
            {"cnt": 3, "total": 7250},
            {"cnt": 2},
            {"cnt": 4},
        ]
    )

    metrics = _admin_dashboard_today_metrics(cur, 9, "2026-11-16")

    assert metrics == {
        "receipt_count": 3,
        "receipt_total": 7250.0,
        "student_count": 2,
        "lead_count": 4,
    }
    assert len(cur.calls) == 3
    for sql, params in cur.calls:
        assert "institute_id = ?" in sql
        assert params == [9, "2026-11-16"]
    assert "parse_date(r.receipt_date) = ?" in cur.calls[0][0]
    assert "parse_date(joined_date) = ?" in cur.calls[1][0]
    assert "date(created_at) = ?" in cur.calls[2][0]
    assert "is_deleted = 0" in cur.calls[2][0]


def test_admin_dashboard_shows_today_status_inside_all_four_cards():
    template = (
        Path(__file__).parents[1] / "templates" / "core" / "dashboard_new.html"
    ).read_text(encoding="utf-8")

    assert 'aria-label="Today\'s receipts"' in template
    assert "today_receipt_total" in template
    assert "today_receipt_count" in template
    assert 'aria-label="Today\'s new students"' in template
    assert "today_new_students" in template
    assert 'aria-label="Today\'s new leads"' in template
    assert "today_new_leads" in template
    assert 'aria-label="Today\'s due payments"' in template
    assert "total_today_due" in template
    assert "todays_dues|length" in template
