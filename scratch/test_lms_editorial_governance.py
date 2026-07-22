"""MySQL regression coverage for LMS editorial governance."""

import test_assignment_phase0_mysql as baseline
from db import get_conn


def edit_form(body, note, pending=False):
    data = {
        'title': 'Governed lesson', 'content_mode': 'rich_text',
        'content_body': body, 'display_order': '1', 'change_note': note,
    }
    if pending:
        data['submit_for_approval'] = '1'
    return data


def run(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    admin = baseline.session_client({
        'user_id': fixtures['users']['admin'], 'role': 'admin', 'branch_id': fixtures['branch']
    })
    staff = baseline.session_client({
        'user_id': fixtures['users']['trainer_a'], 'role': 'staff', 'branch_id': fixtures['branch']
    })

    created = staff.post(
        f"/lms_admin/master/topic/{fixtures['topic']}/content/new",
        data=edit_form('<p>Initial approved lesson.</p>', 'Initial authored lesson.'),
    )
    assert created.status_code == 302
    conn = get_conn()
    try:
        content = conn.execute(
            "SELECT * FROM lms_topic_contents WHERE master_topic_id = ? AND content_mode = 'rich_text'",
            (fixtures['topic'],),
        ).fetchone()
        content_id = content['id']
        first = conn.execute(
            "SELECT * FROM lms_content_revisions WHERE content_id = ? ORDER BY revision_no",
            (content_id,),
        ).fetchall()
        assert len(first) == 1 and first[0]['approval_status'] == 'approved'
        assert first[0]['created_by'] == fixtures['users']['trainer_a']
    finally:
        conn.close()

    pending = staff.post(
        f"/lms_admin/content/{content_id}/edit",
        data=edit_form('<p>Pending reviewed lesson.</p>', 'Improve student explanation.', True),
    )
    assert pending.status_code == 302
    queue = admin.get('/lms_admin/master/editorial-reviews')
    assert queue.status_code == 200
    assert b'Improve student explanation.' in queue.data
    conn = get_conn()
    try:
        live = conn.execute("SELECT content_body FROM lms_topic_contents WHERE id = ?", (content_id,)).fetchone()
        assert 'Initial approved lesson' in live['content_body']
        revision = conn.execute(
            "SELECT * FROM lms_content_revisions WHERE content_id = ? AND approval_status = 'pending'",
            (content_id,),
        ).fetchone()
        pending_revision_id = revision['id']
    finally:
        conn.close()

    denied = staff.post(
        f"/lms_admin/content/{content_id}/revision/{pending_revision_id}/approve"
    )
    assert denied.status_code in (302, 403)
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT approval_status FROM lms_content_revisions WHERE id = ?", (pending_revision_id,)
        ).fetchone()['approval_status'] == 'pending'
    finally:
        conn.close()
    approved = admin.post(
        f"/lms_admin/content/{content_id}/revision/{pending_revision_id}/approve",
        data={'review_note': 'Reviewed and approved.'},
    )
    assert approved.status_code == 302
    conn = get_conn()
    try:
        assert 'Pending reviewed lesson' in conn.execute(
            "SELECT content_body FROM lms_topic_contents WHERE id = ?", (content_id,)
        ).fetchone()['content_body']
    finally:
        conn.close()

    direct = staff.post(
        f"/lms_admin/content/{content_id}/edit",
        data=edit_form('<p>Newer direct version.</p>', 'Urgent correction.'),
    )
    assert direct.status_code == 302
    stale = staff.post(
        f"/lms_admin/content/{content_id}/edit",
        data=edit_form('<p>Stale pending version.</p>', 'Needs review.', True),
    )
    assert stale.status_code == 302
    newer = staff.post(
        f"/lms_admin/content/{content_id}/edit",
        data=edit_form('<p>Newest approved version.</p>', 'Later direct correction.'),
    )
    assert newer.status_code == 302
    conn = get_conn()
    try:
        stale_id = conn.execute(
            "SELECT id FROM lms_content_revisions WHERE content_id = ? AND approval_status = 'pending' "
            "ORDER BY revision_no DESC LIMIT 1", (content_id,)
        ).fetchone()['id']
    finally:
        conn.close()
    stale_approval = admin.post(
        f"/lms_admin/content/{content_id}/revision/{stale_id}/approve", follow_redirects=True
    )
    assert b'revision is stale' in stale_approval.data

    history = admin.get(f"/lms_admin/content/{content_id}/history")
    assert history.status_code == 200
    assert b'Revision History' in history.data
    assert b'Improve student explanation.' in history.data

    rollback = admin.post(
        f"/lms_admin/content/{content_id}/revision/{pending_revision_id}/rollback",
        data={'review_note': 'Restore reviewed version.'},
    )
    assert rollback.status_code == 302
    conn = get_conn()
    try:
        assert 'Pending reviewed lesson' in conn.execute(
            "SELECT content_body FROM lms_topic_contents WHERE id = ?", (content_id,)
        ).fetchone()['content_body']
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM lms_content_revisions WHERE content_id = ? AND action_type = 'rollback'",
            (content_id,),
        ).fetchone()['n'] == 1
    finally:
        conn.close()

    reject_pending = staff.post(
        f"/lms_admin/content/{content_id}/edit",
        data=edit_form('<p>Rejected draft.</p>', 'Experimental rewrite.', True),
    )
    assert reject_pending.status_code == 302
    conn = get_conn()
    try:
        reject_id = conn.execute(
            "SELECT id FROM lms_content_revisions WHERE content_id = ? AND approval_status = 'pending' "
            "ORDER BY revision_no DESC LIMIT 1", (content_id,)
        ).fetchone()['id']
    finally:
        conn.close()
    rejected = admin.post(
        f"/lms_admin/content/{content_id}/revision/{reject_id}/reject",
        data={'review_note': 'Needs clearer examples.'},
    )
    assert rejected.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT approval_status FROM lms_content_revisions WHERE id = ?", (reject_id,)
        ).fetchone()['approval_status'] == 'rejected'
        assert 'Rejected draft' not in conn.execute(
            "SELECT content_body FROM lms_topic_contents WHERE id = ?", (content_id,)
        ).fetchone()['content_body']
    finally:
        conn.close()

    print('lms_editorial_immutable_revisions=OK')
    print('lms_editorial_optional_approval=OK')
    print('lms_editorial_stale_approval_guard=OK')
    print('lms_editorial_rollback_and_identity=OK')
    print('lms_editorial_review_queue_and_rejection=OK')


def cleanup_content():
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM lms_content_revisions WHERE master_topic_id IN "
            "(SELECT id FROM lms_master_topics WHERE title LIKE ?)", (f"{baseline.PREFIX}%",)
        )
        conn.execute(
            "DELETE FROM lms_topic_contents WHERE master_topic_id IN "
            "(SELECT id FROM lms_master_topics WHERE title LIKE ?)", (f"{baseline.PREFIX}%",)
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        seeded = baseline.create_fixtures()
        run(seeded)
    finally:
        cleanup_content()
        baseline.cleanup()
    print('lms_editorial_governance_cleanup=OK')
