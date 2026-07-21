"""Phase 4 clickable assignment/review indicator regressions."""

import test_assignment_phase0_mysql as baseline
import test_assignment_counts_phase3 as phase3
from db import get_conn


def run_phase4(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    assignment_id = fixtures["assignments"]["lifecycle"]
    empty_assignment_title = f"{baseline.PREFIX} authorization"
    students = fixtures["students"]
    users = fixtures["users"]

    conn = get_conn()
    try:
        phase3.add_attempt(conn, assignment_id, students["student_a"], "a-pending", "submitted", "submitted", 1)
        phase3.add_attempt(conn, assignment_id, students["student_b"], "b-accepted", "accepted", "reviewed", 1)
        conn.commit()
    finally:
        conn.close()

    admin = baseline.session_client({
        "user_id": users["admin"], "role": "admin", "branch_id": fixtures["branch"]
    })

    overview = admin.get(f"/lms_admin/master/assignments?program_id={fixtures['program']}")
    assert overview.status_code == 200
    assert b'/lms_admin/master/reviews' in overview.data
    assert b'status_filter=all' in overview.data
    assert b'status_filter=reviewed' in overview.data
    assert b'status_filter=submitted' in overview.data
    assert b'status_filter=all' in overview.data
    assert b'status_filter=reviewed' in overview.data
    assert b'status_filter=submitted' in overview.data
    assert b'aria-label="View all 2 submissions' in overview.data
    assert b'aria-label="View 1 reviewed submissions' in overview.data
    assert b'aria-label="Review 1 pending submissions' in overview.data

    pending = admin.get(
        f"/lms_admin/master/assignments?program_id={fixtures['program']}&review_filter=pending"
    )
    assert pending.status_code == 200
    assert f"{baseline.PREFIX} lifecycle".encode() in pending.data
    assert empty_assignment_title.encode() not in pending.data
    assert b'class="stat-link active"' in pending.data
    assert b"1 of 3" in pending.data

    reviewed = admin.get(
        f"/lms_admin/master/assignments?program_id={fixtures['program']}&review_filter=reviewed"
    )
    assert reviewed.status_code == 200
    assert f"{baseline.PREFIX} lifecycle".encode() in reviewed.data
    assert empty_assignment_title.encode() not in reviewed.data

    trainer_pending = admin.get(
        f"/lms_admin/master/assignments?program_id={fixtures['program']}&trainer_id={users['trainer_a']}&review_filter=pending"
    )
    assert trainer_pending.status_code == 200
    assert f"trainer_id={users['trainer_a']}".encode() in trainer_pending.data
    assert b'name="review_filter" value="pending"' in trainer_pending.data

    invalid = admin.get(
        f"/lms_admin/master/assignments?program_id={fixtures['program']}&review_filter=not-valid"
    )
    assert invalid.status_code == 200
    assert b'class="stat-link active"' in invalid.data
    assert b'name="review_filter" value="not-valid"' not in invalid.data

    reviewed_submissions = admin.get(
        f"/lms_admin/master/assignments/{assignment_id}/submissions?status_filter=reviewed"
    )
    assert reviewed_submissions.status_code == 200
    assert b">\n        Reviewed 1\n      </a>" in reviewed_submissions.data
    assert f"{baseline.PREFIX} student_b".encode() in reviewed_submissions.data
    assert f"{baseline.PREFIX} student_a".encode() not in reviewed_submissions.data

    conn = get_conn()
    pending_id = conn.execute(
        """SELECT id FROM lms_assignment_submissions
           WHERE assignment_id = ? AND student_id = ? AND is_latest = 1""",
        (assignment_id, students["student_a"]),
    ).fetchone()["id"]
    conn.close()
    accepted = admin.post(
        f"/lms_admin/master/submissions/{pending_id}/accept",
        data={"return_status_filter": "reviewed", "feedback": "Phase 4"},
    )
    assert accepted.status_code == 302
    assert "status_filter=reviewed" in accepted.headers["Location"]

    print("phase4_dashboard_card_links=OK")
    print("phase4_assignment_count_links=OK")
    print("phase4_filter_context=OK")
    print("phase4_reviewed_combined_filter=OK")
    print("phase4_review_redirect_filter=OK")


if __name__ == "__main__":
    try:
        phase4_fixtures = baseline.create_fixtures()
        run_phase4(phase4_fixtures)
    finally:
        baseline.cleanup()
    print("phase4_cleanup=OK")
    print("phase4_indicators=OK")
