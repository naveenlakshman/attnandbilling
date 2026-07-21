"""Phase 2 MySQL/Flask authorization regression suite."""

import time

import test_assignment_phase0_mysql as baseline
from db import get_conn


def add_security_actors(fixtures):
    conn = get_conn()
    try:
        other_branch = baseline.insert_id(
            conn,
            """INSERT INTO branches
               (branch_name, branch_code, is_active, created_at, no_of_computers)
               VALUES (?, ?, 1, ?, 0)""",
            (f"{baseline.PREFIX} Other Branch", f"Q0{baseline.TOKEN[:8]}", baseline.NOW),
        )
        actors = {}
        for label, branch_id, can_all, active in (
            ("branch_admin", fixtures["branch"], 0, 1),
            ("other_admin", other_branch, 0, 1),
            ("inactive_staff", fixtures["branch"], 0, 0),
        ):
            role = "admin" if "admin" in label else "staff"
            actors[label] = baseline.insert_id(
                conn,
                """INSERT INTO users
                   (full_name, username, password_hash, role, branch_id,
                    can_view_all_branches, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"{baseline.PREFIX} {label}", f"{baseline.PREFIX}_{label}",
                    "phase2-not-a-login-password", role, branch_id, can_all, active, baseline.NOW,
                ),
            )
        conn.commit()
        return other_branch, actors
    finally:
        conn.close()


def user_client(user_id, role, branch_id):
    return baseline.session_client({"user_id": user_id, "role": role, "branch_id": branch_id})


def run_phase2(fixtures, other_branch, actors):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    users = fixtures["users"]
    students = fixtures["students"]
    assignments = fixtures["assignments"]

    trainer_a = user_client(users["trainer_a"], "staff", fixtures["branch"])
    trainer_b = user_client(users["trainer_b"], "staff", fixtures["branch"])
    branch_admin = user_client(actors["branch_admin"], "admin", fixtures["branch"])
    other_admin = user_client(actors["other_admin"], "admin", other_branch)
    inactive_staff = user_client(actors["inactive_staff"], "staff", fixtures["branch"])
    invalid_role = user_client(users["trainer_a"], "viewer", fixtures["branch"])
    student_a = baseline.session_client({"student_id": students["student_a"], "student_login_at": int(time.time())})
    student_b = baseline.session_client({"student_id": students["student_b"], "student_login_at": int(time.time())})

    with baseline.fake_submission_storage():
        baseline.submit(student_a, assignments["lifecycle"], "trainer-a.pdf")
        baseline.submit(student_b, assignments["authorization"], "trainer-b.pdf")

    conn = get_conn()
    submission_a = conn.execute(
        "SELECT id FROM lms_assignment_submissions WHERE assignment_id = ? AND is_latest = 1",
        (assignments["lifecycle"],),
    ).fetchone()["id"]
    submission_b = conn.execute(
        "SELECT id FROM lms_assignment_submissions WHERE assignment_id = ? AND is_latest = 1",
        (assignments["authorization"],),
    ).fetchone()["id"]
    conn.close()

    # List scoping must hide another trainer's student even with a direct assignment URL.
    foreign_list = trainer_a.get(f"/lms_admin/master/assignments/{assignments['authorization']}/submissions")
    assert foreign_list.status_code == 200
    assert f"{baseline.PREFIX} student_b".encode() not in foreign_list.data

    # Every direct-ID read/mutation endpoint must enforce its own authorization.
    forbidden_requests = (
        trainer_a.get(f"/lms_admin/submission/{submission_b}/preview"),
        trainer_a.get(f"/lms_admin/master/submissions/file/{submission_b}"),
        trainer_a.post(f"/lms_admin/master/submissions/{submission_b}/accept", data={"feedback": "no"}),
        trainer_a.post(f"/lms_admin/master/submissions/{submission_b}/reject", data={"rejection_reason": "no"}),
        other_admin.get(f"/lms_admin/submission/{submission_a}/preview"),
        other_admin.get(f"/lms_admin/master/submissions/file/{submission_a}"),
        other_admin.post(f"/lms_admin/master/submissions/{submission_a}/accept"),
        inactive_staff.post(f"/lms_admin/master/submissions/{submission_a}/accept"),
    )
    assert all(response.status_code == 403 for response in forbidden_requests), [
        response.status_code for response in forbidden_requests
    ]

    conn = get_conn()
    unchanged_a = conn.execute(
        "SELECT review_status, reviewed_by FROM lms_assignment_submissions WHERE id = ?", (submission_a,)
    ).fetchone()
    unchanged_b = conn.execute(
        "SELECT review_status, reviewed_by FROM lms_assignment_submissions WHERE id = ?", (submission_b,)
    ).fetchone()
    conn.close()
    assert unchanged_a["review_status"] == "submitted" and unchanged_a["reviewed_by"] is None
    assert unchanged_b["review_status"] == "submitted" and unchanged_b["reviewed_by"] is None

    # Invalid internal roles cannot enter assignment management at all.
    denied_management = invalid_role.get("/lms_admin/master/assignments")
    assert denied_management.status_code == 302

    # A branch-scoped administrator can review submissions in their own branch.
    allowed_admin = branch_admin.post(
        f"/lms_admin/master/submissions/{submission_b}/accept", data={"feedback": "Authorized branch review"}
    )
    assert allowed_admin.status_code == 302
    conn = get_conn()
    reviewed_b = conn.execute(
        "SELECT review_status, reviewed_by FROM lms_assignment_submissions WHERE id = ?", (submission_b,)
    ).fetchone()
    audit_b = conn.execute(
        """SELECT action_type FROM activity_logs
           WHERE module_name = 'lms_assignment_submissions' AND record_id = ?
           ORDER BY id DESC LIMIT 1""",
        (submission_b,),
    ).fetchone()
    conn.close()
    assert reviewed_b["review_status"] == "accepted" and reviewed_b["reviewed_by"] == actors["branch_admin"]
    assert audit_b and audit_b["action_type"] == "accept"

    # The assigned trainer retains normal review access.
    allowed_trainer = trainer_a.post(
        f"/lms_admin/master/submissions/{submission_a}/reject",
        data={"rejection_reason": "Authorized trainer review", "feedback": "Please revise"},
    )
    assert allowed_trainer.status_code == 302
    conn = get_conn()
    audit_a = conn.execute(
        """SELECT action_type FROM activity_logs
           WHERE module_name = 'lms_assignment_submissions' AND record_id = ?
           ORDER BY id DESC LIMIT 1""",
        (submission_a,),
    ).fetchone()
    conn.close()
    assert audit_a and audit_a["action_type"] == "reject"

    # A branch-limited admin from another branch must not see fixture assignments in the overview.
    other_overview = other_admin.get("/lms_admin/master/assignments")
    assert other_overview.status_code == 200
    assert f"{baseline.PREFIX} lifecycle".encode() not in other_overview.data

    # Assigned staff can reach preview/download; missing mocked files may redirect/404, never 403.
    own_preview = trainer_b.get(f"/lms_admin/submission/{submission_b}/preview")
    own_download = trainer_b.get(f"/lms_admin/master/submissions/file/{submission_b}")
    assert own_preview.status_code != 403
    assert own_download.status_code != 403

    print("phase2_role_gate=OK")
    print("phase2_cross_trainer_direct_id_denied=OK")
    print("phase2_branch_admin_scope=OK")
    print("phase2_inactive_user_denied=OK")
    print("phase2_authorized_admin_and_trainer=OK")
    print("phase2_review_audit_log=OK")


def cleanup_extra(other_branch):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM users WHERE username LIKE ?", (f"{baseline.PREFIX}%",))
        conn.execute("DELETE FROM branches WHERE id = ?", (other_branch,))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    fixtures = None
    other_branch = None
    try:
        fixtures = baseline.create_fixtures()
        other_branch, actors = add_security_actors(fixtures)
        run_phase2(fixtures, other_branch, actors)
    finally:
        # Submission review rows reference test users, so base cleanup removes
        # submissions first; the extra actors can then be deleted safely.
        baseline.cleanup()
        if other_branch is not None:
            cleanup_extra(other_branch)
    print("phase2_cleanup=OK")
    print("phase2_authorization=OK")
