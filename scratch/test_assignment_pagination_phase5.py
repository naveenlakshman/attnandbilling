"""Phase 5 server-side filtering, sorting, and pagination regressions."""

import time
from urllib.parse import quote_plus

import test_assignment_phase0_mysql as baseline
from db import get_conn


def seed_volume(fixtures):
    conn = get_conn()
    try:
        # The base fixture has three assignments; add 57 for an exact total of 60.
        for number in range(3, 60):
            created = "2026-07-10 12:00:00" if number < 30 else "2026-07-21 12:00:00"
            conn.execute(
                """INSERT INTO lms_assignments
                   (master_topic_id, title, description, uploaded_by, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    fixtures["topic"], f"{baseline.PREFIX} Volume {number:03d}",
                    "Phase 5 pagination fixture", fixtures["users"]["admin"], created,
                ),
            )

        assignment_id = fixtures["assignments"]["lifecycle"]
        batch_id = fixtures["batches"]["batch_a"]
        for number in range(60):
            student_id = baseline.insert_id(
                conn,
                """INSERT INTO students
                   (student_code, full_name, phone, joined_date, status, branch_id, created_at, portal_enabled)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, 1)""",
                (
                    f"P5{baseline.TOKEN[:5]}{number:03d}",
                    f"{baseline.PREFIX} Page Student {number:03d}",
                    "9000000000", "2026-07-01", fixtures["branch"], baseline.NOW,
                ),
            )
            conn.execute(
                """INSERT INTO student_batches
                   (student_id, batch_id, joined_on, status, created_at, uses_own_laptop)
                   VALUES (?, ?, '2026-07-01', 'active', ?, 0)""",
                (student_id, batch_id, baseline.NOW),
            )
            status = ('submitted', 'accepted', 'rejected')[number % 3]
            submitted_at = "2026-07-10 12:00:00" if number < 30 else "2026-07-21 12:00:00"
            conn.execute(
                """INSERT INTO lms_assignment_submissions
                   (assignment_id, student_id, file_path, original_filename, status,
                    review_status, submitted_at, updated_at, is_latest)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    assignment_id, student_id, f"documents/page-{number:03d}.pdf",
                    f"page-{number:03d}.pdf", 'submitted' if status == 'submitted' else 'reviewed',
                    status, submitted_at, submitted_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def run_phase5(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    admin = baseline.session_client({
        "user_id": fixtures["users"]["admin"], "role": "admin", "branch_id": fixtures["branch"]
    })
    program = fixtures["program"]
    assignment = fixtures["assignments"]["lifecycle"]

    started = time.perf_counter()
    page_one = admin.get(f"/lms_admin/master/assignments?program_id={program}")
    assignment_ms = (time.perf_counter() - started) * 1000
    assert page_one.status_code == 200
    assert b"Showing 1" in page_one.data and b"25 of 60 assignments" in page_one.data
    assert b"Page 1 of 3" in page_one.data
    assert page_one.data.count(b'class="assignment-title"') == 25

    page_two = admin.get(f"/lms_admin/master/assignments?program_id={program}&page=2&per_page=25")
    assert page_two.status_code == 200
    assert b"Showing 26" in page_two.data and b"50 of 60 assignments" in page_two.data
    assert b"Page 2 of 3" in page_two.data

    search_term = f"{baseline.PREFIX} Volume 042"
    searched = admin.get(
        f"/lms_admin/master/assignments?program_id={program}&q={quote_plus(search_term)}"
    )
    assert searched.status_code == 200
    assert search_term.encode() in searched.data
    assert b"Showing 1" in searched.data and b"1 of 1 assignments" in searched.data

    dated = admin.get(
        f"/lms_admin/master/assignments?program_id={program}&date_from=2026-07-20&per_page=50"
    )
    assert dated.status_code == 200
    assert b"33 of 33 assignments" in dated.data

    unsafe = admin.get(
        f"/lms_admin/master/assignments?program_id={program}&sort=title%20DESC%3BDROP%20TABLE%20users&direction=sideways&per_page=999&page=-5"
    )
    assert unsafe.status_code == 200
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] > 0
    conn.close()

    started = time.perf_counter()
    submissions_one = admin.get(
        f"/lms_admin/master/assignments/{assignment}/submissions?per_page=25"
    )
    submission_ms = (time.perf_counter() - started) * 1000
    assert submissions_one.status_code == 200
    assert b'href="/lms_admin/master/assignments"' in submissions_one.data
    assert f'/lms_admin/master/topic/{fixtures["topic"]}/assignments'.encode() not in submissions_one.data
    assert b"Showing 1" in submissions_one.data and b"25 of 60 submissions" in submissions_one.data
    assert b"Page 1 of 3" in submissions_one.data
    assert submissions_one.data.count(b'class="submission-card"') == 25

    submissions_three = admin.get(
        f"/lms_admin/master/assignments/{assignment}/submissions?per_page=25&page=3"
    )
    assert submissions_three.status_code == 200
    assert b"Showing 51" in submissions_three.data and b"60 of 60 submissions" in submissions_three.data
    assert submissions_three.data.count(b'class="submission-card"') == 10

    student_search = admin.get(
        f"/lms_admin/master/assignments/{assignment}/submissions?q={quote_plus(baseline.PREFIX + ' Page Student 042')}"
    )
    assert student_search.status_code == 200
    assert f"{baseline.PREFIX} Page Student 042".encode() in student_search.data
    assert b"1 of 1 submissions" in student_search.data

    accepted = admin.get(
        f"/lms_admin/master/assignments/{assignment}/submissions?status_filter=accepted&per_page=25"
    )
    assert accepted.status_code == 200
    assert b"20 of 20 submissions" in accepted.data

    recent = admin.get(
        f"/lms_admin/master/assignments/{assignment}/submissions?date_from=2026-07-20&per_page=50"
    )
    assert recent.status_code == 200
    assert b"30 of 30 submissions" in recent.data

    unsafe_submissions = admin.get(
        f"/lms_admin/master/assignments/{assignment}/submissions?sort=submitted%20DESC%3BDROP%20TABLE%20students&direction=no&per_page=999&page=-2"
    )
    assert unsafe_submissions.status_code == 200

    print(f"phase5_assignment_pagination=OK response_ms={assignment_ms:.1f} bytes={len(page_one.data)}")
    print(f"phase5_submission_pagination=OK response_ms={submission_ms:.1f} bytes={len(submissions_one.data)}")
    print("phase5_search_and_date_filters=OK")
    print("phase5_status_filter=OK accepted=20")
    print("phase5_invalid_parameters_safe=OK")


if __name__ == "__main__":
    try:
        phase5_fixtures = baseline.create_fixtures()
        seed_volume(phase5_fixtures)
        run_phase5(phase5_fixtures)
    finally:
        baseline.cleanup()
    print("phase5_cleanup=OK")
    print("phase5_pagination=OK")
