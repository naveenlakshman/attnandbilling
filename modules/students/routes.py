# pyrefly: ignore [missing-import]
from flask import render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
from hashlib import sha256
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import urllib.parse
import re
import os
import uuid
from db import get_conn
from extensions import limiter, public_auth_limit
from . import students_bp


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------
def _clear_student_session():
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('student_code', None)
    session.pop('student_login_at', None)
    session.pop('student_session_mode', None)
    session.pop('student_force_password_change', None)
    session.pop('demo_mode', None)


def _is_mobile_app_request():
    """Detect the Android APK/WebView student app without affecting lab browsers."""
    ua = request.headers.get('User-Agent', '').lower()
    explicit_app = (
        request.values.get('app') in {'1', 'true', 'yes', 'mobile'}
        or request.values.get('client') == 'mobile_app'
    )
    webview_app = '; wv' in ua or 'studentapp' in ua or 'attnandbillingapp' in ua
    return explicit_app or webview_app


def _student_mobile_cookie_name():
    return current_app.config.get('STUDENT_MOBILE_REMEMBER_COOKIE', 'student_mobile_auth')


def _student_mobile_max_age():
    days = int(current_app.config.get('STUDENT_MOBILE_SESSION_DAYS', 30))
    return days * 24 * 60 * 60


def _student_mobile_serializer():
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='student-mobile-auth-v1',
    )


def _password_fingerprint(password_hash):
    return sha256((password_hash or '').encode('utf-8')).hexdigest()


def _mark_student_logged_in(student, mode='lab'):
    session.permanent = mode == 'mobile_app'
    session['student_id'] = student['id']
    session['student_name'] = student['full_name']
    session['student_code'] = student['student_code']
    session['student_login_at'] = int(datetime.utcnow().timestamp())
    session['student_session_mode'] = mode
    session['student_force_password_change'] = (
        (not _is_demo()) and _is_default_student_password(student)
    )


def _set_student_mobile_cookie(response, student):
    token = _student_mobile_serializer().dumps({
        'student_id': student['id'],
        'student_code': student['student_code'],
        'password_fingerprint': _password_fingerprint(student['password_hash']),
    })
    response.set_cookie(
        _student_mobile_cookie_name(),
        token,
        max_age=_student_mobile_max_age(),
        httponly=True,
        secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
        samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
    )
    return response


def _clear_student_mobile_cookie(response):
    response.delete_cookie(
        _student_mobile_cookie_name(),
        secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
        samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
    )
    return response


def _restore_mobile_student_session():
    if not _is_mobile_app_request():
        return False

    token = request.cookies.get(_student_mobile_cookie_name())
    if not token:
        return False

    try:
        payload = _student_mobile_serializer().loads(
            token,
            max_age=_student_mobile_max_age(),
        )
    except (BadSignature, SignatureExpired):
        return False

    conn = get_conn()
    try:
        student = conn.execute(
            """
            SELECT * FROM students
            WHERE id = ? AND student_code = ? AND status != 'dropped' AND portal_enabled = 1
            """,
            (payload.get('student_id'), payload.get('student_code')),
        ).fetchone()
    finally:
        conn.close()

    if (
        not student
        or payload.get('password_fingerprint') != _password_fingerprint(student['password_hash'])
    ):
        return False

    _mark_student_logged_in(student, mode='mobile_app')
    return True


def _is_default_student_password(student):
    """Return True when student's current password is still their student code."""
    if not student or not student['password_hash'] or not student['student_code']:
        return False
    return check_password_hash(student['password_hash'], student['student_code'])


# Common passwords blocklist (8+ chars only, since shorter ones are already rejected)
_COMMON_PASSWORDS = {
    # Complex variations of 'password'
    'password', 'password1', 'password123', 'password12', 'Password1!', 'Password123',
    'Passw0rd', 'passw0rd', 'passw0rd!', 'passwordabc', 'password!@#',
    # Number sequences
    '123456789', '12345678', '12345679', '1234567890', '1122334455',
    # Keyboard patterns
    'qwerty123', 'qwertyasd', 'asdfghjkl', 'zxcvbnm12',
    # Common word combinations
    'letmein123', 'welcomeabc', 'monkeybaby', 'dragonfire', 'mastermind',
    'sunshineday', 'princess123', 'footballfan', 'shadowboss',
    # Common names with variations
    'michael123', 'superman123', 'batman1234', 'johndoe123', 'janedoe1234',
    # Admin/system common passwords
    'admin1234', 'administrator', 'rootaccess', 'root1234', 'sysadmin1',
    'login1234', 'guest1234', 'testtest123',
    # Educational institution common passwords
    'student123', 'student1234', 'college123', 'university1', 'academy123',
    'schooladmin', 'course1234',
    # Emotional/personal
    'iloveyou123', 'trustno1234', 'starwars123',
    # Number patterns (8+ chars)
    '11111111', '00000000', '66666666', '88888888', '99999999',
    '12121212', '11223344', '11112222',
    # Keyboard walks (8+ chars)
    'asdfghjkl', 'qwertyuiop', 'zxcvbnm123', 'asdf1234',
    # Real world common phrases
    'password11', 'password22', 'password99', 'pass@word', 'pass@1234',
    'welcome123', 'hello@123', 'abc123def', 'test@1234',
    'companyname', 'workpass123', 'office1234',
    # Rainbow table common entries
    'foundpass', 'crackme123', 'testcase12',
}


def _validate_student_password_policy(new_password, student_code):
    """Return None if valid; otherwise return policy error message."""
    if len(new_password) < 8:
        return 'New password must be at least 8 characters long.'
    if not re.search(r'[A-Za-z]', new_password):
        return 'New password must include at least one letter.'
    if not re.search(r'\d', new_password):
        return 'New password must include at least one number.'
    if not re.search(r'[^A-Za-z0-9]', new_password):
        return 'New password must include at least one special character.'
    if student_code and new_password.strip().upper() == student_code.strip().upper():
        return 'New password cannot be the same as your Student ID.'
    if new_password.lower() in _COMMON_PASSWORDS:
        return 'This password is too common. Please choose a stronger password.'
    return None


def student_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'student_id' not in session and not _restore_mobile_student_session():
            flash('Please log in to access the student portal.', 'warning')
            return redirect(url_for('students.login'))

        if session.get('student_session_mode') != 'mobile_app':
            timeout_minutes = int(current_app.config.get('STUDENT_SESSION_TIMEOUT_MINUTES', 120))
            now_ts = int(datetime.utcnow().timestamp())
            login_ts = session.get('student_login_at')

            if login_ts is None:
                session['student_login_at'] = now_ts
            else:
                try:
                    login_ts = int(login_ts)
                except (TypeError, ValueError):
                    login_ts = now_ts
                    session['student_login_at'] = now_ts

                if now_ts - login_ts > timeout_minutes * 60:
                    _clear_student_session()
                    flash('Your session expired. Please log in again.', 'warning')
                    return redirect(url_for('students.login'))

        if (
            not _is_demo()
            and session.get('student_force_password_change')
            and request.endpoint != 'students.change_password'
        ):
            flash('Please change your password before continuing.', 'warning')
            return redirect(url_for('students.change_password'))

        return f(*args, **kwargs)
    return decorated


def _is_demo():
    """Return True when the current session is a demo (read-only) session."""
    return bool(session.get('demo_mode'))


def _has_program_access(conn, program_id, student_id):
    """Return True if the student is enrolled/has access to program_id.
    Always returns True in demo mode."""
    if _is_demo():
        return True

    access = conn.execute("""
        SELECT 1 FROM lms_programs lp
        WHERE lp.id = ? AND lp.is_active = 1 AND COALESCE(lp.is_deleted, 0) = 0
          AND EXISTS (
              SELECT 1 FROM lms_student_program_access spa
              WHERE spa.student_id = ? AND spa.program_id = lp.id AND spa.is_active = 1
                AND COALESCE(spa.access_status, 'active') = 'active'
                AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
          )
    """, (program_id, student_id)).fetchone()
    return bool(access)


def _youtube_embed(url):
    """Convert any YouTube URL to embed URL."""
    if not url:
        return None
    url = url.strip()
    if 'youtube.com/embed/' in url:
        return url
    video_id = None
    if 'youtu.be/' in url:
        video_id = url.split('youtu.be/')[-1].split('?')[0].split('&')[0]
    elif 'youtube.com/watch' in url:
        qs = urllib.parse.urlparse(url).query
        params = urllib.parse.parse_qs(qs)
        video_id = params.get('v', [None])[0]
    if video_id:
        return f'https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1'
    return None


def _program_has_master_content(conn, program_id):
    """Return True when program has at least one visible linked active master chapter/topic."""
    row = conn.execute(
        """
            SELECT 1
            FROM lms_program_chapters pc
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
            JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
            WHERE pc.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
            LIMIT 1
        """,
        (program_id,)
    ).fetchone()
    return bool(row)


def _first_master_topic_for_program(conn, program_id):
    """Return first master topic id for a program by linked chapter/topic order."""
    return conn.execute(
        """
            SELECT mt.id
            FROM lms_program_chapters pc
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
            JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
            WHERE pc.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
            ORDER BY pc.chapter_order ASC, mt.topic_order ASC, mt.id ASC
            LIMIT 1
        """,
        (program_id,)
    ).fetchone()


def _ordered_master_topic_ids_for_program(conn, program_id):
    """Return active master topic ids in the program's visible LMS order."""
    rows = conn.execute(
        """
            SELECT mt.id
            FROM lms_program_chapters pc
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
            JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
            WHERE pc.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
            ORDER BY pc.chapter_order ASC, mt.topic_order ASC, mt.id ASC
        """,
        (program_id,)
    ).fetchall()
    return [row['id'] for row in rows]


def _next_master_topic_for_program(conn, program_id, master_topic_id):
    """Return the next active master topic id in LMS order, crossing chapters."""
    ordered_topic_ids = _ordered_master_topic_ids_for_program(conn, program_id)
    if master_topic_id not in ordered_topic_ids:
        return None

    current_index = ordered_topic_ids.index(master_topic_id)
    if current_index >= len(ordered_topic_ids) - 1:
        return None
    return ordered_topic_ids[current_index + 1]


