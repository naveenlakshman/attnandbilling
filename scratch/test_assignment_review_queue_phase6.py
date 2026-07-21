"""Phase 6 centralized assignment review queue regressions."""

from urllib.parse import quote_plus

import test_assignment_phase0_mysql as baseline
import test_assignment_authorization_phase2 as phase2
import test_assignment_pagination_phase5 as phase5
from db import get_conn


def run_phase6(fixtures, other_branch, actors):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    users = fixtures["users"]
    admin = baseline.session_client({"user_id": users["admin"], "role": "admin", "branch_id": fixtures["branch"]})
    trainer_a = baseline.session_client({"user_id": users["trainer_a"], "role": "staff", "branch_id": fixtures["branch"]})
    trainer_b = baseline.session_client({"user_id": users["trainer_b"], "role": "staff", "branch_id": fixtures["branch"]})
    other_admin = baseline.session_client({"user_id": actors["other_admin"], "role": "admin", "branch_id": other_branch})
    invalid_role = baseline.session_client({"user_id": users["trainer_a"], "role": "viewer", "branch_id": fixtures["branch"]})

    default_queue = admin.get(f"/lms_admin/master/reviews?program_id={fixtures['program']}")
    assert default_queue.status_code == 200
    assert b"Assignment Review Queue" in default_queue.data
    assert b"20" in default_queue.data
    assert b"Page Student 000" in default_queue.data
    assert b"Page Student 001" not in default_queue.data
    assert b"Preview" in default_queue.data and b"Review" in default_queue.data
    assert b"Pending by trainer" in default_queue.data
    assert b"Pending by batch" in default_queue.data
    assert b"Pending by program" in default_queue.data
    assert f"{baseline.PREFIX} trainer_a".encode() in default_queue.data
    assert f"{baseline.PREFIX} batch_a".encode() in default_queue.data
    assert f"{baseline.PREFIX} Program".encode() in default_queue.data

    all_queue = admin.get(
        f"/lms_admin/master/reviews?program_id={fixtures['program']}&status_filter=all&per_page=25"
    )
    assert all_queue.status_code == 200
    assert b"Showing 1" in all_queue.data and b"25 of 60" in all_queue.data
    assert b"Page 1 of 3" in all_queue.data

    page_two = admin.get(
        f"/lms_admin/master/reviews?program_id={fixtures['program']}&status_filter=all&per_page=25&page=2"
    )
    assert page_two.status_code == 200
    assert b"Showing 26" in page_two.data and b"50 of 60" in page_two.data

    reviewed = admin.get(
        f"/lms_admin/master/reviews?program_id={fixtures['program']}&status_filter=reviewed&per_page=50"
    )
    assert reviewed.status_code == 200
    assert b"40 of 40" in reviewed.data

    searched = admin.get(
        f"/lms_admin/master/reviews?program_id={fixtures['program']}&q={quote_plus(baseline.PREFIX + ' Page Student 042')}"
    )
    assert searched.status_code == 200
    assert b"Page Student 042" in searched.data and b"1 of 1" in searched.data

    trainer_queue = trainer_a.get("/lms_admin/master/reviews")
    assert trainer_queue.status_code == 200
    assert b"Page Student 000" in trainer_queue.data
    assert f"trainer_id={users['trainer_a']}".encode() in trainer_queue.data

    trainer_b_queue = trainer_b.get("/lms_admin/master/reviews?status_filter=all")
    assert trainer_b_queue.status_code == 200
    assert b"Page Student 000" not in trainer_b_queue.data

    other_branch_queue = other_admin.get("/lms_admin/master/reviews?status_filter=all")
    assert other_branch_queue.status_code == 200
    assert b"Page Student 000" not in other_branch_queue.data

    denied = invalid_role.get("/lms_admin/master/reviews")
    assert denied.status_code == 302

    dashboard = admin.get(f"/lms_admin/master/assignments?program_id={fixtures['program']}")
    assert dashboard.status_code == 200
    assert b"/lms_admin/master/reviews" in dashboard.data
    assert b"status_filter=submitted" in dashboard.data

    unsafe = admin.get(
        "/lms_admin/master/reviews?status_filter=unknown&sort=submitted%20DESC%3BDROP%20TABLE%20users&direction=no&per_page=999&page=-2"
    )
    assert unsafe.status_code == 200
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] > 0
    conn.close()

    print("phase6_pending_oldest_default=OK pending=20")
    print("phase6_all_reviewed_pagination=OK all=60 reviewed=40")
    print("phase6_search_program_filters=OK")
    print("phase6_trainer_branch_authorization=OK")
    print("phase6_dashboard_and_navigation_links=OK")
    print("phase6_pending_workload_breakdowns=OK")
    print("phase6_invalid_parameters_safe=OK")


if __name__ == "__main__":
    other_branch = None
    try:
        phase6_fixtures = baseline.create_fixtures()
        phase5.seed_volume(phase6_fixtures)
        other_branch, phase6_actors = phase2.add_security_actors(phase6_fixtures)
        run_phase6(phase6_fixtures, other_branch, phase6_actors)
    finally:
        baseline.cleanup()
        if other_branch is not None:
            phase2.cleanup_extra(other_branch)
    print("phase6_cleanup=OK")
    print("phase6_review_queue=OK")
