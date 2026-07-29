"""Regression checks for the tenant-scoped MySQL LMS progress dashboard."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "lms_admin" / "routes.py").read_text(encoding="utf-8")

START = ROUTES.index("def progress_dashboard():")
END = ROUTES.index("\n@lms_admin_bp.route('/student/<int:student_id>/progress'", START)
SOURCE = ROUTES[START:END]

DETAIL_START = ROUTES.index("def view_student_progress(student_id):")
DETAIL_END = ROUTES.index(
    "\n@lms_admin_bp.route('/batch/<int:batch_id>/progress'", DETAIL_START
)
DETAIL_SOURCE = ROUTES[DETAIL_START:DETAIL_END]


def require(fragment: str, message: str) -> None:
    if fragment not in SOURCE:
        raise AssertionError(message)


require(
    ") AS legacy_progress",
    "Legacy progress aggregation must use a MySQL-compatible derived-table alias.",
)
require(
    ") AS master_progress",
    "Master progress aggregation must use a MySQL-compatible derived-table alias.",
)
if "SELECT MAX(last_act) FROM (" in SOURCE:
    raise AssertionError(
        "Last activity must not use a correlated UNION-derived table; MySQL rejects it."
    )
require(
    "legacy_progress.student_id = s.id",
    "Legacy activity aggregation must join back to the current student.",
)
require(
    "master_progress.program_id = lp.id",
    "Master activity aggregation must join back to the current program.",
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

if ") AS recent_activity" not in DETAIL_SOURCE:
    raise AssertionError(
        "Student progress recent activity UNION must have a MySQL derived-table alias."
    )
if "WHERE id = ? AND institute_id = ?" not in DETAIL_SOURCE:
    raise AssertionError(
        "Student progress detail must restrict the requested student to the current institute."
    )
if '"lp.institute_id = ?"' not in DETAIL_SOURCE:
    raise AssertionError(
        "Student progress detail must restrict programs to the current institute."
    )

print("LMS progress dashboard/detail MySQL and tenant-isolation regression checks passed.")
