"""Phase 7 integrated preview-and-review screen regressions."""

from unittest.mock import patch

import test_assignment_phase0_mysql as baseline
import test_assignment_authorization_phase2 as phase2
import test_assignment_pagination_phase5 as phase5
from db import get_conn
from modules.lms_admin import routes as lms_admin_routes


def run_phase7(fixtures, other_branch, actors):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    ist_filter = baseline.app.jinja_env.filters['format_ist_datetime']
    assert ist_filter('2026-06-15 00:00:00', '%d-%b-%Y %I:%M %p') == '15-Jun-2026 05:30 AM'
    assert ist_filter('2026-06-15T00:00:00+00:00', '%d-%b-%Y %I:%M %p') == '15-Jun-2026 05:30 AM'
    assert ist_filter('2026-06-15') == '15-06-2026'
    users = fixtures['users']
    admin = baseline.session_client({'user_id': users['admin'], 'role': 'admin', 'branch_id': fixtures['branch']})
    trainer_a = baseline.session_client({'user_id': users['trainer_a'], 'role': 'staff', 'branch_id': fixtures['branch']})
    trainer_b = baseline.session_client({'user_id': users['trainer_b'], 'role': 'staff', 'branch_id': fixtures['branch']})

    conn = get_conn()
    pending = conn.execute(
        """SELECT s.id FROM lms_assignment_submissions s
           JOIN students st ON st.id = s.student_id
           WHERE st.full_name LIKE ? AND s.is_latest = 1 AND s.review_status = 'submitted'
           ORDER BY s.id""",
        (f'{baseline.PREFIX} Page Student%',),
    ).fetchall()
    conn.close()
    assert len(pending) == 20
    first_id, next_id = pending[0]['id'], pending[1]['id']
    context = f"program_id={fixtures['program']}&status_filter=submitted&sort=submitted&direction=asc&per_page=25"

    queue = admin.get(f'/lms_admin/master/reviews?{context}')
    assert queue.status_code == 200
    assert f'/lms_admin/master/reviews/{first_id}'.encode() in queue.data

    detail = admin.get(f'/lms_admin/master/reviews/{first_id}?{context}')
    assert detail.status_code == 200
    assert b'Review Submission' in detail.data
    assert b'Assignment instructions' in detail.data
    assert b'PDF submission preview' in detail.data
    assert b'Accept' in detail.data and b'Reject' in detail.data
    assert f'/lms_admin/master/reviews/{next_id}'.encode() in detail.data
    assert b'program_id=' + str(fixtures['program']).encode() in detail.data
    assert detail.data.count(b'10-Jul-2026 05:30 PM') >= 2
    assert b'12:July' not in detail.data

    # The legacy Preview tab must render even when the object is only in cloud
    # storage and is absent from the rebuilt container's ephemeral filesystem.
    preview = admin.get(f'/lms_admin/submission/{first_id}/preview?{context}')
    assert preview.status_code == 200
    assert b'Assignment Submission Preview' in preview.data
    assert preview.data.count(b'Back to Review Queue') == 2
    assert f'program_id={fixtures["program"]}'.encode() in preview.data
    assert b'Back to Submissions' not in preview.data

    class CloudPdf:
        def file_exists(self, path): return True
        def download_file(self, path): return b'%PDF-1.4\nphase7\n%%EOF'

    with patch('modules.lms_admin.routes.get_storage_service', return_value=CloudPdf()):
        inline_pdf = admin.get(f'/lms_admin/master/submissions/file/{first_id}?inline=1')
    assert inline_pdf.status_code == 200
    assert inline_pdf.mimetype == 'application/pdf'
    assert inline_pdf.data.startswith(b'%PDF-1.4')

    class CloudDocx:
        def file_exists(self, path): return True
        def download_file(self, path): return b'PK\x03\x04phase7-docx'

    conn = get_conn()
    original_name = conn.execute(
        'SELECT original_filename FROM lms_assignment_submissions WHERE id = ?', (first_id,)
    ).fetchone()['original_filename']
    conn.execute(
        'UPDATE lms_assignment_submissions SET original_filename = ? WHERE id = ?',
        ('phase7-preview.docx', first_id),
    )
    conn.commit()
    conn.close()
    try:
        token = lms_admin_routes._make_submission_preview_token(first_id)
        with patch('modules.lms_admin.routes.get_storage_service', return_value=CloudDocx()):
            public_docx = admin.get(f'/lms_admin/submission/public-file?token={token}')
    finally:
        conn = get_conn()
        conn.execute(
            'UPDATE lms_assignment_submissions SET original_filename = ? WHERE id = ?',
            (original_name, first_id),
        )
        conn.commit()
        conn.close()
    assert public_docx.status_code == 200
    assert public_docx.mimetype == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', public_docx.mimetype
    assert public_docx.data.startswith(b'PK\x03\x04')

    class LegacyCloudImage:
        def file_exists(self, path): return path == 'documents/legacy-submission.jpeg'
        def download_file(self, path):
            assert path == 'documents/legacy-submission.jpeg'
            return b'\xff\xd8\xffphase7-jpeg'

    conn = get_conn()
    saved_file = conn.execute(
        'SELECT file_path, original_filename FROM lms_assignment_submissions WHERE id = ?',
        (first_id,),
    ).fetchone()
    conn.execute(
        'UPDATE lms_assignment_submissions SET file_path = ?, original_filename = ? WHERE id = ?',
        ('legacy-submission.jpeg', 'Student image.jpeg', first_id),
    )
    conn.commit()
    conn.close()
    try:
        with patch('modules.lms_admin.routes.get_storage_service', return_value=LegacyCloudImage()):
            inline_image = admin.get(f'/lms_admin/master/submissions/file/{first_id}?inline=1')
    finally:
        conn = get_conn()
        conn.execute(
            'UPDATE lms_assignment_submissions SET file_path = ?, original_filename = ? WHERE id = ?',
            (saved_file['file_path'], saved_file['original_filename'], first_id),
        )
        conn.commit()
        conn.close()
    assert inline_image.status_code == 200
    assert inline_image.mimetype == 'image/jpeg'
    assert inline_image.data.startswith(b'\xff\xd8\xff')

    security_headers_enabled = baseline.app.config.get('SECURITY_HEADERS_ENABLED')
    baseline.app.config['SECURITY_HEADERS_ENABLED'] = True
    try:
        csp_response = admin.get(f'/lms_admin/master/reviews/{first_id}')
    finally:
        baseline.app.config['SECURITY_HEADERS_ENABLED'] = security_headers_enabled
    preview_csp = csp_response.headers.get('Content-Security-Policy', '')
    assert "frame-src 'self' https://view.officeapps.live.com https://*.officeapps.live.com" in preview_csp

    assert trainer_a.get(f'/lms_admin/master/reviews/{first_id}').status_code == 200
    assert trainer_b.get(f'/lms_admin/master/reviews/{first_id}').status_code == 403

    accepted = admin.post(
        f'/lms_admin/master/submissions/{first_id}/accept',
        data={'feedback': 'Phase 7 accepted.', 'return_queue': '1',
              'return_next_id': str(next_id), 'return_program_id': str(fixtures['program']),
              'return_status_filter': 'submitted', 'return_sort': 'submitted',
              'return_direction': 'asc', 'return_per_page': '25'},
    )
    assert accepted.status_code == 302
    assert f'/lms_admin/master/reviews/{next_id}' in accepted.headers['Location']
    conn = get_conn()
    decision = conn.execute('SELECT review_status, reviewed_by, feedback FROM lms_assignment_submissions WHERE id = ?', (first_id,)).fetchone()
    assert decision['review_status'] == 'accepted' and decision['reviewed_by'] == users['admin']
    assert decision['feedback'] == 'Phase 7 accepted.'
    conn.close()

    duplicate = admin.post(
        f'/lms_admin/master/submissions/{first_id}/reject',
        data={'rejection_reason': 'Must not overwrite.', 'return_queue': '1'},
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert b'Only the latest pending submission can be accepted/rejected.' in duplicate.data
    conn = get_conn()
    unchanged = conn.execute('SELECT review_status, reviewed_by FROM lms_assignment_submissions WHERE id = ?', (first_id,)).fetchone()
    assert unchanged['review_status'] == 'accepted' and unchanged['reviewed_by'] == users['admin']
    conn.close()

    reviewed = admin.get(f'/lms_admin/master/reviews/{first_id}?{context}')
    assert reviewed.status_code == 200
    assert b'read-only because it has already been processed' in reviewed.data
    assert b'Phase 7 accepted.' in reviewed.data

    print('phase7_integrated_preview_decision=OK')
    print('phase7_cloud_backed_preview_route=OK')
    print('phase7_filtered_pending_navigation=OK')
    print('phase7_authorization_scope=OK')
    print('phase7_atomic_concurrent_review=OK')


if __name__ == '__main__':
    other_branch = None
    try:
        fixtures = baseline.create_fixtures()
        phase5.seed_volume(fixtures)
        other_branch, actors = phase2.add_security_actors(fixtures)
        run_phase7(fixtures, other_branch, actors)
    finally:
        baseline.cleanup()
        if other_branch is not None:
            phase2.cleanup_extra(other_branch)
    print('phase7_cleanup=OK')
    print('phase7_review_detail=OK')
