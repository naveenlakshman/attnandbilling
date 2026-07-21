"""Phase 3 latest-attempt assignment count regressions for MySQL/Flask."""

import test_assignment_phase0_mysql as baseline
from db import get_conn


def add_attempt(conn, assignment_id, student_id, suffix, review_status, status, is_latest):
    return baseline.insert_id(
        conn,
        """INSERT INTO lms_assignment_submissions
           (assignment_id, student_id, file_path, original_filename, status,
            review_status, submitted_at, updated_at, is_latest)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assignment_id,
            student_id,
            f"documents/{baseline.PREFIX}-{suffix}.pdf",
            f"{suffix}.pdf",
            status,
            review_status,
            baseline.NOW,
            baseline.NOW,
            is_latest,
        ),
    )


def run_phase3(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    assignment_id = fixtures["assignments"]["lifecycle"]
    students = fixtures["students"]
    users = fixtures["users"]

    conn = get_conn()
    try:
        # Student A has rejected history and one latest pending attempt.
        add_attempt(conn, assignment_id, students["student_a"], "a-old", "rejected", "reviewed", 0)
        add_attempt(conn, assignment_id, students["student_a"], "a-latest", "submitted", "submitted", 1)
        # Deliberately leave legacy status='submitted': Phase 3 must use review_status.
        add_attempt(conn, assignment_id, students["student_b"], "b-latest", "accepted", "submitted", 1)
        conn.commit()

        index_row = conn.execute(
            """SELECT COUNT(*) AS n
               FROM INFORMATION_SCHEMA.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE()
                 AND TABLE_NAME = 'lms_assignment_submissions'
                 AND INDEX_NAME = 'idx_lms_asn_assignment_latest_review'"""
        ).fetchone()
        assert index_row["n"] == 3

        counts = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN COALESCE(review_status, 'submitted') IN ('accepted', 'rejected') THEN 1 ELSE 0 END) AS reviewed,
                   SUM(CASE WHEN COALESCE(review_status, 'submitted') = 'submitted' THEN 1 ELSE 0 END) AS pending
               FROM lms_assignment_submissions
               WHERE assignment_id = ? AND is_latest = 1""",
            (assignment_id,),
        ).fetchone()
        assert (counts["total"], counts["reviewed"], counts["pending"]) == (2, 1, 1)
    finally:
        conn.close()

    admin = baseline.session_client({
        "user_id": users["admin"], "role": "admin", "branch_id": fixtures["branch"]
    })
    trainer_a = baseline.session_client({
        "user_id": users["trainer_a"], "role": "staff", "branch_id": fixtures["branch"]
    })
    trainer_b = baseline.session_client({
        "user_id": users["trainer_b"], "role": "staff", "branch_id": fixtures["branch"]
    })

    admin_page = admin.get("/lms_admin/master/assignments")
    trainer_a_page = trainer_a.get("/lms_admin/master/assignments")
    trainer_b_page = trainer_b.get("/lms_admin/master/assignments")
    topic_page = admin.get(f"/lms_admin/master/topic/{fixtures['topic']}/assignments")
    assert all(page.status_code == 200 for page in (admin_page, trainer_a_page, trainer_b_page, topic_page))

    assert b'aria-label="2 submissions, 1 reviewed, 1 pending"' in admin_page.data
    assert b'aria-label="1 submissions, 0 reviewed, 1 pending"' in trainer_a_page.data
    assert b'aria-label="1 submissions, 1 reviewed, 0 pending"' in trainer_b_page.data
    assert b"2 submissions" in topic_page.data
    assert b"1 reviewed" in topic_page.data

    print("phase3_latest_attempt_total=OK total=2")
    print("phase3_review_status_counts=OK reviewed=1 pending=1")
    print("phase3_trainer_scoped_counts=OK")
    print("phase3_topic_management_counts=OK")
    print("phase3_composite_index=OK")


if __name__ == "__main__":
    try:
        phase3_fixtures = baseline.create_fixtures()
        run_phase3(phase3_fixtures)
    finally:
        baseline.cleanup()
    print("phase3_cleanup=OK")
    print("phase3_counts=OK")
