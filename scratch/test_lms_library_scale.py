"""MySQL regression coverage for Phase 3 LMS library scaling."""

import test_assignment_phase0_mysql as baseline
from db import get_conn


def run(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    admin = baseline.session_client({
        'user_id': fixtures['users']['admin'], 'role': 'admin', 'branch_id': fixtures['branch']
    })
    staff = baseline.session_client({
        'user_id': fixtures['users']['trainer_a'], 'role': 'staff', 'branch_id': fixtures['branch']
    })

    chapters = admin.get(
        f"/lms_admin/master/chapters?q={baseline.PREFIX}&status=all&usage=used&program={fixtures['program']}&per_page=12"
    )
    assert chapters.status_code == 200
    assert f"{baseline.PREFIX} Chapter".encode() in chapters.data
    assert b"Attach to program" in chapters.data

    missing = admin.get(
        f"/lms_admin/master/chapter/{fixtures['chapter']}/topics?status=all&readiness=missing_lesson&per_page=25"
    )
    assert missing.status_code == 200
    assert f"{baseline.PREFIX} Topic".encode() in missing.data
    ready = admin.get(
        f"/lms_admin/master/chapter/{fixtures['chapter']}/topics?status=all&readiness=ready"
    )
    assert ready.status_code == 200
    assert f"{baseline.PREFIX} Topic".encode() not in ready.data

    conn = get_conn()
    try:
        now = baseline.NOW
        cursor = conn.execute(
            "INSERT INTO lms_master_chapters (title, status, created_by, created_at) VALUES (?, 'active', ?, ?)",
            (f"{baseline.PREFIX} Bulk Chapter", fixtures['users']['admin'], now),
        )
        bulk_chapter = cursor.lastrowid
        cursor = conn.execute(
            "INSERT INTO lms_master_topics (master_chapter_id, title, topic_order, status, created_at) "
            "VALUES (?, ?, 1, 'active', ?)",
            (bulk_chapter, f"{baseline.PREFIX} Bulk Topic", now),
        )
        bulk_topic = cursor.lastrowid
        cursor = conn.execute(
            "INSERT INTO lms_master_chapters (title, status, created_by, created_at) VALUES (?, 'active', ?, ?)",
            (f"{baseline.PREFIX} Archive Chapter", fixtures['users']['admin'], now),
        )
        archive_chapter = cursor.lastrowid
        cursor = conn.execute(
            "INSERT INTO lms_master_topics (master_chapter_id, title, topic_order, status, created_at) "
            "VALUES (?, ?, 1, 'active', ?)",
            (archive_chapter, f"{baseline.PREFIX} Archive Topic", now),
        )
        archive_topic = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    attach = staff.post('/lms_admin/master/chapters/bulk', data={
        'bulk_action': 'attach', 'program_id': str(fixtures['program']),
        'chapter_ids': [str(bulk_chapter), str(fixtures['chapter'])],
    })
    assert attach.status_code == 302
    conn = get_conn()
    try:
        links = conn.execute(
            "SELECT id, master_chapter_id, is_visible FROM lms_program_chapters "
            "WHERE program_id = ? ORDER BY chapter_order", (fixtures['program'],)
        ).fetchall()
        assert len(links) == 2
        link_ids = [str(row['id']) for row in links]
    finally:
        conn.close()

    hide = staff.post(f"/lms_admin/program/{fixtures['program']}/chapter-links/bulk", data={
        'bulk_action': 'hide', 'link_ids': link_ids,
    })
    assert hide.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM lms_program_chapters WHERE program_id = ? AND is_visible = 1",
            (fixtures['program'],),
        ).fetchone()['n'] == 0
        conn.execute(
            "UPDATE lms_program_chapters SET is_visible = 1 WHERE program_id = ?", (fixtures['program'],)
        )
        conn.commit()
    finally:
        conn.close()

    move = staff.post(f"/lms_admin/program/{fixtures['program']}/chapter-links/bulk", data={
        'bulk_action': 'move_top', 'link_ids': link_ids[-1],
    })
    assert move.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT id FROM lms_program_chapters WHERE program_id = ? ORDER BY chapter_order LIMIT 1",
            (fixtures['program'],),
        ).fetchone()['id'] == int(link_ids[-1])
    finally:
        conn.close()

    protected = admin.post('/lms_admin/master/chapters/bulk', data={
        'bulk_action': 'archive', 'chapter_ids': str(fixtures['chapter']),
    })
    assert protected.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT status FROM lms_master_chapters WHERE id = ?", (fixtures['chapter'],)
        ).fetchone()['status'] == 'active'
    finally:
        conn.close()

    staff_archive = staff.post('/lms_admin/master/chapters/bulk', data={
        'bulk_action': 'archive', 'chapter_ids': str(archive_chapter),
    })
    assert staff_archive.status_code == 403
    archived = admin.post('/lms_admin/master/chapters/bulk', data={
        'bulk_action': 'archive', 'chapter_ids': str(archive_chapter),
    })
    assert archived.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT status FROM lms_master_chapters WHERE id = ?", (archive_chapter,)
        ).fetchone()['status'] == 'archived'
    finally:
        conn.close()

    protected_topic = admin.post(
        f"/lms_admin/master/chapter/{fixtures['chapter']}/topics/bulk",
        data={'bulk_action': 'archive', 'topic_ids': str(fixtures['topic'])},
    )
    assert protected_topic.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT status FROM lms_master_topics WHERE id = ?", (fixtures['topic'],)
        ).fetchone()['status'] == 'active'
    finally:
        conn.close()

    safe_topic = admin.post(
        f"/lms_admin/master/chapter/{archive_chapter}/topics/bulk",
        data={'bulk_action': 'archive', 'topic_ids': str(archive_topic)},
    )
    assert safe_topic.status_code == 302
    conn = get_conn()
    try:
        assert conn.execute(
            "SELECT status FROM lms_master_topics WHERE id = ?", (archive_topic,)
        ).fetchone()['status'] == 'archived'
    finally:
        conn.close()

    print('lms_library_server_filters_pagination=OK')
    print('lms_library_bulk_attach_visibility=OK')
    print('lms_library_published_content_safeguards=OK')
    print('lms_library_safe_bulk_archive_and_order=OK')


if __name__ == '__main__':
    try:
        seeded = baseline.create_fixtures()
        run(seeded)
    finally:
        baseline.cleanup()
    print('lms_library_scale_cleanup=OK')
