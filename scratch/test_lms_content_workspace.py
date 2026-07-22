"""Regression coverage for the LMS admin/staff content workspace."""

import test_assignment_phase0_mysql as baseline


def run(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    users = fixtures['users']
    admin = baseline.session_client({
        'user_id': users['admin'], 'role': 'admin', 'branch_id': fixtures['branch']
    })
    staff = baseline.session_client({
        'user_id': users['trainer_a'], 'role': 'staff', 'branch_id': fixtures['branch']
    })

    for client in (admin, staff):
        dashboard = client.get('/lms_admin/dashboard')
        assert dashboard.status_code == 200
        assert b'LMS Content Workspace' in dashboard.data
        assert b'Content Authoring Workflow' in dashboard.data
        assert b'Open Master Library' in dashboard.data
        assert b'Topics Missing Lesson' in dashboard.data

        topic = client.get(f"/lms_admin/master/topic/{fixtures['topic']}/contents")
        assert topic.status_code == 200
        assert b'Topic is ready for student preview' not in topic.data
        assert b'Lesson content is still required' in topic.data
        assert b'1 of 3 content slots configured' in topic.data
        assert f"/lms_admin/program/{fixtures['program']}/master-topic/{fixtures['topic']}/preview".encode() in topic.data

    assert b'Course Mapping' in admin.get('/lms_admin/dashboard').data
    assert b'Check Program Status' in staff.get('/lms_admin/dashboard').data
    print('lms_content_workspace_admin_staff=OK')
    print('lms_content_readiness_and_preview=OK')


if __name__ == '__main__':
    try:
        seeded = baseline.create_fixtures()
        run(seeded)
    finally:
        baseline.cleanup()
    print('lms_content_workspace_cleanup=OK')