def _completed_legacy_chapter_mock_url(conn, student_id, topic_id):
    """Return a mock setup URL when a legacy chapter's active topics are all complete."""
    topic = conn.execute(
        """
            SELECT lt.id, lt.chapter_id
            FROM lms_topics lt
            WHERE lt.id = ?
        """,
        (topic_id,)
    ).fetchone()
    if not topic:
        return None

    counts = conn.execute(
        """
            SELECT
                COUNT(*) AS total_topics,
                SUM(CASE WHEN COALESCE(tp.is_completed, 0) = 1 THEN 1 ELSE 0 END) AS completed_topics
            FROM lms_topics lt
            LEFT JOIN lms_topic_progress tp
                ON tp.topic_id = lt.id
               AND tp.student_id = ?
            WHERE lt.chapter_id = ?
              AND lt.is_active = 1
        """,
        (student_id, topic['chapter_id'])
    ).fetchone()

    if not counts or not counts['total_topics'] or counts['completed_topics'] != counts['total_topics']:
        return None

    master_chapter = conn.execute(
        """
            SELECT mt.master_chapter_id
            FROM lms_master_topic_bridge b
            JOIN lms_master_topics mt ON mt.id = b.master_topic_id
            JOIN lms_topics lt ON lt.id = b.legacy_topic_id
            WHERE lt.chapter_id = ?
            LIMIT 1
        """,
        (topic['chapter_id'],)
    ).fetchone()

    question_chapter_id = master_chapter['master_chapter_id'] if master_chapter else topic['chapter_id']
    status = _mock_status_for_question_chapter(conn, student_id, question_chapter_id)
    return status['url'] if status else None


def _completed_master_chapter_mock_url(conn, student_id, program_id, master_topic_id):
    """Return a mock setup URL when a reusable chapter's active topics are all complete."""
    topic = conn.execute(
        """
            SELECT master_chapter_id
            FROM lms_master_topics
            WHERE id = ?
        """,
        (master_topic_id,)
    ).fetchone()
    if not topic:
        return None

    counts = conn.execute(
        """
            SELECT
                COUNT(*) AS total_topics,
                SUM(CASE WHEN COALESCE(mp.is_completed, 0) = 1 THEN 1 ELSE 0 END) AS completed_topics
            FROM lms_master_topics mt
            LEFT JOIN lms_master_topic_progress mp
                ON mp.master_topic_id = mt.id
               AND mp.student_id = ?
               AND mp.program_id = ?
            WHERE mt.master_chapter_id = ?
              AND mt.status = 'active'
        """,
        (student_id, program_id, topic['master_chapter_id'])
    ).fetchone()

    if not counts or not counts['total_topics'] or counts['completed_topics'] != counts['total_topics']:
        return None

    status = _mock_status_for_question_chapter(conn, student_id, topic['master_chapter_id'])
    return status['url'] if status else None


def _latest_mock_attempt(conn, student_id, chapter_id):
    return conn.execute(
        """
            SELECT id, score_percent, submitted_at
            FROM lms_chapter_mock_attempts
            WHERE student_id = ?
              AND chapter_id = ?
            ORDER BY submitted_at DESC, id DESC
            LIMIT 1
        """,
        (student_id, chapter_id)
    ).fetchone()


def _mock_status_for_question_chapter(conn, student_id, question_chapter_id):
    has_questions = conn.execute(
        "SELECT 1 FROM lms_question_bank WHERE chapter_id = ? LIMIT 1",
        (question_chapter_id,)
    ).fetchone()
    if not has_questions:
        return None

    attempt = _latest_mock_attempt(conn, student_id, question_chapter_id)
    if attempt:
        return {
            'is_completed': True,
            'score_percent': attempt['score_percent'],
            'url': url_for('exams.review_chapter_mock', chapter_id=question_chapter_id),
        }

    return {
        'is_completed': False,
        'score_percent': None,
        'url': url_for('exams.chapter_mock_intro', chapter_id=question_chapter_id),
    }


def _master_mock_status_by_chapter(conn, student_id, chapter_ids):
    result = {}
    for chapter_id in chapter_ids:
        status = _mock_status_for_question_chapter(conn, student_id, chapter_id)
        if status:
            result[chapter_id] = status
    return result


def _legacy_mock_status_by_chapter(conn, student_id, chapter_ids):
    result = {}
    for chapter_id in chapter_ids:
        mapped = conn.execute(
            """
                SELECT mt.master_chapter_id
                FROM lms_master_topic_bridge b
                JOIN lms_master_topics mt ON mt.id = b.master_topic_id
                JOIN lms_topics lt ON lt.id = b.legacy_topic_id
                WHERE lt.chapter_id = ?
                LIMIT 1
            """,
            (chapter_id,)
        ).fetchone()
        question_chapter_id = mapped['master_chapter_id'] if mapped else chapter_id
        status = _mock_status_for_question_chapter(conn, student_id, question_chapter_id)
        if status:
            result[chapter_id] = status
    return result


def _last_master_topic_for_program(conn, student_id, program_id):
    """Return the student's last valid active master topic for this program."""
    if not student_id or _is_demo():
        return None
    return conn.execute(
        """
            SELECT mt.id
            FROM student_program_last_activity la
            JOIN lms_master_topics mt ON mt.id = la.master_topic_id
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
            JOIN lms_program_chapters pc
                ON pc.master_chapter_id = mt.master_chapter_id
               AND pc.program_id = la.program_id
            WHERE la.student_id = ?
              AND la.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
            LIMIT 1
        """,
        (student_id, program_id)
    ).fetchone()


def _save_last_master_topic(conn, student_id, program_id, master_topic_id):
    """Store the latest valid master topic opened by a student for a program."""
    if not student_id or _is_demo():
        return
    conn.execute(
        """
            INSERT INTO student_program_last_activity (
                student_id, program_id, master_topic_id, updated_at
            ) VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(student_id, program_id)
            DO UPDATE SET
                master_topic_id = excluded.master_topic_id,
                updated_at = datetime('now')
        """,
        (student_id, program_id, master_topic_id)
    )


def _has_approved_assignment(conn, student_id, program_id, master_topic_id):
    """Return True if student has an accepted assignment for this program/topic."""
    row = conn.execute(
        """
            SELECT 1
            FROM lms_assignment_submissions s
            JOIN lms_assignments a ON a.id = s.assignment_id
            JOIN lms_master_topics mt ON mt.id = a.master_topic_id
            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
            WHERE s.student_id = ?
              AND pc.program_id = ?
              AND a.master_topic_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
              AND COALESCE(
                    s.review_status,
                    CASE WHEN s.status = 'reviewed' THEN 'accepted' ELSE s.status END
                  ) = 'accepted'
            LIMIT 1
        """,
        (student_id, program_id, master_topic_id)
    ).fetchone()
    return bool(row)


def _master_curriculum_sidebar(conn, program_id, student_id):
    """Return chapters/topics/progress data for master-topic sidebar in one program."""
    chapters = conn.execute(
        """
            SELECT
                pc.id AS link_id,
                pc.chapter_order,
                pc.master_chapter_id AS id,
                COALESCE(pc.custom_title, mc.title) AS chapter_title
            FROM lms_program_chapters pc
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
            WHERE pc.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
            ORDER BY pc.chapter_order ASC, pc.id ASC
        """,
        (program_id,)
    ).fetchall()

    topics = conn.execute(
        """
            SELECT
                mt.id,
                mt.title AS topic_title,
                mt.topic_order,
                mt.master_chapter_id AS chapter_id,
                CASE
                    WHEN mp.is_completed = 1 THEN 1
                    WHEN EXISTS (
                        SELECT 1
                        FROM lms_assignments a
                        JOIN lms_assignment_submissions s ON s.assignment_id = a.id
                        JOIN lms_program_chapters pc2 ON pc2.master_chapter_id = mt.master_chapter_id
                        WHERE a.master_topic_id = mt.id
                          AND s.student_id = ?
                          AND pc2.program_id = ?
                          AND pc2.is_visible = 1
                          AND COALESCE(
                                s.review_status,
                                CASE WHEN s.status = 'reviewed' THEN 'accepted' ELSE s.status END
                              ) = 'accepted'
                    ) THEN 1
                    ELSE 0
                END AS is_completed
            FROM lms_program_chapters pc
            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
            JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
            LEFT JOIN lms_master_topic_progress mp
                ON mp.master_topic_id = mt.id
               AND mp.student_id = ?
               AND mp.program_id = ?
            WHERE pc.program_id = ?
              AND pc.is_visible = 1
              AND mc.status = 'active'
              AND mt.status = 'active'
            ORDER BY pc.chapter_order ASC, mt.topic_order ASC, mt.id ASC
        """,
                (student_id, program_id, student_id, program_id, program_id)
    ).fetchall()

    topics_by_chapter = {}
    for t in topics:
        topics_by_chapter.setdefault(t['chapter_id'], []).append(t)

    return chapters, topics, topics_by_chapter


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------
@students_bp.route('/login', methods=['GET', 'POST'])
@public_auth_limit()
def login():
    if 'student_id' in session:
        return redirect(url_for('students.dashboard'))

    mobile_app_login = _is_mobile_app_request()

    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
    finally:
        conn.close()

    if request.method == 'POST':
        student_code = request.form.get('student_code', '').strip().upper()
        password = request.form.get('password', '')

        conn = get_conn()
        try:
            student = conn.execute(
                "SELECT * FROM students WHERE student_code = ? AND status != 'dropped' AND portal_enabled = 1",
                (student_code,)
            ).fetchone()
        finally:
            conn.close()

        if student and student['password_hash'] and check_password_hash(student['password_hash'], password):
            mode = 'mobile_app' if mobile_app_login else 'lab'
            _mark_student_logged_in(student, mode=mode)

            if session['student_force_password_change']:
                flash('Your password is still the default Student ID. Please change it now.', 'warning')
                response = redirect(url_for('students.change_password'))
                if mobile_app_login:
                    response = _clear_student_mobile_cookie(response)
                return response

            response = redirect(url_for('students.dashboard'))
            if mobile_app_login:
                response = _set_student_mobile_cookie(response, student)
            return response

        flash('Invalid Student ID or password.', 'danger')

    return render_template(
        'students/login.html',
        company=company,
        mobile_app_login=mobile_app_login,
    )


@students_bp.route('/logout')
def logout():
    was_demo = session.get('demo_mode')
    _clear_student_session()
    response = redirect(url_for('lms_admin.dashboard')) if was_demo else redirect(url_for('students.login'))
    response = _clear_student_mobile_cookie(response)
    if was_demo:
        return response
    return response


