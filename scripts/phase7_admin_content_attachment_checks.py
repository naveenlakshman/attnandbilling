"""Phase 7 admin content propagation + attachment-path checks.

Checks performed:
1. Admin content edit on a master-topic rich-text row.
2. Student visibility of edited content in linked program topic view.
3. Revert edit and confirm marker removal.
4. Protected attachment endpoint behavior (unauthenticated redirect,
   authenticated response path without server errors).

The script is safe for repeated runs and reverts content to original values.
"""

from __future__ import annotations

from datetime import datetime

from app import app
from db import get_conn


def _pick_master_richtext_for_program(program_id: int = 1):
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                c.id AS content_id,
                c.master_topic_id,
                c.content_title,
                c.content_body,
                c.display_order
            FROM lms_topic_contents c
            JOIN lms_master_topics mt ON mt.id = c.master_topic_id AND mt.status = 'active'
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id AND mc.status = 'active'
            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
            WHERE c.master_topic_id IS NOT NULL
              AND c.content_mode = 'rich_text'
              AND COALESCE(c.content_body, '') != ''
              AND pc.program_id = ?
              AND pc.is_visible = 1
            ORDER BY c.id
            LIMIT 1
            """,
            (program_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def _pick_student_with_program_access(program_id: int):
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT s.id AS student_id
            FROM students s
            WHERE EXISTS (
                SELECT 1
                FROM lms_programs lp
                WHERE lp.id = ? AND lp.is_active = 1 AND (
                    EXISTS (
                        SELECT 1
                        FROM lms_student_program_access spa
                        WHERE spa.student_id = s.id
                          AND spa.program_id = lp.id
                          AND spa.is_active = 1
                          AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM lms_batch_program_access bpa
                        JOIN student_batches sb ON sb.batch_id = bpa.batch_id
                        WHERE sb.student_id = s.id
                          AND bpa.program_id = lp.id
                          AND bpa.is_active = 1
                          AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM invoices i
                        JOIN invoice_items ii ON ii.invoice_id = i.id
                        WHERE i.student_id = s.id
                          AND ii.course_id = lp.course_id
                          AND lp.course_id IS NOT NULL
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM invoices i
                        JOIN invoice_items ii ON ii.invoice_id = i.id
                        JOIN lms_course_program_map cpm
                          ON cpm.course_id = ii.course_id
                         AND cpm.program_id = lp.id
                        WHERE i.student_id = s.id
                    )
                )
            )
            ORDER BY s.id
            LIMIT 1
            """,
            (program_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def _pick_file_content(program_id: int = 1):
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT c.id AS content_id, c.content_mode, c.file_path
            FROM lms_topic_contents c
            JOIN lms_master_topics mt ON mt.id = c.master_topic_id
            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
            WHERE c.content_mode IN ('pdf', 'download')
              AND COALESCE(c.file_path, '') != ''
              AND pc.program_id = ?
              AND pc.is_visible = 1
            ORDER BY c.id
            LIMIT 1
            """,
            (program_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def _content_row(content_id: int):
    conn = get_conn()
    try:
        return conn.execute(
            """
            SELECT id, content_title, content_body, content_mode, display_order, master_topic_id
            FROM lms_topic_contents
            WHERE id = ?
            """,
            (content_id,),
        ).fetchone()
    finally:
        conn.close()


def main() -> int:
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    program_id = 1
    picked_content = _pick_master_richtext_for_program(program_id)
    picked_student = _pick_student_with_program_access(program_id)
    picked_file = _pick_file_content(program_id)

    if not picked_content or not picked_student or not picked_file:
        print('admin_checks_ok=False; reason=missing_test_fixtures')
        print(f'has_content={bool(picked_content)}; has_student={bool(picked_student)}; has_file={bool(picked_file)}')
        return 1

    content_id = picked_content['content_id']
    master_topic_id = picked_content['master_topic_id']
    student_id = picked_student['student_id']
    file_content_id = picked_file['content_id']
    file_mode = picked_file['content_mode']

    marker = f"PHASE7_PROPAGATION_MARKER_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    original_title = picked_content['content_title']
    original_body = picked_content['content_body']
    original_display_order = picked_content['display_order'] or 1

    print(f'selected_program_id={program_id}')
    print(f'selected_student_id={student_id}')
    print(f'selected_content_id={content_id}; master_topic_id={master_topic_id}')
    print(f'selected_file_content_id={file_content_id}; file_mode={file_mode}')

    client = app.test_client()

    # Admin can open edit page.
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'admin'
    r_edit_get = client.get(f'/lms_admin/content/{content_id}/edit', follow_redirects=False)
    print(f'admin_edit_get_status={r_edit_get.status_code}')

    # Admin updates content with marker.
    updated_body = f"{original_body}\n<p>{marker}</p>"
    r_edit_post = client.post(
        f'/lms_admin/content/{content_id}/edit',
        data={
            'title': original_title,
            'content_mode': 'rich_text',
            'content_body': updated_body,
            'display_order': str(original_display_order),
            'external_url': '',
        },
        follow_redirects=False,
    )
    print(f'admin_edit_post_status={r_edit_post.status_code}')

    row_after_edit = _content_row(content_id)
    marker_in_db = bool(row_after_edit and marker in (row_after_edit['content_body'] or ''))
    print(f'propagation_db_marker_present={marker_in_db}')

    # Student loads master topic and should see updated marker.
    with client.session_transaction() as sess:
        sess.clear()
        sess['student_id'] = student_id
        sess['student_name'] = 'Phase7 Student'

    r_student_topic_after_edit = client.get(
        f'/student/program/{program_id}/master-topic/{master_topic_id}',
        follow_redirects=False,
    )
    topic_html_after_edit = r_student_topic_after_edit.get_data(as_text=True)
    marker_in_student_view = marker in topic_html_after_edit
    print(f'student_topic_after_edit_status={r_student_topic_after_edit.status_code}')
    print(f'propagation_student_view_marker_present={marker_in_student_view}')

    # Revert content to original body.
    with client.session_transaction() as sess:
        sess.clear()
        sess['user_id'] = 1
        sess['role'] = 'admin'

    r_revert_post = client.post(
        f'/lms_admin/content/{content_id}/edit',
        data={
            'title': original_title,
            'content_mode': 'rich_text',
            'content_body': original_body,
            'display_order': str(original_display_order),
            'external_url': '',
        },
        follow_redirects=False,
    )
    print(f'admin_revert_post_status={r_revert_post.status_code}')

    row_after_revert = _content_row(content_id)
    marker_after_revert = bool(row_after_revert and marker in (row_after_revert['content_body'] or ''))
    print(f'propagation_marker_after_revert={marker_after_revert}')

    # Attachment path checks.
    # 1) Unauthenticated request should be redirected to login.
    with client.session_transaction() as sess:
        sess.clear()

    if file_mode == 'pdf':
        file_url = f'/student/content/{file_content_id}/pdf'
    else:
        file_url = f'/student/content/{file_content_id}/download'

    r_file_anon = client.get(file_url, follow_redirects=False)
    location = r_file_anon.headers.get('Location', '')
    print(f'attachment_anon_status={r_file_anon.status_code}; location={location}')

    # 2) Authenticated student request should not error; 200 if file exists, 404 if missing.
    with client.session_transaction() as sess:
        sess['student_id'] = student_id
        sess['student_name'] = 'Phase7 Student'

    r_file_auth = client.get(file_url, follow_redirects=False)
    print(f'attachment_auth_status={r_file_auth.status_code}')

    # Optional negative path: requesting download route for a pdf content should 404.
    r_wrong_mode = client.get(f'/student/content/{file_content_id}/download', follow_redirects=False)
    print(f'attachment_wrong_mode_status={r_wrong_mode.status_code}')

    admin_ok = r_edit_get.status_code == 200 and r_edit_post.status_code in (302, 303)
    propagation_ok = (
        marker_in_db
        and r_student_topic_after_edit.status_code == 200
        and marker_in_student_view
        and r_revert_post.status_code in (302, 303)
        and not marker_after_revert
    )
    attachment_ok = (
        r_file_anon.status_code in (301, 302)
        and '/student/login' in location
        and r_file_auth.status_code in (200, 404)
        and r_wrong_mode.status_code in (404,)
    )

    ok = admin_ok and propagation_ok and attachment_ok
    print(f'admin_checks_ok={ok}')
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
