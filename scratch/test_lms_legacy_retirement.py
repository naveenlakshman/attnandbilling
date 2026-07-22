"""MySQL regression coverage for resumable LMS legacy retirement."""

import test_assignment_phase0_mysql as baseline
from db import get_conn
from modules.lms_admin.routes import _migrate_legacy_chapter_to_master


def run(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    admin = baseline.session_client({
        'user_id': fixtures['users']['admin'], 'role': 'admin', 'branch_id': fixtures['branch']
    })
    conn = get_conn()
    try:
        chapter_cursor = conn.execute(
            "INSERT INTO lms_chapters (program_id, chapter_title, chapter_order, description, is_active, created_at) "
            "VALUES (?, ?, 9, '', 1, ?)",
            (fixtures['program'], f"{baseline.PREFIX} Legacy Chapter", baseline.NOW),
        )
        legacy_chapter = chapter_cursor.lastrowid
        legacy_topics = []
        for order in (1, 2):
            cursor = conn.execute(
                "INSERT INTO lms_topics (chapter_id, topic_title, topic_order, short_description, content_type, "
                "is_preview, is_active, is_required, created_at) VALUES (?, ?, ?, '', 'lesson', 0, 1, 0, ?)",
                (legacy_chapter, f"{baseline.PREFIX} Legacy Topic {order}", order, baseline.NOW),
            )
            legacy_topics.append(cursor.lastrowid)
        conn.execute(
            "INSERT INTO lms_master_topic_bridge (master_topic_id, legacy_topic_id, created_at) VALUES (?, ?, ?)",
            (fixtures['topic'], legacy_topics[0], baseline.NOW),
        )
        conn.execute(
            "INSERT INTO lms_topic_contents (topic_id, content_mode, content_title, content_body, display_order, created_at) "
            "VALUES (?, 'rich_text', ?, '<p>Legacy content</p>', 1, ?)",
            (legacy_topics[0], f"{baseline.PREFIX} Legacy Content", baseline.NOW),
        )
        conn.commit()

        migration, error = _migrate_legacy_chapter_to_master(
            conn.cursor(), fixtures['program'], legacy_chapter, fixtures['users']['admin']
        )
        assert error is None
        assert migration['migrated_topics'] == 1
        assert migration['repaired_content'] == 1
        conn.commit()

        mapped = conn.execute(
            "SELECT COUNT(*) AS n FROM lms_master_topic_bridge WHERE legacy_topic_id IN (?, ?)",
            tuple(legacy_topics),
        ).fetchone()['n']
        assert mapped == 2
        tagged = conn.execute(
            "SELECT master_topic_id FROM lms_topic_contents WHERE topic_id = ?", (legacy_topics[0],)
        ).fetchone()['master_topic_id']
        assert tagged == fixtures['topic']

        repeated, repeat_error = _migrate_legacy_chapter_to_master(
            conn.cursor(), fixtures['program'], legacy_chapter, fixtures['users']['admin']
        )
        assert repeated is None and 'fully migrated' in repeat_error
        conn.rollback()
    finally:
        conn.close()

    chapter_redirect = admin.get(f"/lms_admin/chapter/{legacy_chapter}/topics")
    assert chapter_redirect.status_code == 302
    assert f"/lms_admin/master/chapter/{fixtures['chapter']}/topics" in chapter_redirect.location
    topic_redirect = admin.get(f"/lms_admin/topic/{legacy_topics[0]}/contents")
    assert topic_redirect.status_code == 302
    assert f"/lms_admin/master/topic/{fixtures['topic']}/contents" in topic_redirect.location

    old_write = admin.post(
        f"/lms_admin/topic/{legacy_topics[0]}/edit",
        data={'title': 'SHOULD NOT WRITE'},
    )
    assert old_write.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT topic_title FROM lms_topics WHERE id = ?", (legacy_topics[0],)
        ).fetchone()['topic_title'] != 'SHOULD NOT WRITE'
    finally:
        conn.close()

    dashboard = admin.get('/lms_admin/legacy-migration')
    assert dashboard.status_code == 200
    assert b'Legacy Retirement' in dashboard.data
    print('lms_legacy_partial_resume_and_repair=OK')
    print('lms_legacy_idempotent_migration=OK')
    print('lms_legacy_bookmark_redirects_and_write_retirement=OK')


def cleanup_legacy():
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM lms_content_revisions WHERE master_topic_id IN "
            "(SELECT id FROM lms_master_topics WHERE title LIKE ?)", (f"{baseline.PREFIX}%",)
        )
        conn.execute(
            "DELETE FROM lms_topic_contents WHERE topic_id IN "
            "(SELECT id FROM lms_topics WHERE topic_title LIKE ?)", (f"{baseline.PREFIX}%",)
        )
        conn.execute(
            "DELETE FROM lms_master_topic_bridge WHERE legacy_topic_id IN "
            "(SELECT id FROM lms_topics WHERE topic_title LIKE ?)", (f"{baseline.PREFIX}%",)
        )
        conn.execute("DELETE FROM lms_topics WHERE topic_title LIKE ?", (f"{baseline.PREFIX}%",))
        conn.execute("DELETE FROM lms_chapters WHERE chapter_title LIKE ?", (f"{baseline.PREFIX}%",))
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        seeded = baseline.create_fixtures()
        run(seeded)
    finally:
        cleanup_legacy()
        baseline.cleanup()
    print('lms_legacy_retirement_cleanup=OK')
