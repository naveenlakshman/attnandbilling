"""Regression checks for the tenant-scoped MySQL LMS progress dashboard."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "lms_admin" / "routes.py").read_text(encoding="utf-8")

START = ROUTES.index("def progress_dashboard():")
END = ROUTES.index("\n@lms_admin_bp.route('/student/<int:student_id>/progress'", START)
SOURCE = ROUTES[START:END]


def require(fragment: str, message: str) -> None:
    if fragment not in SOURCE:
        raise AssertionError(message)


require(
    ") AS progress_activity",
    "The UNION-derived last-activity table must have a MySQL-compatible alias.",
)
require(
    "s.institute_id = ?",
    "Student progress rows must be restricted to the current institute.",
)
require(
    "lp.institute_id = ?",
    "Programs on the progress dashboard must be restricted to the current institute.",
)
require(
    "inv.institute_id = s.institute_id",
    "Invoice-derived LMS enrollment must not cross institute boundaries.",
)
require(
    "WHERE is_active = 1 AND institute_id = ?",
    "The branch filter must only list branches belonging to the current institute.",
)

print("LMS progress dashboard MySQL and tenant-isolation regression checks passed.")
