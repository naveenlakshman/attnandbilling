"""Phase 7 transactional smoke checks.

Runs HTTP-level checks through Flask test_client for:
- student master-topic journey
- completion write idempotency in lms_master_topic_progress
- admin rollout page access

The script is intentionally small and non-destructive except for expected
master progress upsert writes used to validate transactional behavior.
"""

from __future__ import annotations

from typing import Any

from app import app
from db import get_conn


def _pick_student_program_topic() -> dict[str, Any] | None:
    """Choose one student/program/topic tuple using the same access logic as student routes."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT
                s.id AS student_id,
                p.id AS program_id,
                mt.id AS master_topic_id
            FROM students s
            JOIN lms_programs p ON p.is_active = 1 AND p.slug != '__lms_master_bridge__'
            JOIN lms_program_chapters pc ON pc.program_id = p.id AND pc.is_visible = 1
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id AND mc.status = 'active'
            JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id AND mt.status = 'active'
            WHERE
                EXISTS (
                    SELECT 1
                    FROM lms_student_program_access spa
                    WHERE spa.student_id = s.id
                      AND spa.program_id = p.id
                      AND spa.is_active = 1
                      AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1
                    FROM lms_batch_program_access bpa
                    JOIN student_batches sb ON sb.batch_id = bpa.batch_id
                    WHERE sb.student_id = s.id
                      AND bpa.program_id = p.id
                      AND bpa.is_active = 1
                      AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1
                    FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE i.student_id = s.id
                      AND ii.course_id = p.course_id
                      AND p.course_id IS NOT NULL
                )
                OR EXISTS (
                    SELECT 1
                    FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    JOIN lms_course_program_map cpm
                      ON cpm.course_id = ii.course_id
                     AND cpm.program_id = p.id
                    WHERE i.student_id = s.id
                )
            ORDER BY s.id, p.id, pc.chapter_order, mt.topic_order
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return {
            "student_id": row["student_id"],
            "program_id": row["program_id"],
            "master_topic_id": row["master_topic_id"],
        }
    finally:
        conn.close()


def _progress_row(student_id: int, program_id: int, master_topic_id: int):
    conn = get_conn()
    try:
        return conn.execute(
            """
            SELECT student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at
            FROM lms_master_topic_progress
            WHERE student_id = ? AND program_id = ? AND master_topic_id = ?
            """,
            (student_id, program_id, master_topic_id),
        ).fetchone()
    finally:
        conn.close()


def main() -> int:
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    picked = _pick_student_program_topic()
    if not picked:
        print("smoke_ok=False; reason=no_accessible_student_program_master_topic")
        return 1

    student_id = picked["student_id"]
    program_id = picked["program_id"]
    master_topic_id = picked["master_topic_id"]

    print(f"selected_student_id={student_id}")
    print(f"selected_program_id={program_id}")
    print(f"selected_master_topic_id={master_topic_id}")

    client = app.test_client()

    # Student GET: program view should resolve (200 or redirect into first topic view)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
        sess["student_name"] = "Phase7 Smoke"

    r_program = client.get(f"/student/program/{program_id}", follow_redirects=False)
    print(f"program_view_status={r_program.status_code}")

    # Student GET: explicit master topic page
    r_topic = client.get(
        f"/student/program/{program_id}/master-topic/{master_topic_id}",
        follow_redirects=False,
    )
    print(f"master_topic_view_status={r_topic.status_code}")

    # Student POST: completion action idempotency and toggle
    r_complete_1 = client.post(
        f"/student/program/{program_id}/master-topic/{master_topic_id}/complete",
        data={"action": "complete", "confirmation_text": "Completed"},
    )
    print(f"mark_complete_first_status={r_complete_1.status_code}; body={r_complete_1.get_json()}")

    row_after_1 = _progress_row(student_id, program_id, master_topic_id)
    print(
        "progress_after_first="
        f"exists={bool(row_after_1)};is_completed={row_after_1['is_completed'] if row_after_1 else None};"
        f"created_at={row_after_1['created_at'] if row_after_1 else None};"
        f"updated_at={row_after_1['updated_at'] if row_after_1 else None}"
    )

    r_complete_2 = client.post(
        f"/student/program/{program_id}/master-topic/{master_topic_id}/complete",
        data={"action": "complete", "confirmation_text": "Completed"},
    )
    print(f"mark_complete_second_status={r_complete_2.status_code}; body={r_complete_2.get_json()}")

    row_after_2 = _progress_row(student_id, program_id, master_topic_id)
    print(
        "progress_after_second="
        f"exists={bool(row_after_2)};is_completed={row_after_2['is_completed'] if row_after_2 else None};"
        f"created_at={row_after_2['created_at'] if row_after_2 else None};"
        f"updated_at={row_after_2['updated_at'] if row_after_2 else None}"
    )

    r_incomplete = client.post(
        f"/student/program/{program_id}/master-topic/{master_topic_id}/complete",
        data={"action": "incomplete", "confirmation_text": "Not Completed"},
    )
    print(f"mark_incomplete_status={r_incomplete.status_code}; body={r_incomplete.get_json()}")

    row_after_incomplete = _progress_row(student_id, program_id, master_topic_id)
    print(
        "progress_after_incomplete="
        f"exists={bool(row_after_incomplete)};is_completed={row_after_incomplete['is_completed'] if row_after_incomplete else None};"
        f"completed_at={row_after_incomplete['completed_at'] if row_after_incomplete else None}"
    )

    # End with complete state so there is positive completion evidence in Phase 7.
    r_complete_final = client.post(
        f"/student/program/{program_id}/master-topic/{master_topic_id}/complete",
        data={"action": "complete", "confirmation_text": "Completed"},
    )
    print(f"mark_complete_final_status={r_complete_final.status_code}; body={r_complete_final.get_json()}")

    row_final = _progress_row(student_id, program_id, master_topic_id)
    print(
        "progress_final="
        f"exists={bool(row_final)};is_completed={row_final['is_completed'] if row_final else None};"
        f"completed_at={row_final['completed_at'] if row_final else None}"
    )

    # Admin GET: rollout page access with admin session.
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = 1
        sess["role"] = "admin"

    r_admin = client.get("/lms_admin/phase6/rollout", follow_redirects=False)
    print(f"admin_phase6_rollout_status={r_admin.status_code}")

    # Basic pass/fail gate
    ok = (
        r_program.status_code in (200, 302)
        and r_topic.status_code == 200
        and r_complete_1.status_code == 200
        and r_complete_2.status_code == 200
        and r_incomplete.status_code == 200
        and r_complete_final.status_code == 200
        and row_final is not None
        and row_final["is_completed"] == 1
        and r_admin.status_code == 200
    )
    print(f"smoke_ok={ok}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
