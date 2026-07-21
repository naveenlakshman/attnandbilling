"""Phase 9 optional grading, due-date, rubric, and completion-rule regressions."""

import io
import time

import test_assignment_phase0_mysql as baseline
from db import get_conn


def run_phase9(fixtures):
    baseline.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    users, students = fixtures['users'], fixtures['students']
    admin = baseline.session_client({'user_id': users['admin'], 'role': 'admin', 'branch_id': fixtures['branch']})
    student_a = baseline.session_client({'student_id': students['student_a'], 'student_login_at': int(time.time())})
    student_b = baseline.session_client({'student_id': students['student_b'], 'student_login_at': int(time.time())})

    conn = get_conn()
    rubric_id = baseline.insert_id(conn, "INSERT INTO lms_rubrics (name, created_by) VALUES (?, ?)",
                                   (f'{baseline.PREFIX} Rubric', users['admin']))
    criterion_a = baseline.insert_id(conn, "INSERT INTO lms_rubric_criteria (rubric_id, criterion_name, max_score, display_order) VALUES (?, ?, 50, 1)", (rubric_id, 'Accuracy'))
    criterion_b = baseline.insert_id(conn, "INSERT INTO lms_rubric_criteria (rubric_id, criterion_name, max_score, display_order) VALUES (?, ?, 50, 2)", (rubric_id, 'Presentation'))
    assignment_id = fixtures['assignments']['lifecycle']
    conn.execute(
        """UPDATE lms_assignments SET grading_mode='numeric_rubric', rubric_id=?,
                  max_score=100, passing_score=60, completion_rule='score_meets_passing_score',
                  due_at='2099-01-01 12:00:00', allow_late_submission=1, max_attempts=2
           WHERE id=?""", (rubric_id, assignment_id))
    conn.commit(); conn.close()

    with baseline.fake_submission_storage():
        baseline.submit(student_a, assignment_id, 'graded-attempt.pdf')
    conn = get_conn()
    submission_id = conn.execute("SELECT id FROM lms_assignment_submissions WHERE assignment_id=? AND student_id=? AND is_latest=1", (assignment_id, students['student_a'])).fetchone()['id']
    conn.close()

    detail = admin.get(f'/lms_admin/master/reviews/{submission_id}')
    assert detail.status_code == 200
    assert b'Score (maximum' in detail.data and b'Accuracy' in detail.data and b'Presentation' in detail.data
    assert b'On time' in detail.data

    invalid = admin.post(f'/lms_admin/master/submissions/{submission_id}/accept', data={
        'score': '101', f'criterion_{criterion_a}': '50', f'criterion_{criterion_b}': '50'
    }, follow_redirects=True)
    assert b'Score must be between 0 and' in invalid.data
    missing = admin.post(f'/lms_admin/master/submissions/{submission_id}/accept', data={'score': '80'}, follow_redirects=True)
    assert b'Score is required for rubric criterion' in missing.data

    accepted = admin.post(f'/lms_admin/master/submissions/{submission_id}/accept', data={
        'score': '80', 'feedback': 'Strong work.', 'internal_reviewer_notes': 'Verified privately.',
        f'criterion_{criterion_a}': '45', f'criterion_comment_{criterion_a}': 'Accurate',
        f'criterion_{criterion_b}': '35',
    })
    assert accepted.status_code == 302
    conn = get_conn()
    graded = conn.execute("SELECT review_status, score, graded_at, internal_reviewer_notes, is_late FROM lms_assignment_submissions WHERE id=?", (submission_id,)).fetchone()
    rubric_count = conn.execute("SELECT COUNT(*) AS n FROM lms_submission_rubric_scores WHERE submission_id=?", (submission_id,)).fetchone()['n']
    progress = conn.execute("SELECT is_completed FROM lms_master_topic_progress WHERE student_id=? AND program_id=? AND master_topic_id=?", (students['student_a'], fixtures['program'], fixtures['topic'])).fetchone()
    conn.close()
    assert graded['review_status'] == 'accepted' and float(graded['score']) == 80 and graded['graded_at']
    assert graded['internal_reviewer_notes'] == 'Verified privately.' and graded['is_late'] == 0
    assert rubric_count == 2 and progress and progress['is_completed'] == 1

    student_view = student_a.get(f"/student/program/{fixtures['program']}/master-topic/{fixtures['topic']}/assignments").get_json()
    lifecycle = next(item for item in student_view['assignments'] if item['id'] == assignment_id)
    assert lifecycle['submission']['score'] == 80.0
    assert 'internal_reviewer_notes' not in lifecycle['submission']

    late_assignment = fixtures['assignments']['authorization']
    conn = get_conn()
    conn.execute("UPDATE lms_assignments SET due_at='2020-01-01 00:00:00', allow_late_submission=0, max_attempts=1 WHERE id=?", (late_assignment,))
    conn.commit(); conn.close()
    with baseline.fake_submission_storage():
        blocked_late = student_b.post(f'/student/assignments/{late_assignment}/submit', data={'submission_file': (io.BytesIO(b'x'), 'late.pdf')}, content_type='multipart/form-data')
        assert blocked_late.status_code == 403 and 'due date has passed' in blocked_late.get_json()['error']
        conn = get_conn(); conn.execute("UPDATE lms_assignments SET allow_late_submission=1 WHERE id=?", (late_assignment,)); conn.commit(); conn.close()
        allowed_late = student_b.post(f'/student/assignments/{late_assignment}/submit', data={'submission_file': (io.BytesIO(b'x'), 'late.pdf')}, content_type='multipart/form-data')
        assert allowed_late.status_code == 200 and allowed_late.get_json()['is_late'] is True

    conn = get_conn()
    late_submission = conn.execute("SELECT id,is_late FROM lms_assignment_submissions WHERE assignment_id=? AND student_id=?", (late_assignment, students['student_b'])).fetchone()
    conn.close(); assert late_submission['is_late'] == 1
    admin.post(f"/lms_admin/master/submissions/{late_submission['id']}/reject", data={'rejection_reason': 'Retry.'})
    with baseline.fake_submission_storage():
        maxed = student_b.post(f'/student/assignments/{late_assignment}/submit', data={'submission_file': (io.BytesIO(b'x'), 'again.pdf')}, content_type='multipart/form-data')
    assert maxed.status_code == 403 and 'Maximum submission attempts reached' in maxed.get_json()['error']

    print('phase9_numeric_rubric_validation=OK')
    print('phase9_score_completion_rule=OK')
    print('phase9_internal_notes_private=OK')
    print('phase9_late_submission_server_rule=OK')
    print('phase9_max_attempts_server_rule=OK')


if __name__ == '__main__':
    try:
        phase9_fixtures = baseline.create_fixtures()
        run_phase9(phase9_fixtures)
    finally:
        conn = get_conn()
        try:
            conn.execute("""DELETE srs FROM lms_submission_rubric_scores srs
                            JOIN lms_rubric_criteria rc ON rc.id=srs.criterion_id
                            JOIN lms_rubrics r ON r.id=rc.rubric_id WHERE r.name LIKE ?""", (f'{baseline.PREFIX}%',))
            conn.commit()
        finally:
            conn.close()
        baseline.cleanup()
        conn = get_conn()
        try:
            conn.execute("DELETE FROM lms_rubrics WHERE name LIKE ?", (f'{baseline.PREFIX}%',))
            conn.commit()
        finally:
            conn.close()
    print('phase9_cleanup=OK')
    print('phase9_grading_completion=OK')
