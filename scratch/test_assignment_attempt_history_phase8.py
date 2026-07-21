"""Phase 8 reviewer identity and assignment attempt-history regressions."""

import time

import test_assignment_phase0_mysql as baseline
from db import get_conn


def run_phase8(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    baseline.run_baseline(fixtures)
    users = fixtures['users']
    students = fixtures['students']
    assignment_id = fixtures['assignments']['lifecycle']

    admin = baseline.session_client({'user_id': users['admin'], 'role': 'admin', 'branch_id': fixtures['branch']})
    trainer_a = baseline.session_client({'user_id': users['trainer_a'], 'role': 'staff', 'branch_id': fixtures['branch']})
    trainer_b = baseline.session_client({'user_id': users['trainer_b'], 'role': 'staff', 'branch_id': fixtures['branch']})
    student_a = baseline.session_client({'student_id': students['student_a'], 'student_login_at': int(time.time())})

    conn = get_conn()
    attempts = conn.execute(
        """SELECT id, is_latest, review_status, reviewed_by
           FROM lms_assignment_submissions
           WHERE assignment_id = ? AND student_id = ? ORDER BY id""",
        (assignment_id, students['student_a']),
    ).fetchall()
    reviewer = conn.execute('SELECT full_name FROM users WHERE id = ?', (users['admin'],)).fetchone()
    conn.close()
    assert len(attempts) == 2
    assert all(row['reviewed_by'] == users['admin'] for row in attempts)

    latest = admin.get(f"/lms_admin/master/reviews/{attempts[1]['id']}")
    assert latest.status_code == 200
    assert b'Attempt History' in latest.data and b'#1' in latest.data and b'#2' in latest.data
    assert latest.data.count(reviewer['full_name'].encode()) >= 2
    assert b'Reviewed at' in latest.data
    assert b'Review formulas.' in latest.data
    assert b'Please correct the calculations.' in latest.data
    assert b'Good work.' in latest.data
    assert b'Not scored' in latest.data

    historical = trainer_a.get(f"/lms_admin/master/reviews/{attempts[0]['id']}")
    assert historical.status_code == 200
    assert b'read-only because it has already been processed' in historical.data
    assert b'<button class="btn btn-success"' not in historical.data
    assert trainer_b.get(f"/lms_admin/master/reviews/{attempts[0]['id']}").status_code == 403

    student_history = student_a.get(
        f"/student/program/{fixtures['program']}/master-topic/{fixtures['topic']}/assignments"
    )
    assert student_history.status_code == 200
    lifecycle = next(item for item in student_history.get_json()['assignments'] if item['id'] == assignment_id)
    assert len(lifecycle['attempts']) == 2
    assert [item['attempt_number'] for item in reversed(lifecycle['attempts'])] == [1, 2]
    assert lifecycle['attempts'][0]['reviewed_by_name'] == reviewer['full_name']
    assert lifecycle['submission']['reviewed_by_name'] == reviewer['full_name']

    print('phase8_reviewer_identity_timestamp=OK')
    print('phase8_staff_attempt_history=OK attempts=2')
    print('phase8_historical_read_only_authorization=OK')
    print('phase8_student_staff_history_agreement=OK')


if __name__ == '__main__':
    try:
        phase8_fixtures = baseline.create_fixtures()
        run_phase8(phase8_fixtures)
    finally:
        baseline.cleanup()
    print('phase8_cleanup=OK')
    print('phase8_attempt_history=OK')
