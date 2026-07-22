"""MySQL regression coverage for LMS program publishing readiness."""

import test_assignment_phase0_mysql as baseline
from db import get_conn
from modules.lms_admin.publishing import get_program_publishing_readiness


def program_form(fixtures, publish=True):
    return {
        "program_name": f"{baseline.PREFIX} Program",
        "program_reference_name": f"{baseline.PREFIX} Program",
        "course_id": str(fixtures["course"]),
        "slug": f"phase0-{baseline.TOKEN}",
        "description": "Publishing readiness regression fixture",
        "thumbnail_path": "",
        "is_published": "1" if publish else "0",
    }


def run(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    admin = baseline.session_client({
        "user_id": fixtures["users"]["admin"], "role": "admin",
        "branch_id": fixtures["branch"],
    })
    staff = baseline.session_client({
        "user_id": fixtures["users"]["trainer_a"], "role": "staff",
        "branch_id": fixtures["branch"],
    })

    conn = get_conn()
    try:
        conn.execute("UPDATE lms_programs SET is_published = 0 WHERE id = ?", (fixtures["program"],))
        conn.commit()
        readiness = get_program_publishing_readiness(conn, fixtures["program"])
        assert not readiness["is_ready"]
        assert len(readiness["missing_lessons"]) == 1
    finally:
        conn.close()

    view = staff.get(f"/lms_admin/program/{fixtures['program']}/view")
    assert view.status_code == 200
    assert b"Publishing Readiness" in view.data
    assert b"Topics needing lesson content" in view.data
    assert b"Preview as student" in view.data

    blocked = admin.post(
        f"/lms_admin/program/{fixtures['program']}/edit",
        data=program_form(fixtures), follow_redirects=True,
    )
    assert blocked.status_code == 200
    assert b"remains a draft" in blocked.data
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT is_published FROM lms_programs WHERE id = ?", (fixtures["program"],)
        ).fetchone()["is_published"] == 0
    finally:
        conn.close()

    content = admin.post(
        f"/lms_admin/master/topic/{fixtures['topic']}/content/new",
        data={
            "title": "Ready lesson", "content_mode": "rich_text",
            "content_body": "<p>Student-ready lesson content.</p>", "display_order": "1",
        },
    )
    assert content.status_code == 302

    conn = get_conn()
    try:
        readiness = get_program_publishing_readiness(conn, fixtures["program"])
        assert readiness["is_ready"]
    finally:
        conn.close()

    published = admin.post(
        f"/lms_admin/program/{fixtures['program']}/edit",
        data=program_form(fixtures), follow_redirects=True,
    )
    assert published.status_code == 200
    assert b"Published" in published.data
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT is_published FROM lms_programs WHERE id = ?", (fixtures["program"],)
        ).fetchone()["is_published"] == 1
    finally:
        conn.close()

    print("lms_publishing_unready_block=OK")
    print("lms_publishing_ready_publish=OK")


def cleanup_content():
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM lms_topic_contents WHERE master_topic_id IN "
            "(SELECT id FROM lms_master_topics WHERE title LIKE ?)",
            (f"{baseline.PREFIX}%",),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        seeded = baseline.create_fixtures()
        run(seeded)
    finally:
        cleanup_content()
        baseline.cleanup()
    print("lms_publishing_readiness_cleanup=OK")