# ---------------------------------------------------------------------------
# Dashboard — enrolled programs
# ---------------------------------------------------------------------------
@students_bp.route('/')
@students_bp.route('/dashboard')
@student_login_required
def dashboard():
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        if _is_demo():
            # Demo mode: show one published program per course/reference so cloned drafts
            # do not crowd the student preview used for lead demos.
            programs = conn.execute("""
                WITH ranked_demo_programs AS (
                    SELECT
                        lp.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(
                                'course:' || lp.course_id,
                                'course:' || (
                                    SELECT MIN(cpm_group.course_id)
                                    FROM lms_course_program_map cpm_group
                                    WHERE cpm_group.program_id = lp.id
                                ),
                                'ref:' || lower(trim(COALESCE(NULLIF(lp.program_reference_name, ''), lp.program_name)))
                            )
                            ORDER BY
                                datetime(COALESCE(NULLIF(lp.updated_at, ''), lp.created_at)) DESC,
                                lp.id DESC
                        ) AS demo_rank
                    FROM lms_programs lp
                    WHERE lp.is_active = 1
                      AND COALESCE(lp.is_deleted, 0) = 0
                      AND lp.is_published = 1
                )
                SELECT DISTINCT
                    lp.id, lp.program_name, lp.description,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM lms_program_chapters pcx
                            JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
                            JOIN lms_master_topics mtx ON mtx.master_chapter_id = mcx.id
                            WHERE pcx.program_id = lp.id
                              AND pcx.is_visible = 1
                              AND mcx.status = 'active'
                              AND mtx.status = 'active'
                        ) THEN (
                            SELECT COUNT(DISTINCT pc.master_chapter_id)
                            FROM lms_program_chapters pc
                            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                            WHERE pc.program_id = lp.id
                              AND pc.is_visible = 1
                              AND mc.status = 'active'
                        )
                        ELSE (
                            SELECT COUNT(*)
                            FROM lms_chapters lc
                            WHERE lc.program_id = lp.id AND lc.is_active = 1
                        )
                    END AS chapter_count,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM lms_program_chapters pcx
                            JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
                            JOIN lms_master_topics mtx ON mtx.master_chapter_id = mcx.id
                            WHERE pcx.program_id = lp.id
                              AND pcx.is_visible = 1
                              AND mcx.status = 'active'
                              AND mtx.status = 'active'
                        ) THEN (
                            SELECT COUNT(*)
                            FROM lms_master_topics mt
                            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                            WHERE pc.program_id = lp.id
                              AND pc.is_visible = 1
                              AND mc.status = 'active'
                              AND mt.status = 'active'
                        )
                        ELSE (
                            SELECT COUNT(*)
                            FROM lms_topics lt
                            JOIN lms_chapters lc2 ON lt.chapter_id = lc2.id
                            WHERE lc2.program_id = lp.id AND lt.is_active = 1
                        )
                    END AS topic_count,
                    0 AS completed_count,
                    NULL AS last_topic_id,
                    (SELECT lt4.id FROM lms_topics lt4 JOIN lms_chapters lc5 ON lt4.chapter_id = lc5.id
                     WHERE lc5.program_id = lp.id AND lc5.is_active = 1 AND lt4.is_active = 1
                     ORDER BY lc5.chapter_order, lt4.topic_order LIMIT 1) AS first_topic_id,
                    NULL AS map_order
                FROM ranked_demo_programs lp
                WHERE lp.demo_rank = 1
                ORDER BY COALESCE(lp.program_reference_name, lp.program_name), lp.program_name
            """).fetchall()
        else:
            # Normal mode: only programs the student is enrolled in
            programs = conn.execute("""
                SELECT DISTINCT
                    lp.id, lp.program_name, lp.description,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM lms_program_chapters pcx
                            JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
                            JOIN lms_master_topics mtx ON mtx.master_chapter_id = mcx.id
                            WHERE pcx.program_id = lp.id
                              AND pcx.is_visible = 1
                              AND mcx.status = 'active'
                              AND mtx.status = 'active'
                        ) THEN (
                            SELECT COUNT(DISTINCT pc.master_chapter_id)
                            FROM lms_program_chapters pc
                            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                            WHERE pc.program_id = lp.id
                              AND pc.is_visible = 1
                              AND mc.status = 'active'
                        )
                        ELSE (
                            SELECT COUNT(*)
                            FROM lms_chapters lc
                            WHERE lc.program_id = lp.id AND lc.is_active = 1
                        )
                    END AS chapter_count,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM lms_program_chapters pcx
                            JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
                            JOIN lms_master_topics mtx ON mtx.master_chapter_id = mcx.id
                            WHERE pcx.program_id = lp.id
                              AND pcx.is_visible = 1
                              AND mcx.status = 'active'
                              AND mtx.status = 'active'
                        ) THEN (
                            SELECT COUNT(*)
                            FROM lms_master_topics mt
                            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                            WHERE pc.program_id = lp.id
                              AND pc.is_visible = 1
                              AND mc.status = 'active'
                              AND mt.status = 'active'
                        )
                        ELSE (
                            SELECT COUNT(*)
                            FROM lms_topics lt
                            JOIN lms_chapters lc2 ON lt.chapter_id = lc2.id
                            WHERE lc2.program_id = lp.id AND lt.is_active = 1
                        )
                    END AS topic_count,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM lms_program_chapters pcx
                            JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
                            JOIN lms_master_topics mtx ON mtx.master_chapter_id = mcx.id
                            WHERE pcx.program_id = lp.id
                              AND pcx.is_visible = 1
                              AND mcx.status = 'active'
                              AND mtx.status = 'active'
                        ) THEN (
                            SELECT COUNT(*)
                            FROM lms_master_topic_progress mp
                            JOIN lms_master_topics mt ON mt.id = mp.master_topic_id
                            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                            JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                            WHERE mp.program_id = lp.id
                              AND mp.student_id = ?
                              AND mp.is_completed = 1
                              AND pc.program_id = lp.id
                              AND pc.is_visible = 1
                              AND mc.status = 'active'
                              AND mt.status = 'active'
                        )
                        ELSE (
                            SELECT COUNT(*)
                            FROM lms_topic_progress tp2
                            JOIN lms_topics lt2 ON tp2.topic_id = lt2.id
                            JOIN lms_chapters lc3 ON lt2.chapter_id = lc3.id
                            WHERE lc3.program_id = lp.id AND tp2.student_id = ? AND tp2.is_completed = 1
                        )
                    END AS completed_count,
                    (
                        SELECT lt3.id FROM lms_topic_progress tp3
                        JOIN lms_topics lt3 ON tp3.topic_id = lt3.id
                        JOIN lms_chapters lc4 ON lt3.chapter_id = lc4.id
                        WHERE lc4.program_id = lp.id AND tp3.student_id = ?
                        ORDER BY tp3.completed_at DESC LIMIT 1
                    ) AS last_topic_id,
                    (
                        SELECT lt4.id FROM lms_topics lt4
                        JOIN lms_chapters lc5 ON lt4.chapter_id = lc5.id
                        WHERE lc5.program_id = lp.id AND lc5.is_active = 1 AND lt4.is_active = 1
                        ORDER BY lc5.chapter_order, lt4.topic_order LIMIT 1
                    ) AS first_topic_id,
                    (
                        SELECT MIN(cpm_ord.display_order)
                        FROM lms_course_program_map cpm_ord
                        JOIN invoice_items ii_ord ON cpm_ord.course_id = ii_ord.course_id
                        JOIN invoices i_ord ON ii_ord.invoice_id = i_ord.id
                        WHERE cpm_ord.program_id = lp.id AND i_ord.student_id = ?
                    ) AS map_order
                FROM lms_programs lp
                WHERE lp.is_active = 1 AND COALESCE(lp.is_deleted, 0) = 0
                  AND EXISTS (
                      SELECT 1 FROM lms_student_program_access spa
                      WHERE spa.student_id = ? AND spa.program_id = lp.id
                        AND spa.is_active = 1
                        AND COALESCE(spa.access_status, 'active') = 'active'
                        AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                  )
                ORDER BY CASE WHEN map_order IS NULL THEN 1 ELSE 0 END, map_order, lp.program_name
            """, (student_id, student_id, student_id, student_id, student_id)).fetchall()

        programs = [dict(program) for program in programs]
        for program in programs:
            if _program_has_master_content(conn, program['id']):
                first_master_topic = _first_master_topic_for_program(conn, program['id'])
                last_master_topic = _last_master_topic_for_program(conn, student_id, program['id'])
                program['first_master_topic_id'] = first_master_topic['id'] if first_master_topic else None
                program['last_master_topic_id'] = last_master_topic['id'] if last_master_topic else None
            else:
                program['first_master_topic_id'] = None
                program['last_master_topic_id'] = None

    finally:
        conn.close()

    return render_template('students/dashboard.html',
                           programs=programs, company=company)


