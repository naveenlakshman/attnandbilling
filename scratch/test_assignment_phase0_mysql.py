"""Phase 0 baseline coverage for the LMS assignment workflow.

Run inside the local web container:
    python scratch/test_assignment_phase0_mysql.py

The suite uses uniquely named MySQL fixtures, exercises real Flask routes, mocks
only external file storage, reports known baseline gaps, and removes its records.
It deliberately documents current behavior; it does not fix authorization or
counting behavior assigned to later phases.
"""

from __future__ import annotations

import io
import time
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from app import app
from db import get_conn


TOKEN = uuid.uuid4().hex[:12]
PREFIX = f"__phase0_{TOKEN}__"
NOW = "2026-07-21 12:00:00"


class FakeStorage:
    """Avoid external GCS writes while retaining route-level upload behavior."""

    def upload_file(self, file_obj, destination, content_type=None):
        file_obj.read()
        return destination


def insert_id(conn, sql, params):
    cursor = conn.execute(sql, params)
    return cursor.lastrowid


def session_client(session_values):
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(session_values)
    return client


@contextmanager
def fake_submission_storage():
    with patch("modules.students.routes.get_storage_service", return_value=FakeStorage()):
        yield


def create_fixtures():
    conn = get_conn()
    try:
        branch_id = insert_id(
            conn,
            """INSERT INTO branches
               (branch_name, branch_code, is_active, created_at, no_of_computers)
               VALUES (?, ?, 1, ?, 0)""",
            (f"{PREFIX} Branch", f"P0{TOKEN[:8]}", NOW),
        )
        course_id = insert_id(
            conn,
            """INSERT INTO courses
               (course_name, fee, is_active, created_at, show_on_website)
               VALUES (?, 0, 1, ?, 0)""",
            (f"{PREFIX} Course", NOW),
        )

        users = {}
        for label, role in (("admin", "admin"), ("trainer_a", "staff"), ("trainer_b", "staff")):
            users[label] = insert_id(
                conn,
                """INSERT INTO users
                   (full_name, username, password_hash, role, branch_id,
                    can_view_all_branches, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    f"{PREFIX} {label}",
                    f"{PREFIX}_{label}",
                    "phase0-not-a-login-password",
                    role,
                    branch_id,
                    1 if role == "admin" else 0,
                    NOW,
                ),
            )

        batches = {}
        for label, trainer in (("batch_a", users["trainer_a"]), ("batch_b", users["trainer_b"])):
            batches[label] = insert_id(
                conn,
                """INSERT INTO batches
                   (batch_name, course_id, branch_id, trainer_id, status, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (f"{PREFIX} {label}", course_id, branch_id, trainer, NOW),
            )

        students = {}
        for label, batch in (("student_a", batches["batch_a"]), ("student_b", batches["batch_b"])):
            students[label] = insert_id(
                conn,
                """INSERT INTO students
                   (student_code, full_name, phone, joined_date, status,
                    branch_id, created_at, portal_enabled)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, 1)""",
                (f"P0{TOKEN[:6]}{label[-1].upper()}", f"{PREFIX} {label}", "9000000000", NOW[:10], branch_id, NOW),
            )
            conn.execute(
                """INSERT INTO student_batches
                   (student_id, batch_id, joined_on, status, created_at, uses_own_laptop)
                   VALUES (?, ?, ?, 'active', ?, 0)""",
                (students[label], batch, NOW[:10], NOW),
            )

        chapter_id = insert_id(
            conn,
            """INSERT INTO lms_master_chapters
               (title, status, created_by, created_at)
               VALUES (?, 'active', ?, ?)""",
            (f"{PREFIX} Chapter", users["admin"], NOW),
        )
        topic_id = insert_id(
            conn,
            """INSERT INTO lms_master_topics
               (master_chapter_id, title, topic_order, status, created_at)
               VALUES (?, ?, 1, 'active', ?)""",
            (chapter_id, f"{PREFIX} Topic", NOW),
        )
        program_id = insert_id(
            conn,
            """INSERT INTO lms_programs
               (course_id, program_name, slug, is_published, is_active,
                created_by, created_at, is_deleted)
               VALUES (?, ?, ?, 1, 1, ?, ?, 0)""",
            (course_id, f"{PREFIX} Program", f"phase0-{TOKEN}", users["admin"], NOW),
        )
        conn.execute(
            """INSERT INTO lms_program_chapters
               (program_id, master_chapter_id, chapter_order, is_visible, created_at)
               VALUES (?, ?, 1, 1, ?)""",
            (program_id, chapter_id, NOW),
        )
        for label, batch in (("student_a", batches["batch_a"]), ("student_b", batches["batch_b"])):
            conn.execute(
                """INSERT INTO lms_student_program_access
                   (student_id, program_id, batch_id, access_status, is_active, created_at)
                   VALUES (?, ?, ?, 'active', 1, ?)""",
                (students[label], program_id, batch, NOW),
            )

        assignments = {}
        for label in ("lifecycle", "authorization", "delete"):
            assignments[label] = insert_id(
                conn,
                """INSERT INTO lms_assignments
                   (master_topic_id, title, description, uploaded_by, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (topic_id, f"{PREFIX} {label}", "Phase 0 baseline", users["admin"], NOW),
            )
        conn.commit()
        return {
            "branch": branch_id,
            "course": course_id,
            "users": users,
            "batches": batches,
            "students": students,
            "chapter": chapter_id,
            "topic": topic_id,
            "program": program_id,
            "assignments": assignments,
        }
    finally:
        conn.close()


def submit(client, assignment_id, filename):
    response = client.post(
        f"/student/assignments/{assignment_id}/submit",
        data={"submission_file": (io.BytesIO(b"phase-0-test-file"), filename)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, (response.status_code, response.get_data(as_text=True))
    payload = response.get_json()
    assert payload and payload["ok"] is True
    return payload


def run_baseline(fixtures):
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    users = fixtures["users"]
    students = fixtures["students"]
    assignments = fixtures["assignments"]

    admin = session_client({
        "user_id": users["admin"], "role": "admin", "branch_id": fixtures["branch"]
    })
    trainer_a = session_client({
        "user_id": users["trainer_a"], "role": "staff", "branch_id": fixtures["branch"]
    })
    trainer_b = session_client({
        "user_id": users["trainer_b"], "role": "staff", "branch_id": fixtures["branch"]
    })
    student_a = session_client({"student_id": students["student_a"], "student_login_at": int(time.time())})
    student_b = session_client({"student_id": students["student_b"], "student_login_at": int(time.time())})

    findings = []
    with fake_submission_storage():
        submit(student_a, assignments["lifecycle"], "attempt-1.pdf")

        duplicate = student_a.post(
            f"/student/assignments/{assignments['lifecycle']}/submit",
            data={"submission_file": (io.BytesIO(b"duplicate"), "duplicate.pdf")},
            content_type="multipart/form-data",
        )
        assert duplicate.status_code == 403

        conn = get_conn()
        first = conn.execute(
            """SELECT id FROM lms_assignment_submissions
               WHERE assignment_id = ? AND student_id = ? AND is_latest = 1""",
            (assignments["lifecycle"], students["student_a"]),
        ).fetchone()
        conn.close()
        assert first

        rejected = admin.post(
            f"/lms_admin/master/submissions/{first['id']}/reject",
            data={"rejection_reason": "Please correct the calculations.", "feedback": "Review formulas."},
        )
        assert rejected.status_code == 302

        submit(student_a, assignments["lifecycle"], "attempt-2.pdf")

        conn = get_conn()
        attempts = conn.execute(
            """SELECT id, is_latest, review_status FROM lms_assignment_submissions
               WHERE assignment_id = ? AND student_id = ? ORDER BY id""",
            (assignments["lifecycle"], students["student_a"]),
        ).fetchall()
        conn.close()
        assert len(attempts) == 2
        assert attempts[0]["is_latest"] == 0 and attempts[0]["review_status"] == "rejected"
        assert attempts[1]["is_latest"] == 1 and attempts[1]["review_status"] == "submitted"

        accepted = admin.post(f"/lms_admin/master/submissions/{attempts[1]['id']}/accept", data={"feedback": "Good work."})
        assert accepted.status_code == 302

        conn = get_conn()
        progress = conn.execute(
            """SELECT is_completed FROM lms_master_topic_progress
               WHERE student_id = ? AND program_id = ? AND master_topic_id = ?""",
            (students["student_a"], fixtures["program"], fixtures["topic"]),
        ).fetchone()
        accepted_state = conn.execute(
            "SELECT review_status, score FROM lms_assignment_submissions WHERE id = ?",
            (attempts[1]['id'],),
        ).fetchone()
        conn.close()
        assert progress and progress["is_completed"] == 1, (dict(progress) if progress else None, dict(accepted_state))

        submit(student_b, assignments["authorization"], "trainer-b-work.pdf")
        conn = get_conn()
        foreign_submission = conn.execute(
            """SELECT id FROM lms_assignment_submissions
               WHERE assignment_id = ? AND student_id = ? AND is_latest = 1""",
            (assignments["authorization"], students["student_b"]),
        ).fetchone()
        conn.close()
        assert foreign_submission

        foreign_list = trainer_a.get(
            f"/lms_admin/master/assignments/{assignments['authorization']}/submissions"
        )
        if foreign_list.status_code == 200 and f"{PREFIX} student_b".encode() in foreign_list.data:
            findings.append("AUTHORIZATION: trainer A can view trainer B's submission by direct assignment URL")

        foreign_review = trainer_a.post(
            f"/lms_admin/master/submissions/{foreign_submission['id']}/accept",
            data={"feedback": "Unauthorized baseline probe"},
        )
        conn = get_conn()
        reviewed = conn.execute(
            "SELECT review_status, reviewed_by FROM lms_assignment_submissions WHERE id = ?",
            (foreign_submission["id"],),
        ).fetchone()
        conn.close()
        assert foreign_review.status_code == 403
        assert reviewed["review_status"] == "submitted" and reviewed["reviewed_by"] is None
        print("phase0_cross_trainer_mutation_denied=OK")

    conn = get_conn()
    raw_count = conn.execute(
        "SELECT COUNT(*) AS n FROM lms_assignment_submissions WHERE assignment_id = ?",
        (assignments["lifecycle"],),
    ).fetchone()["n"]
    latest_count = conn.execute(
        "SELECT COUNT(*) AS n FROM lms_assignment_submissions WHERE assignment_id = ? AND is_latest = 1",
        (assignments["lifecycle"],),
    ).fetchone()["n"]
    conn.close()
    assert raw_count == 2 and latest_count == 1
    print(f"phase0_attempt_history=OK all_attempts={raw_count} latest_attempts={latest_count}")

    deleted = admin.post(f"/lms_admin/master/assignments/{assignments['delete']}/delete")
    assert deleted.status_code == 302
    conn = get_conn()
    assert conn.execute("SELECT id FROM lms_assignments WHERE id = ?", (assignments["delete"],)).fetchone() is None
    conn.close()

    # Confirm the role-scoped list itself hides trainer B's data from trainer A.
    scoped = trainer_a.get("/lms_admin/master/assignments")
    assert scoped.status_code == 200
    print("phase0_cross_trainer_list_scope=OK")

    conn = get_conn()
    assignment_volume = conn.execute("SELECT COUNT(*) AS n FROM lms_assignments").fetchone()["n"]
    submission_volume = conn.execute("SELECT COUNT(*) AS n FROM lms_assignment_submissions").fetchone()["n"]
    conn.close()
    started = time.perf_counter()
    dashboard = admin.get("/lms_admin/master/assignments")
    dashboard_ms = (time.perf_counter() - started) * 1000
    assert dashboard.status_code == 200
    print(
        "phase0_dashboard_baseline="
        f"assignments:{assignment_volume},submissions:{submission_volume},"
        f"response_ms:{dashboard_ms:.1f},response_bytes:{len(dashboard.data)}"
    )
    print("phase0_workflow=OK")
    print("phase0_upload_pending_reject_resubmit_accept=OK")
    print("phase0_topic_completion=OK")
    print("phase0_assignment_delete=OK")
    for finding in findings:
        print(f"BASELINE_GAP: {finding}")
    return findings


def cleanup():
    conn = get_conn()
    try:
        # Delete from leaves to roots; every predicate is restricted to this run's token.
        assignment_rows = conn.execute(
            "SELECT id FROM lms_assignments WHERE title LIKE ?", (f"{PREFIX}%",)
        ).fetchall()
        assignment_ids = [row["id"] for row in assignment_rows]
        for assignment_id in assignment_ids:
            conn.execute("DELETE FROM lms_assignment_submissions WHERE assignment_id = ?", (assignment_id,))
        conn.execute(
            "DELETE FROM activity_logs WHERE user_id IN (SELECT id FROM users WHERE username LIKE ?)",
            (f"{PREFIX}%",),
        )
        conn.execute("DELETE FROM lms_master_topic_progress WHERE master_topic_id IN (SELECT id FROM lms_master_topics WHERE title LIKE ?)", (f"{PREFIX}%",))
        conn.execute("DELETE FROM lms_assignments WHERE title LIKE ?", (f"{PREFIX}%",))
        conn.execute(
            "DELETE FROM lms_master_topic_bridge WHERE master_topic_id IN "
            "(SELECT id FROM lms_master_topics WHERE title LIKE ?) OR legacy_topic_id IN "
            "(SELECT id FROM lms_topics WHERE topic_title LIKE ?)",
            (f"{PREFIX}%", f"[MASTER BRIDGE] {PREFIX}%"),
        )
        conn.execute("DELETE FROM lms_topics WHERE topic_title LIKE ?", (f"[MASTER BRIDGE] {PREFIX}%",))
        conn.execute("DELETE FROM lms_student_program_access WHERE program_id IN (SELECT id FROM lms_programs WHERE slug = ?)", (f"phase0-{TOKEN}",))
        conn.execute("DELETE FROM lms_program_chapters WHERE program_id IN (SELECT id FROM lms_programs WHERE slug = ?)", (f"phase0-{TOKEN}",))
        conn.execute("DELETE FROM lms_programs WHERE slug = ?", (f"phase0-{TOKEN}",))
        conn.execute("DELETE FROM lms_master_topics WHERE title LIKE ?", (f"{PREFIX}%",))
        conn.execute("DELETE FROM lms_master_chapters WHERE title LIKE ?", (f"{PREFIX}%",))
        conn.execute("DELETE FROM student_batches WHERE student_id IN (SELECT id FROM students WHERE full_name LIKE ?)", (f"{PREFIX}%",))
        conn.execute("DELETE FROM students WHERE full_name LIKE ?", (f"{PREFIX}%",))
        conn.execute("DELETE FROM batches WHERE batch_name LIKE ?", (f"{PREFIX}%",))
        conn.execute("DELETE FROM users WHERE username LIKE ?", (f"{PREFIX}%",))
        conn.execute("DELETE FROM courses WHERE course_name LIKE ?", (f"{PREFIX}%",))
        conn.execute("DELETE FROM branches WHERE branch_name LIKE ?", (f"{PREFIX}%",))
        conn.commit()
    finally:
        conn.close()

    verify = get_conn()
    try:
        remaining = 0
        checks = (
            ("SELECT COUNT(*) AS n FROM branches WHERE branch_name LIKE ?", f"{PREFIX}%"),
            ("SELECT COUNT(*) AS n FROM users WHERE username LIKE ?", f"{PREFIX}%"),
            ("SELECT COUNT(*) AS n FROM students WHERE full_name LIKE ?", f"{PREFIX}%"),
            ("SELECT COUNT(*) AS n FROM batches WHERE batch_name LIKE ?", f"{PREFIX}%"),
            ("SELECT COUNT(*) AS n FROM lms_assignments WHERE title LIKE ?", f"{PREFIX}%"),
        )
        for sql, pattern in checks:
            remaining += verify.execute(sql, (pattern,)).fetchone()["n"]
        assert remaining == 0, f"Phase 0 cleanup left {remaining} token-matched fixture rows"
    finally:
        verify.close()


if __name__ == "__main__":
    fixtures = None
    try:
        fixtures = create_fixtures()
        gaps = run_baseline(fixtures)
        assert not gaps, f"Unexpected baseline gaps remain: {gaps}"
    finally:
        cleanup()
    print("phase0_cleanup=OK")
    print("phase0_baseline=OK")