# ---------------------------------------------------------------------------
# Program — chapter list
# ---------------------------------------------------------------------------
@students_bp.route('/program/<int:program_id>')
@limiter.exempt
@student_login_required
def program_view(program_id):
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        # Verify access
        access = _has_program_access(conn, program_id, student_id)

        if not access:
            flash('You do not have access to this program.', 'danger')
            return redirect(url_for('students.dashboard'))

        program = conn.execute("SELECT * FROM lms_programs WHERE id = ?", (program_id,)).fetchone()

        has_master = _program_has_master_content(conn, program_id)

        if has_master:
            last_master_topic = _last_master_topic_for_program(conn, student_id, program_id)
            first_master_topic = _first_master_topic_for_program(conn, program_id)
            first_topic = None
            chapters = conn.execute(
                """
                    SELECT
                        pc.master_chapter_id AS id,
                        COALESCE(pc.custom_title, mc.title) AS chapter_title,
                        pc.chapter_order,
                        mc.description,
                        (
                            SELECT COUNT(*)
                            FROM lms_master_topics mt
                            WHERE mt.master_chapter_id = pc.master_chapter_id
                              AND mt.status = 'active'
                        ) AS topic_count
                    FROM lms_program_chapters pc
                    JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                    WHERE pc.program_id = ?
                      AND pc.is_visible = 1
                      AND mc.status = 'active'
                    ORDER BY pc.chapter_order ASC
                """,
                (program_id,)
            ).fetchall()
        else:
            last_master_topic = None
            first_master_topic = None
            # Find the first topic in the legacy program flow
            first_topic = conn.execute("""
                SELECT lt.id FROM lms_topics lt
                JOIN lms_chapters lc ON lt.chapter_id = lc.id
                WHERE lc.program_id = ? AND lc.is_active = 1 AND lt.is_active = 1
                ORDER BY lc.chapter_order, lt.topic_order
                LIMIT 1
            """, (program_id,)).fetchone()

            # Legacy fallback chapters list
            chapters = conn.execute("""
                SELECT lc.*,
                    (
                        SELECT COUNT(*) FROM lms_topics lt
                        WHERE lt.chapter_id = lc.id AND lt.is_active = 1
                    ) AS topic_count
                FROM lms_chapters lc
                WHERE lc.program_id = ? AND lc.is_active = 1
                ORDER BY lc.chapter_order
            """, (program_id,)).fetchall()

    finally:
        conn.close()

    # Redirect directly to first topic (Tally LMS style — sidebar shows full curriculum)
    # Resume from the last active master topic when the student has one.
    if last_master_topic:
        return redirect(url_for('students.master_topic_view', program_id=program_id, master_topic_id=last_master_topic['id']))

    if first_master_topic:
        return redirect(url_for('students.master_topic_view', program_id=program_id, master_topic_id=first_master_topic['id']))

    if first_topic:
        return redirect(url_for('students.topic_view', topic_id=first_topic['id']))

    # Fallback: show chapter list if no topics exist
    return render_template('students/program.html',
                           program=program, chapters=chapters, company=company)


# ---------------------------------------------------------------------------
# Chapter — topic list
# ---------------------------------------------------------------------------
@students_bp.route('/chapter/<int:chapter_id>')
@limiter.exempt
@student_login_required
def chapter_view(chapter_id):
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        chapter = conn.execute("""
            SELECT lc.*, lp.program_name, lp.id AS program_id
            FROM lms_chapters lc
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lc.id = ? AND lc.is_active = 1
        """, (chapter_id,)).fetchone()

        if not chapter:
            flash('Chapter not found.', 'danger')
            return redirect(url_for('students.dashboard'))

        # Verify program access
        access = _has_program_access(conn, chapter['program_id'], student_id)

        if not access:
            flash('You do not have access to this program.', 'danger')
            return redirect(url_for('students.dashboard'))

        topics = conn.execute("""
            SELECT lt.*,
                (
                    SELECT COUNT(*) FROM lms_topic_contents ltc
                    WHERE ltc.topic_id = lt.id
                ) AS content_count
            FROM lms_topics lt
            WHERE lt.chapter_id = ? AND lt.is_active = 1
            ORDER BY lt.topic_order
        """, (chapter_id,)).fetchall()

    finally:
        conn.close()

    return render_template('students/chapter.html',
                           chapter=chapter, topics=topics, company=company)


# ---------------------------------------------------------------------------
# Topic — view content
# ---------------------------------------------------------------------------
@students_bp.route('/topic/<int:topic_id>')
@limiter.exempt
@student_login_required
def topic_view(topic_id):
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        topic = conn.execute("""
            SELECT lt.*, lc.chapter_title, lc.id AS chapter_id,
                   lc.program_id, lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ? AND lt.is_active = 1
        """, (topic_id,)).fetchone()

        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('students.dashboard'))

        # Verify program access
        access = _has_program_access(conn, topic['program_id'], student_id)

        if not access:
            flash('You do not have access to this program.', 'danger')
            return redirect(url_for('students.dashboard'))

        # If this program uses the master library, find the matching master topic
        # and redirect there so progress is stored in the correct table.
        if _program_has_master_content(conn, topic['program_id']):
            master_topic = conn.execute("""
                SELECT mt.id
                FROM lms_master_topics mt
                JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                WHERE pc.program_id = ?
                  AND mt.title = ?
                  AND mt.status = 'active'
                  AND mc.status = 'active'
                  AND pc.is_visible = 1
                LIMIT 1
            """, (topic['program_id'], topic['topic_title'])).fetchone()
            if master_topic:
                return redirect(url_for('students.master_topic_view',
                                        program_id=topic['program_id'],
                                        master_topic_id=master_topic['id']))

        contents = conn.execute("""
            SELECT * FROM lms_topic_contents
            WHERE topic_id = ?
            ORDER BY display_order
        """, (topic_id,)).fetchall()

        # Extract single item of each type (one-per-type system)
        video_content = next((c for c in contents if c['content_mode'] == 'youtube'), None)
        lesson_content = next((c for c in contents if c['content_mode'] in ('pdf', 'rich_text', 'interactive_image')), None)

        # Previous / next topic in same chapter
        all_topics = conn.execute("""
            SELECT id FROM lms_topics
            WHERE chapter_id = ? AND is_active = 1
            ORDER BY topic_order
        """, (topic['chapter_id'],)).fetchall()
        ids = [r['id'] for r in all_topics]
        idx = ids.index(topic_id) if topic_id in ids else -1
        prev_topic_id = ids[idx - 1] if idx > 0 else None
        next_topic_id = ids[idx + 1] if idx >= 0 and idx < len(ids) - 1 else None

        # Build embed URLs for YouTube content
        embed_urls = {}
        for c in contents:
            if c['content_mode'] == 'youtube':
                embed_urls[c['id']] = _youtube_embed(c['external_url'])

        # Full curriculum for sidebar: all chapters + topics for this program
        chapters_sidebar = conn.execute("""
            SELECT id, chapter_title, chapter_order
            FROM lms_chapters
            WHERE program_id = ? AND is_active = 1
            ORDER BY chapter_order
        """, (topic['program_id'],)).fetchall()

        sidebar_topics = conn.execute("""
            SELECT lt.id, lt.topic_title, lt.topic_order, lt.chapter_id,
                   CASE WHEN tp.is_completed = 1 THEN 1 ELSE 0 END AS is_completed
            FROM lms_topics lt
            LEFT JOIN lms_topic_progress tp
                ON tp.topic_id = lt.id AND tp.student_id = ?
            WHERE lt.is_active = 1
              AND lt.chapter_id IN (
                  SELECT id FROM lms_chapters WHERE program_id = ? AND is_active = 1
              )
            ORDER BY lt.chapter_id, lt.topic_order
        """, (student_id, topic['program_id'])).fetchall()

        # Group sidebar topics by chapter_id
        topics_by_chapter = {}
        for t in sidebar_topics:
            topics_by_chapter.setdefault(t['chapter_id'], []).append(t)

        chapter_mock_map = _legacy_mock_status_by_chapter(
            conn,
            student_id,
            [chapter['id'] for chapter in chapters_sidebar],
        )

        # Progress counts
        total_topics = len(sidebar_topics)
        completed_topics = sum(1 for t in sidebar_topics if t['is_completed'])

        # Is current topic completed?
        current_completed = conn.execute(
            "SELECT is_completed FROM lms_topic_progress WHERE student_id=? AND topic_id=?",
            (student_id, topic_id)
        ).fetchone()
        is_completed = current_completed and current_completed['is_completed'] == 1

    finally:
        conn.close()

    return render_template('students/topic.html',
                           topic=topic, contents=contents,
                           embed_urls=embed_urls,
                           video_content=video_content,
                           lesson_content=lesson_content,
                           prev_topic_id=prev_topic_id,
                           next_topic_id=next_topic_id,
                           chapters_sidebar=chapters_sidebar,
                           topics_by_chapter=topics_by_chapter,
                           chapter_mock_map=chapter_mock_map,
                           total_topics=total_topics,
                           completed_topics=completed_topics,
                           is_completed=is_completed,
                           is_master_topic=False,
                           progress_endpoint=url_for('students.mark_complete', topic_id=topic_id),
                           topic_base_route='legacy',
                           company=company)


@students_bp.route('/program/<int:program_id>/master-topic/<int:master_topic_id>')
@limiter.exempt
@student_login_required
def master_topic_view(program_id, master_topic_id):
    """Student topic viewer for reusable master topics (program-scoped progress)."""
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        access = _has_program_access(conn, program_id, student_id)
        if not access:
            flash('You do not have access to this program.', 'danger')
            return redirect(url_for('students.dashboard'))

        topic = conn.execute(
            """
                SELECT
                    mt.id,
                    mt.title AS topic_title,
                    mt.short_description,
                    mt.topic_order,
                    mt.master_chapter_id AS chapter_id,
                    COALESCE(pc.custom_title, mc.title) AS chapter_title,
                    pc.chapter_order,
                    lp.id AS program_id,
                    lp.program_name
                FROM lms_master_topics mt
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                JOIN lms_program_chapters pc
                    ON pc.master_chapter_id = mt.master_chapter_id
                   AND pc.program_id = ?
                JOIN lms_programs lp ON lp.id = pc.program_id
                WHERE mt.id = ?
                  AND pc.is_visible = 1
                  AND mc.status = 'active'
                  AND mt.status = 'active'
                LIMIT 1
            """,
            (program_id, master_topic_id)
        ).fetchone()

        if not topic:
            flash('Topic not found in this program.', 'danger')
            return redirect(url_for('students.program_view', program_id=program_id))

        _save_last_master_topic(conn, student_id, program_id, master_topic_id)
        conn.commit()

        completion_locked_by_assignment = _has_approved_assignment(
            conn, student_id, program_id, master_topic_id
        )
        if completion_locked_by_assignment:
            conn.execute(
                """
                    INSERT INTO lms_master_topic_progress (
                        student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, datetime('now'), datetime('now'), datetime('now'))
                    ON CONFLICT(student_id, program_id, master_topic_id)
                    DO UPDATE SET
                        is_completed = 1,
                        completed_at = datetime('now'),
                        updated_at = datetime('now')
                """,
                (student_id, program_id, master_topic_id)
            )
            conn.commit()

        contents = conn.execute(
            """
                SELECT *
                FROM lms_topic_contents
                WHERE master_topic_id = ?
                ORDER BY display_order
            """,
            (master_topic_id,)
        ).fetchall()

        video_content = next((c for c in contents if c['content_mode'] == 'youtube'), None)
        lesson_content = next((c for c in contents if c['content_mode'] in ('pdf', 'rich_text', 'interactive_image')), None)

        chapters_sidebar, sidebar_topics, topics_by_chapter = _master_curriculum_sidebar(conn, program_id, student_id)
        chapter_mock_map = _master_mock_status_by_chapter(
            conn,
            student_id,
            [chapter['id'] for chapter in chapters_sidebar],
        )

        ordered_topic_ids = [r['id'] for r in sidebar_topics]
        idx = ordered_topic_ids.index(master_topic_id) if master_topic_id in ordered_topic_ids else -1
        prev_topic_id = ordered_topic_ids[idx - 1] if idx > 0 else None
        next_topic_id = ordered_topic_ids[idx + 1] if idx >= 0 and idx < len(ordered_topic_ids) - 1 else None

        embed_urls = {}
        for c in contents:
            if c['content_mode'] == 'youtube':
                embed_urls[c['id']] = _youtube_embed(c['external_url'])

        total_topics = len(sidebar_topics)
        completed_topics = sum(1 for t in sidebar_topics if t['is_completed'])

        current_completed = conn.execute(
            """
                SELECT is_completed
                FROM lms_master_topic_progress
                WHERE student_id = ? AND program_id = ? AND master_topic_id = ?
            """,
            (student_id, program_id, master_topic_id)
        ).fetchone()
        is_completed = bool(
            (current_completed and current_completed['is_completed'] == 1)
            or completion_locked_by_assignment
        )

    finally:
        conn.close()

    return render_template(
        'students/topic.html',
        topic=topic,
        contents=contents,
        embed_urls=embed_urls,
        video_content=video_content,
        lesson_content=lesson_content,
        prev_topic_id=prev_topic_id,
        next_topic_id=next_topic_id,
        chapters_sidebar=chapters_sidebar,
        topics_by_chapter=topics_by_chapter,
        chapter_mock_map=chapter_mock_map,
        total_topics=total_topics,
        completed_topics=completed_topics,
        is_completed=is_completed,
        completion_locked_by_assignment=completion_locked_by_assignment,
        is_master_topic=True,
        progress_endpoint=url_for('students.mark_master_complete', program_id=program_id, master_topic_id=master_topic_id),
        topic_base_route='master',
        company=company,
    )


# ---------------------------------------------------------------------------
# Mark topic as complete / incomplete (AJAX POST)
# ---------------------------------------------------------------------------
_COMPLETION_CONFIRMATION_TEXT = {
    'complete': 'Completed',
    'incomplete': 'Not Completed',
}


def _validate_completion_action_confirmation(action):
    expected_text = _COMPLETION_CONFIRMATION_TEXT.get(action)
    if not expected_text:
        return 'Invalid completion action.'

    confirmation_text = (request.form.get('confirmation_text') or '').strip()
    if confirmation_text.upper() != expected_text.upper():
        return f'Type "{expected_text}" to confirm this change.'

    return None


@students_bp.route('/topic/<int:topic_id>/complete', methods=['POST'])
@limiter.exempt
@student_login_required
def mark_complete(topic_id):
    from flask import jsonify
    if _is_demo():
        return jsonify({'status': 'demo', 'message': 'Read-only in demo mode'})
    student_id = session['student_id']
    action = (request.form.get('action', 'complete') or 'complete').strip().lower()
    confirmation_error = _validate_completion_action_confirmation(action)
    if confirmation_error:
        return jsonify({'status': 'error', 'message': confirmation_error}), 400

    conn = get_conn()
    try:
        if action == 'complete':
            conn.execute("""
                INSERT INTO lms_topic_progress (student_id, topic_id, is_completed, completed_at)
                VALUES (?, ?, 1, datetime('now'))
                ON CONFLICT(student_id, topic_id) DO UPDATE SET is_completed=1, completed_at=datetime('now')
            """, (student_id, topic_id))
        else:
            conn.execute("""
                INSERT INTO lms_topic_progress (student_id, topic_id, is_completed)
                VALUES (?, ?, 0)
                ON CONFLICT(student_id, topic_id) DO UPDATE SET is_completed=0, completed_at=NULL
            """, (student_id, topic_id))
        mock_url = (
            _completed_legacy_chapter_mock_url(conn, student_id, topic_id)
            if action == 'complete'
            else None
        )
        conn.commit()
        return jsonify({'status': 'ok', 'action': action, 'next_topic_url': mock_url})
    finally:
        conn.close()


@students_bp.route('/program/<int:program_id>/master-topic/<int:master_topic_id>/complete', methods=['POST'])
@limiter.exempt
@student_login_required
def mark_master_complete(program_id, master_topic_id):
    from flask import jsonify
    if _is_demo():
        return jsonify({'status': 'demo', 'message': 'Read-only in demo mode'})

    student_id = session['student_id']
    action = (request.form.get('action', 'complete') or 'complete').strip().lower()
    confirmation_error = _validate_completion_action_confirmation(action)
    if confirmation_error:
        return jsonify({'status': 'error', 'message': confirmation_error}), 400

    conn = get_conn()
    try:
        access = _has_program_access(conn, program_id, student_id)
        if not access:
            return jsonify({'status': 'error', 'message': 'No access'}), 403

        in_program = conn.execute(
            """
                SELECT 1
                FROM lms_program_chapters pc
                JOIN lms_master_topics mt ON mt.master_chapter_id = pc.master_chapter_id
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE pc.program_id = ?
                  AND mt.id = ?
                  AND pc.is_visible = 1
                  AND mc.status = 'active'
                  AND mt.status = 'active'
                LIMIT 1
            """,
            (program_id, master_topic_id)
        ).fetchone()

        if not in_program:
            return jsonify({'status': 'error', 'message': 'Topic not in program'}), 404

        next_master_topic_id = _next_master_topic_for_program(conn, program_id, master_topic_id)
        next_topic_url = (
            url_for(
                'students.master_topic_view',
                program_id=program_id,
                master_topic_id=next_master_topic_id,
            )
            if next_master_topic_id
            else None
        )

        assignment_locked = _has_approved_assignment(conn, student_id, program_id, master_topic_id)
        if assignment_locked:
            conn.execute(
                """
                    INSERT INTO lms_master_topic_progress (
                        student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, datetime('now'), datetime('now'), datetime('now'))
                    ON CONFLICT(student_id, program_id, master_topic_id)
                    DO UPDATE SET
                        is_completed = 1,
                        completed_at = datetime('now'),
                        updated_at = datetime('now')
                """,
                (student_id, program_id, master_topic_id)
            )
            if next_master_topic_id and action == 'complete':
                _save_last_master_topic(conn, student_id, program_id, next_master_topic_id)
            mock_url = (
                _completed_master_chapter_mock_url(conn, student_id, program_id, master_topic_id)
                if action == 'complete'
                else None
            )
            if mock_url:
                next_topic_url = mock_url
            conn.commit()
            if action != 'complete':
                return jsonify({
                    'status': 'locked',
                    'message': 'This topic is completed because your assignment was approved. It cannot be marked as not completed.'
                })
            return jsonify({
                'status': 'ok',
                'action': 'complete',
                'locked': True,
                'next_topic_url': next_topic_url,
                'message': None if next_topic_url else 'You have completed all topics.'
            })

        if action == 'complete':
            conn.execute(
                """
                    INSERT INTO lms_master_topic_progress (
                        student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, datetime('now'), datetime('now'), datetime('now'))
                    ON CONFLICT(student_id, program_id, master_topic_id)
                    DO UPDATE SET
                        is_completed = 1,
                        completed_at = datetime('now'),
                        updated_at = datetime('now')
                """,
                (student_id, program_id, master_topic_id)
            )
            if next_master_topic_id:
                _save_last_master_topic(conn, student_id, program_id, next_master_topic_id)
            mock_url = _completed_master_chapter_mock_url(conn, student_id, program_id, master_topic_id)
            if mock_url:
                next_topic_url = mock_url
        else:
            conn.execute(
                """
                    INSERT INTO lms_master_topic_progress (
                        student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 0, NULL, datetime('now'), datetime('now'))
                    ON CONFLICT(student_id, program_id, master_topic_id)
                    DO UPDATE SET
                        is_completed = 0,
                        completed_at = NULL,
                        updated_at = datetime('now')
                """,
                (student_id, program_id, master_topic_id)
            )

        conn.commit()
        return jsonify({
            'status': 'ok',
            'action': action,
            'next_topic_url': next_topic_url if action == 'complete' else None,
            'message': (
                'You have completed all topics.'
                if action == 'complete' and not next_topic_url
                else None
            )
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Serve protected PDF (login required, path never in HTML)
# ---------------------------------------------------------------------------
@students_bp.route('/content/<int:content_id>/pdf')
@student_login_required
def serve_pdf(content_id):
    import os
    from flask import send_from_directory
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT file_path FROM lms_topic_contents WHERE id = ? AND content_mode = 'pdf'",
            (content_id,)
        ).fetchone()
        if not row or not row['file_path']:
            return 'Not found', 404
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        abs_path = os.path.join(base_dir, row['file_path'].replace('/', os.sep))
        resp = send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path),
                                   mimetype='application/pdf')
        resp.headers['Content-Disposition'] = 'inline'
        resp.headers['Cache-Control'] = 'no-store, no-cache'
        return resp
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Serve protected interactive image
# ---------------------------------------------------------------------------
@students_bp.route('/content/<int:content_id>/image')
@student_login_required
def serve_image(content_id):
    import os
    from flask import send_from_directory
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT file_path FROM lms_topic_contents WHERE id = ? AND content_mode = 'interactive_image'",
            (content_id,)
        ).fetchone()
        if not row or not row['file_path']:
            return 'Not found', 404
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        abs_path = os.path.join(base_dir, row['file_path'].replace('/', os.sep))
        ext = abs_path.rsplit('.', 1)[-1].lower()
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                    'gif': 'image/gif', 'webp': 'image/webp'}
        mimetype = mime_map.get(ext, 'image/jpeg')
        resp = send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path),
                                   mimetype=mimetype)
        resp.headers['Cache-Control'] = 'no-store, no-cache'
        return resp
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Serve protected download file
# ---------------------------------------------------------------------------
@students_bp.route('/content/<int:content_id>/download')
@student_login_required
def serve_download(content_id):
    import os
    from flask import send_from_directory
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT file_path, content_title FROM lms_topic_contents WHERE id = ? AND content_mode = 'download'",
            (content_id,)
        ).fetchone()
        if not row or not row['file_path']:
            return 'Not found', 404
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        abs_path = os.path.join(base_dir, row['file_path'].replace('/', os.sep))
        filename = os.path.basename(abs_path)
        return send_from_directory(os.path.dirname(abs_path), filename,
                                   as_attachment=True, download_name=filename)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Student profile
# ---------------------------------------------------------------------------
@students_bp.route('/profile')
@student_login_required
def profile():
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()

        # Enrolled batches
        batches = conn.execute("""
            SELECT sb.*, b.batch_name, b.start_date, b.end_date,
                   c.course_name
            FROM student_batches sb
            JOIN batches b ON sb.batch_id = b.id
            LEFT JOIN courses c ON b.course_id = c.id
            WHERE sb.student_id = ?
            ORDER BY sb.joined_on DESC
        """, (student_id,)).fetchall()

        # Courses enrolled via invoice (not already covered by a batch)
        invoice_courses = conn.execute("""
            SELECT DISTINCT c.course_name, i.invoice_no, i.invoice_date
            FROM invoices i
            JOIN invoice_items ii ON ii.invoice_id = i.id
            JOIN courses c ON c.id = ii.course_id
            WHERE i.student_id = ?
              AND NOT EXISTS (
                SELECT 1 FROM student_batches sb
                JOIN batches b ON sb.batch_id = b.id
                WHERE sb.student_id = ? AND b.course_id = c.id
              )
            ORDER BY i.invoice_date DESC
        """, (student_id, student_id)).fetchall()

        # Invoices with paid amount summed from receipts
        invoices = conn.execute("""
            SELECT i.invoice_no, i.invoice_date, i.total_amount, i.status,
                   COALESCE((SELECT SUM(r.amount_received) FROM receipts r WHERE r.invoice_id = i.id), 0) AS paid_amount,
                   i.total_amount 
                   - COALESCE((SELECT SUM(r.amount_received) FROM receipts r WHERE r.invoice_id = i.id), 0)
                   - COALESCE((SELECT SUM(w.amount_written_off) FROM bad_debt_writeoffs w WHERE w.invoice_id = i.id), 0) AS balance_amount
            FROM invoices i
            WHERE i.student_id = ?
            ORDER BY i.invoice_date DESC
        """, (student_id,)).fetchall()

        # Fetch uploaded documents
        uploaded_docs = conn.execute(
            "SELECT * FROM student_uploaded_documents WHERE student_id = ?",
            (student_id,)
        ).fetchall()
        docs_by_cat = {d['category']: d for d in uploaded_docs}

        # Fetch pending update requests
        pending_update = conn.execute(
            "SELECT * FROM student_profile_update_requests WHERE student_id = ? AND status = 'PENDING' LIMIT 1",
            (student_id,)
        ).fetchone()

        profile_score = calculate_profile_score(student, uploaded_docs)

        from modules.billing.routes import QUALIFICATION_LEVELS

    finally:
        conn.close()

    return render_template('students/profile.html',
                           student=student, batches=batches,
                           invoice_courses=invoice_courses,
                           invoices=invoices, company=company,
                           docs_by_cat=docs_by_cat,
                           pending_update=pending_update,
                           profile_score=profile_score,
                           qualification_levels=QUALIFICATION_LEVELS)


def calculate_profile_score(student, uploaded_docs):
    """Calculate the profile completion percentage from 0 to 100 based on 22 criteria."""
    if not student:
        return 0
    
    student_dict = dict(student)
    uploaded_cats = {d['category'] for d in uploaded_docs}
    
    fields_to_check = [
        'full_name', 'phone', 'email', 'address', 'gender', 'education_level', 
        'qualification', 'employment_status', 'date_of_birth', 'parent_name', 
        'parent_contact', 'father_name', 'mother_name', 'tenth_institution', 
        'tenth_percentage', 'puc_institution', 'puc_percentage',
        'student_signature_filename', 'parent_signature_filename'
    ]
    
    filled_count = 0
    for field in fields_to_check:
        val = student_dict.get(field)
        if val is not None and str(val).strip() != "":
            filled_count += 1
            
    if 'qualification' in uploaded_cats:
        filled_count += 1
    if 'identity' in uploaded_cats:
        filled_count += 1
    if 'address' in uploaded_cats:
        filled_count += 1
        
    total_items = len(fields_to_check) + 3
    return int((filled_count / total_items) * 100)


@students_bp.route('/profile/upload-document', methods=['POST'])
@student_login_required
def profile_upload_document():
    student_id = session['student_id']
    category = request.form.get('category')
    doc_type = request.form.get('document_type')
    
    if category not in ('qualification', 'identity', 'address') or not doc_type:
        flash('Invalid document category or type.', 'danger')
        return redirect(url_for('students.profile'))
        
    if 'document_file' not in request.files:
        flash('No file uploaded.', 'danger')
        return redirect(url_for('students.profile'))
        
    file = request.files['document_file']
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('students.profile'))
        
    # Check extension
    allowed_exts = {'.pdf', '.png', '.jpg', '.jpeg'}
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in allowed_exts:
        flash('Invalid file format. Only PDF, PNG, JPG, and JPEG are allowed.', 'danger')
        return redirect(url_for('students.profile'))
        
    # Ensure upload folder exists
    upload_dir = os.path.abspath(os.path.join("uploads", "student_documents"))
    os.makedirs(upload_dir, exist_ok=True)
    
    # Save file with a secure, unique filename
    unique_fn = f"doc_{student_id}_{category}_{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(upload_dir, unique_fn)
    file.save(dest_path)
    
    # Database update
    conn = get_conn()
    try:
        # Check if record exists for this category, update it or insert new one
        existing = conn.execute(
            "SELECT id, file_path FROM student_uploaded_documents WHERE student_id = ? AND category = ?",
            (student_id, category)
        ).fetchone()
        
        if existing:
            # Optionally delete old file
            try:
                old_path = os.path.abspath(existing['file_path'])
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                pass
            conn.execute(
                """
                UPDATE student_uploaded_documents
                SET document_type = ?, file_path = ?, uploaded_at = datetime('now')
                WHERE id = ?
                """,
                (doc_type, dest_path, existing['id'])
            )
        else:
            conn.execute(
                """
                INSERT INTO student_uploaded_documents (student_id, category, document_type, file_path)
                VALUES (?, ?, ?, ?)
                """,
                (student_id, category, doc_type, dest_path)
            )
        conn.commit()
        flash('Document uploaded successfully.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Database error: {str(e)}', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('students.profile'))


@students_bp.route('/profile/request-update', methods=['POST'])
@student_login_required
def profile_request_update():
    student_id = session['student_id']
    conn = get_conn()
    try:
        # 1. Fetch current student details
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        
        # Check 3 approved updates limit
        if student.get('profile_approved_updates_count', 0) >= 3:
            flash('You have reached the maximum limit of 3 approved profile updates.', 'danger')
            return redirect(url_for('students.profile'))
            
        # Check if there is already a PENDING request
        pending = conn.execute(
            "SELECT id FROM student_profile_update_requests WHERE student_id = ? AND status = 'PENDING' LIMIT 1",
            (student_id,)
        ).fetchone()
        if pending:
            flash('You already have a pending profile update request.', 'warning')
            return redirect(url_for('students.profile'))
            
        # 2. Gather allowed fields from form
        allowed_fields = [
            'full_name', 'phone', 'email', 'address', 'gender', 'education_level', 
            'qualification', 'employment_status', 'date_of_birth', 'parent_name', 
            'parent_contact', 'father_name', 'mother_name', 'tenth_institution', 
            'tenth_board', 'tenth_year', 'tenth_percentage', 'puc_institution', 
            'puc_board', 'puc_stream', 'puc_year', 'puc_percentage'
        ]
        
        requested_data = {}
        for field in allowed_fields:
            val = request.form.get(field, '').strip()
            # Compare with current value to only request changes for modified fields
            curr_val = str(student[field]) if student[field] is not None else ''
            if val != curr_val:
                requested_data[field] = val
                
        if not requested_data:
            flash('No changes were made to your profile.', 'info')
            return redirect(url_for('students.profile'))
            
        # 3. Save pending request
        import json
        conn.execute(
            """
            INSERT INTO student_profile_update_requests (student_id, requested_data, status)
            VALUES (?, ?, 'PENDING')
            """,
            (student_id, json.dumps(requested_data))
        )
        conn.commit()
        flash('Your profile update request has been submitted for staff approval.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Database error: {str(e)}', 'danger')
    finally:
        conn.close()
        
    return redirect(url_for('students.profile'))


@students_bp.route('/change-password', methods=['GET', 'POST'])
@student_login_required
def change_password():
    student_id = session['student_id']

    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        if _is_demo():
            flash('Demo mode is read-only. Password changes are disabled.', 'warning')
            return redirect(url_for('students.dashboard'))

        if request.method == 'POST':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not current_password or not new_password or not confirm_password:
                flash('All password fields are required.', 'danger')
                return redirect(url_for('students.change_password'))

            if new_password != confirm_password:
                flash('New password and confirm password do not match.', 'danger')
                return redirect(url_for('students.change_password'))

            student = conn.execute(
                """
                SELECT id, password_hash, student_code
                FROM students
                WHERE id = ? AND status != 'dropped' AND portal_enabled = 1
                """,
                (student_id,)
            ).fetchone()

            if not student or not student['password_hash']:
                flash('Your portal account is not eligible for password change.', 'danger')
                return redirect(url_for('students.change_password'))

            if not check_password_hash(student['password_hash'], current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('students.change_password'))

            if check_password_hash(student['password_hash'], new_password):
                flash('New password must be different from current password.', 'danger')
                return redirect(url_for('students.change_password'))

            policy_error = _validate_student_password_policy(new_password, student['student_code'])
            if policy_error:
                flash(policy_error, 'danger')
                return redirect(url_for('students.change_password'))

            new_password_hash = generate_password_hash(new_password)
            conn.execute(
                "UPDATE students SET password_hash = ? WHERE id = ?",
                (new_password_hash, student_id)
            )
            conn.commit()
            session['student_force_password_change'] = False
            flash('Password changed successfully.', 'success')
            response = redirect(url_for('students.dashboard'))
            if session.get('student_session_mode') == 'mobile_app':
                response = _set_student_mobile_cookie(response, {
                    'id': student_id,
                    'student_code': student['student_code'],
                    'password_hash': new_password_hash,
                })
            return response
    finally:
        conn.close()

    return render_template('students/change_password.html', company=company)


# ---------------------------------------------------------------------------
# Leave Requests — Apply
# ---------------------------------------------------------------------------
@students_bp.route('/leave/apply', methods=['GET', 'POST'])
@student_login_required
def leave_apply():
    """Student applies for leave."""
    student_id = session['student_id']

    # Demo mode — block all writes; just show the form as a preview
    if _is_demo() and request.method == 'POST':
        flash('Demo mode is read-only. Leave requests cannot be submitted.', 'warning')
        return redirect(url_for('students.leave_apply'))

    if request.method == 'POST':
        from_date = request.form.get('from_date', '').strip()
        to_date   = request.form.get('to_date', '').strip()
        reason    = request.form.get('reason', '').strip()

        # --- Basic validation ---
        if not from_date or not to_date:
            flash('Please select a valid date range.', 'danger')
            return redirect(url_for('students.leave_apply'))

        if not reason:
            flash('Please provide a reason for the leave.', 'danger')
            return redirect(url_for('students.leave_apply'))

        today = datetime.now().strftime('%Y-%m-%d')
        if from_date < today:
            flash('Leave start date cannot be in the past.', 'danger')
            return redirect(url_for('students.leave_apply'))

        if from_date > to_date:
            flash('From date cannot be later than To date.', 'danger')
            return redirect(url_for('students.leave_apply'))

        # --- Duplicate / overlap check ---
        # Block new requests that overlap any existing pending or approved leave.
        # Overlap condition: existing.from_date <= new.to_date AND existing.to_date >= new.from_date
        conn = get_conn()
        try:
            overlap = conn.execute("""
                SELECT id FROM leave_requests
                WHERE student_id = ?
                  AND status IN ('pending', 'approved')
                  AND date(from_date) <= date(?)
                  AND date(to_date)   >= date(?)
            """, (student_id, to_date, from_date)).fetchone()
        finally:
            conn.close()

        if overlap:
            flash(
                'You already have a pending or approved leave request that overlaps these dates. '
                'Please check your leave history.',
                'danger'
            )
            return redirect(url_for('students.leave_apply'))

        # --- Optional document upload ---
        document_filename = None
        doc_file = request.files.get('document')
        if doc_file and doc_file.filename:
            allowed_ext = {'jpg', 'jpeg', 'png', 'pdf'}
            ext = doc_file.filename.rsplit('.', 1)[-1].lower() if '.' in doc_file.filename else ''
            if ext not in allowed_ext:
                flash('Invalid file type. Allowed: jpg, jpeg, png, pdf.', 'danger')
                return redirect(url_for('students.leave_apply'))

            # Check file size (5 MB max) — read into memory once
            doc_file.seek(0, 2)   # seek to end
            file_size = doc_file.tell()
            doc_file.seek(0)       # reset
            if file_size > 5 * 1024 * 1024:
                flash('Document too large. Maximum size is 5 MB.', 'danger')
                return redirect(url_for('students.leave_apply'))

            from config import LEAVE_DOCS_DIR
            safe_name = secure_filename(doc_file.filename)
            unique_name = f"{uuid.uuid4().hex}_{safe_name}"
            doc_file.save(os.path.join(LEAVE_DOCS_DIR, unique_name))
            document_filename = unique_name

        # --- Save to DB ---
        now = datetime.now().isoformat(timespec="seconds")
        conn = get_conn()
        try:
            conn.execute("""
                INSERT INTO leave_requests
                    (student_id, from_date, to_date, reason, document_filename,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (student_id, from_date, to_date, reason, document_filename, now, now))
            conn.commit()
        finally:
            conn.close()

        flash('Leave request submitted successfully! You will be notified once it is reviewed.', 'success')
        return redirect(url_for('students.leave_history'))

    return render_template('students/leave_apply.html')


# ---------------------------------------------------------------------------
# Leave Requests — History
# ---------------------------------------------------------------------------
@students_bp.route('/leave/history')
@student_login_required
def leave_history():
    """Student views their own leave request history."""
    student_id = session['student_id']

    # Demo mode — show sample leave records so the UI is visible
    if _is_demo():
        from datetime import date, timedelta
        today = date.today()
        demo_leaves = [
            {
                'id': 1,
                'from_date': (today - timedelta(days=20)).isoformat(),
                'to_date':   (today - timedelta(days=18)).isoformat(),
                'reason': 'Family function \u2014 attending a relatives wedding.',
                'document_filename': None,
                'status': 'approved',
                'review_notes': 'Approved. Enjoy the occasion!',
                'reviewed_by_name': 'Staff (Demo)',
                'reviewed_at': (today - timedelta(days=19)).isoformat(),
                'created_at': (today - timedelta(days=21)).isoformat(),
            },
            {
                'id': 2,
                'from_date': (today - timedelta(days=5)).isoformat(),
                'to_date':   (today - timedelta(days=4)).isoformat(),
                'reason': 'Medical appointment and rest.',
                'document_filename': None,
                'status': 'rejected',
                'review_notes': 'Insufficient notice. Please apply at least 3 days in advance.',
                'reviewed_by_name': 'Staff (Demo)',
                'reviewed_at': (today - timedelta(days=5)).isoformat(),
                'created_at': (today - timedelta(days=6)).isoformat(),
            },
            {
                'id': 3,
                'from_date': (today + timedelta(days=3)).isoformat(),
                'to_date':   (today + timedelta(days=5)).isoformat(),
                'reason': 'Personal work — need a few days off.',
                'document_filename': None,
                'status': 'pending',
                'review_notes': None,
                'reviewed_by_name': None,
                'reviewed_at': None,
                'created_at': today.isoformat(),
            },
        ]
        return render_template('students/leave_history.html', leaves=demo_leaves, is_demo=True)

    conn = get_conn()
    try:
        # Only fetch this student's own requests — never expose other students' data
        leaves = conn.execute("""
            SELECT lr.*,
                   u.full_name AS reviewed_by_name
            FROM leave_requests lr
            LEFT JOIN users u ON u.id = lr.reviewed_by
            WHERE lr.student_id = ?
            ORDER BY lr.created_at DESC
        """, (student_id,)).fetchall()
    finally:
        conn.close()

    return render_template('students/leave_history.html', leaves=leaves)


# ---------------------------------------------------------------------------
# Student Notes (per content item)
# ---------------------------------------------------------------------------

def _student_can_access_content(conn, content_id, student_id):
    """Return True if the content item belongs to any program the student can access."""
    tc = conn.execute(
        "SELECT master_topic_id FROM lms_topic_contents WHERE id = ?",
        (content_id,)
    ).fetchone()
    if not tc or not tc['master_topic_id']:
        return False
    mt = conn.execute(
        "SELECT master_chapter_id FROM lms_master_topics WHERE id = ?",
        (tc['master_topic_id'],)
    ).fetchone()
    if not mt:
        return False
    programs = conn.execute(
        "SELECT program_id FROM lms_program_chapters WHERE master_chapter_id = ?",
        (mt['master_chapter_id'],)
    ).fetchall()
    return any(_has_program_access(conn, p['program_id'], student_id) for p in programs)


@students_bp.route('/notes/content/<int:content_id>', methods=['GET'])
@limiter.exempt
@student_login_required
def get_student_note(content_id):
    from flask import jsonify
    student_id = session['student_id']
    conn = get_conn()
    try:
        if not _student_can_access_content(conn, content_id, student_id):
            return jsonify({'error': 'Access denied'}), 403
        row = conn.execute(
            "SELECT note_body, strftime('%Y-%m-%d %H:%M', updated_at) AS updated_at "
            "FROM student_notes WHERE student_id = ? AND content_id = ?",
            (student_id, content_id)
        ).fetchone()
        if row:
            return jsonify({'note_body': row['note_body'], 'updated_at': row['updated_at']})
        return jsonify({'note_body': '', 'updated_at': None})
    finally:
        conn.close()


@students_bp.route('/notes/content/<int:content_id>', methods=['POST'])
@limiter.exempt
@student_login_required
def save_student_note(content_id):
    from flask import jsonify
    import bleach
    if _is_demo():
        return jsonify({'ok': False, 'error': 'Read-only in demo mode'}), 403

    student_id = session['student_id']
    data = request.get_json(silent=True)
    if not data or 'note_body' not in data:
        return jsonify({'ok': False, 'error': 'Missing note_body'}), 400

    allowed_tags = ['b', 'i', 'u', 'ul', 'ol', 'li', 'p', 'br', 'strong', 'em']
    clean_body = bleach.clean(data['note_body'], tags=allowed_tags, strip=True)

    conn = get_conn()
    try:
        if not _student_can_access_content(conn, content_id, student_id):
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        conn.execute(
            """
            INSERT INTO student_notes (student_id, content_id, note_body, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(student_id, content_id) DO UPDATE
                SET note_body = excluded.note_body,
                    updated_at = datetime('now')
            """,
            (student_id, content_id, clean_body)
        )
        conn.commit()
        row = conn.execute(
            "SELECT strftime('%Y-%m-%d %H:%M', updated_at) AS updated_at "
            "FROM student_notes WHERE student_id = ? AND content_id = ?",
            (student_id, content_id)
        ).fetchone()
        return jsonify({'ok': True, 'updated_at': row['updated_at'] if row else None})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LMS Assignments — Student
# ---------------------------------------------------------------------------

_SUBMISSION_ALLOWED_EXTS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'jpg', 'jpeg', 'png'}
_SUBMISSION_MAX_BYTES     = 20 * 1024 * 1024   # 20 MB


def _save_submission_file(file_obj):
    """Save a student submission to instance/uploads/submissions/.
    Returns (ok, unique_filename_or_error, original_name)."""
    orig_name = file_obj.filename or ''
    filename  = secure_filename(orig_name)
    if not filename:
        return False, 'Invalid filename.', ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in _SUBMISSION_ALLOWED_EXTS:
        return False, f'File type .{ext} not allowed. Use PDF, DOC, DOCX, or image.', ''
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > _SUBMISSION_MAX_BYTES:
        return False, f'File too large ({size / 1048576:.1f} MB). Max 20 MB.', ''
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'uploads', 'submissions')
    )
    os.makedirs(base_dir, exist_ok=True)
    unique_name = datetime.now().strftime('%Y%m%d_%H%M%S_') + filename
    file_obj.save(os.path.join(base_dir, unique_name))
    return True, unique_name, orig_name


@students_bp.route('/program/<int:program_id>/master-topic/<int:master_topic_id>/assignments')
@limiter.exempt
@student_login_required
def get_topic_assignments(program_id, master_topic_id):
    from flask import jsonify
    student_id = session['student_id']
    conn = get_conn()
    try:
        if not _has_program_access(conn, program_id, student_id):
            return jsonify({'error': 'Access denied'}), 403
        assignments = conn.execute("""
            SELECT id, title, description, original_filename, file_path,
                   strftime('%Y-%m-%d', created_at) AS created_at
            FROM   lms_assignments
            WHERE  master_topic_id = ?
            ORDER  BY created_at
        """, (master_topic_id,)).fetchall()
        result = []
        for a in assignments:
            sub = conn.execute("""
                SELECT id, status, review_status, rejection_reason,
                       original_filename, feedback,
                       strftime('%d %b %Y %H:%M', submitted_at) AS submitted_at,
                       strftime('%d %b %Y %H:%M', reviewed_at)  AS reviewed_at
                FROM   lms_assignment_submissions
                WHERE  assignment_id = ? AND student_id = ? AND is_latest = 1
            """, (a['id'], student_id)).fetchone()
            result.append({
                'id':                a['id'],
                'title':             a['title'],
                'description':       a['description'] or '',
                'original_filename': a['original_filename'] or '',
                'has_file':          bool(a['file_path']),
                'created_at':        a['created_at'],
                'submission':        dict(sub) if sub else None,
            })
        return jsonify({'assignments': result})
    finally:
        conn.close()


@students_bp.route('/assignments/<int:assignment_id>/submit', methods=['POST'])
@student_login_required
def submit_assignment(assignment_id):
    from flask import jsonify
    if _is_demo():
        return jsonify({'ok': False, 'error': 'Read-only in demo mode'}), 403

    student_id = session['student_id']
    conn = get_conn()
    try:
        a = conn.execute(
            "SELECT master_topic_id FROM lms_assignments WHERE id = ?",
            (assignment_id,)
        ).fetchone()
        if not a:
            return jsonify({'ok': False, 'error': 'Assignment not found'}), 404
        mt = conn.execute(
            "SELECT master_chapter_id FROM lms_master_topics WHERE id = ?",
            (a['master_topic_id'],)
        ).fetchone()
        if not mt:
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        programs = conn.execute(
            "SELECT program_id FROM lms_program_chapters WHERE master_chapter_id = ?",
            (mt['master_chapter_id'],)
        ).fetchall()
        if not any(_has_program_access(conn, p['program_id'], student_id) for p in programs):
            return jsonify({'ok': False, 'error': 'Access denied'}), 403

        # Check re-upload permission based on latest submission review_status
        existing = conn.execute("""
            SELECT id, review_status
            FROM   lms_assignment_submissions
            WHERE  assignment_id = ? AND student_id = ? AND is_latest = 1
        """, (assignment_id, student_id)).fetchone()

        if existing:
            rs = existing['review_status'] or 'submitted'
            if rs == 'submitted':
                return jsonify({'ok': False,
                                'error': 'Your assignment is pending review. Re-upload is not allowed until staff reviews it.'}), 403
            if rs == 'accepted':
                return jsonify({'ok': False,
                                'error': 'Your assignment has been accepted. Re-upload is not allowed.'}), 403
            # rs == 'rejected' — allowed to re-upload

        file_obj = request.files.get('submission_file')
        if not file_obj or not file_obj.filename:
            return jsonify({'ok': False, 'error': 'No file uploaded'}), 400

        ok, path_or_err, orig_name = _save_submission_file(file_obj)
        if not ok:
            return jsonify({'ok': False, 'error': path_or_err}), 400

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Mark previous submission (if any) as not latest
        if existing:
            conn.execute(
                "UPDATE lms_assignment_submissions SET is_latest = 0 WHERE id = ?",
                (existing['id'],)
            )

        # Insert new submission row
        conn.execute("""
            INSERT INTO lms_assignment_submissions
                (assignment_id, student_id, file_path, original_filename,
                 status, review_status, submitted_at, updated_at, is_latest)
            VALUES (?, ?, ?, ?, 'submitted', 'submitted', ?, ?, 1)
        """, (assignment_id, student_id, path_or_err, orig_name, now, now))
        conn.commit()
        return jsonify({'ok': True, 'status': 'submitted', 'review_status': 'submitted',
                        'submitted_at': now[:16], 'original_filename': orig_name})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@students_bp.route('/assignments/file/<int:assignment_id>')
@student_login_required
def download_assignment_file(assignment_id):
    from flask import send_file, abort
    student_id = session['student_id']
    conn = get_conn()
    try:
        a = conn.execute(
            "SELECT master_topic_id, file_path, original_filename FROM lms_assignments WHERE id = ?",
            (assignment_id,)
        ).fetchone()
        if not a or not a['file_path']:
            abort(404)
        mt = conn.execute(
            "SELECT master_chapter_id FROM lms_master_topics WHERE id = ?",
            (a['master_topic_id'],)
        ).fetchone()
        if not mt:
            abort(403)
        programs = conn.execute(
            "SELECT program_id FROM lms_program_chapters WHERE master_chapter_id = ?",
            (mt['master_chapter_id'],)
        ).fetchall()
        if not any(_has_program_access(conn, p['program_id'], student_id) for p in programs):
            abort(403)
        file_path = a['file_path']
        orig_name = a['original_filename'] or file_path
    finally:
        conn.close()
    base_dir  = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'uploads', 'assignments')
    )
    full_path = os.path.join(base_dir, file_path)
    if not os.path.isfile(full_path):
        abort(404)
    return send_file(full_path, as_attachment=True, download_name=orig_name)


@students_bp.route('/submissions/file/<int:submission_id>')
@student_login_required
def download_own_submission(submission_id):
    from flask import send_file, abort
    student_id = session['student_id']
    conn = get_conn()
    try:
        sub = conn.execute(
            "SELECT student_id, file_path, original_filename FROM lms_assignment_submissions WHERE id = ?",
            (submission_id,)
        ).fetchone()
        if not sub or sub['student_id'] != student_id:
            abort(403)
        file_path = sub['file_path']
        orig_name = sub['original_filename'] or file_path
    finally:
        conn.close()
    base_dir  = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'uploads', 'submissions')
    )
    full_path = os.path.join(base_dir, file_path)
    if not os.path.isfile(full_path):
        abort(404)
    return send_file(full_path, as_attachment=True, download_name=orig_name)


# ---------------------------------------------------------------------------
# Attendance Calendar
# ---------------------------------------------------------------------------
@students_bp.route('/attendance')
@student_login_required
def attendance_calendar():
    """Student views their complete attendance history in calendar format."""
    import json
    student_id = session['student_id']
    conn = get_conn()
    try:
        # Demo mode — use the first real student's attendance so the calendar is meaningful
        if _is_demo():
            demo_row = conn.execute("""
                SELECT student_id FROM attendance_records
                ORDER BY attendance_date DESC LIMIT 1
            """).fetchone()
            student_id = demo_row['student_id'] if demo_row else 0

        records = conn.execute("""
            SELECT ar.attendance_date,
                   ar.status,
                   ar.remarks,
                   b.batch_name
            FROM attendance_records ar
            JOIN batches b ON b.id = ar.batch_id
            WHERE ar.student_id = ?
            ORDER BY ar.attendance_date ASC
        """, (student_id,)).fetchall()

        # Summary counts
        total = len(records)
        present = sum(1 for r in records if r['status'] == 'present')
        late    = sum(1 for r in records if r['status'] == 'late')
        leave   = sum(1 for r in records if r['status'] == 'leave')
        absent  = sum(1 for r in records if r['status'] == 'absent')

        # Build a dict keyed by date for JS consumption
        # If a student has 2 batches on same day, concatenate
        cal_data = {}
        for r in records:
            d = r['attendance_date']
            if d not in cal_data:
                cal_data[d] = {'status': r['status'], 'batches': [r['batch_name']]}
            else:
                # If statuses differ, prefer: present > late > leave > absent
                priority = {'present': 4, 'late': 3, 'leave': 2, 'absent': 1}
                if priority.get(r['status'], 0) > priority.get(cal_data[d]['status'], 0):
                    cal_data[d]['status'] = r['status']
                cal_data[d]['batches'].append(r['batch_name'])

        cal_json = json.dumps(cal_data)
    finally:
        conn.close()

    return render_template(
        'students/attendance_calendar.html',
        cal_json=cal_json,
        total=total,
        present=present,
        late=late,
        leave=leave,
        absent=absent,
    )


@students_bp.route('/profile/save-signature', methods=['POST'])
@student_login_required
def profile_save_signature():
    import base64
    student_id = session['student_id']
    sig_type = request.form.get('sig_type')
    sig_data = request.form.get('sig_data')

    if sig_type not in ('student', 'parent') or not sig_data:
        return {"success": False, "error": "Invalid signature details."}, 400

    conn = get_conn()
    try:
        student = conn.execute("SELECT student_code FROM students WHERE id = ?", (student_id,)).fetchone()
        if not student:
            return {"success": False, "error": "Student not found."}, 404

        if ',' in sig_data:
            sig_data = sig_data.split(',')[1]
        sig_bytes = base64.b64decode(sig_data)

        sig_dir = os.path.join("static", "images", "student_signatures")
        os.makedirs(sig_dir, exist_ok=True)

        code = student["student_code"]
        filename = f"{code}_{sig_type}_signature.png"
        filepath = os.path.join(sig_dir, filename)
        with open(filepath, "wb") as f:
            f.write(sig_bytes)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if sig_type == "student":
            conn.execute(
                "UPDATE students SET student_signature_filename=?, student_signature_date=?, updated_at=? WHERE id=?",
                (filename, now, now, student_id)
            )
        else:
            conn.execute(
                "UPDATE students SET parent_signature_filename=?, parent_signature_date=?, updated_at=? WHERE id=?",
                (filename, now, now, student_id)
            )
        conn.commit()
        return {"success": True, "filename": filename, "signed_at": now}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500
    finally:
        conn.close()

