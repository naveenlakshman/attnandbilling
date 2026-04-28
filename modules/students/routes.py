from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from datetime import datetime
import urllib.parse
from db import get_conn
from . import students_bp


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------
def student_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'student_id' not in session:
            flash('Please log in to access the student portal.', 'warning')
            return redirect(url_for('students.login'))
        return f(*args, **kwargs)
    return decorated


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


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------
@students_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'student_id' in session:
        return redirect(url_for('students.dashboard'))

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
            session['student_id'] = student['id']
            session['student_name'] = student['full_name']
            session['student_code'] = student['student_code']
            return redirect(url_for('students.dashboard'))

        flash('Invalid Student ID or password.', 'danger')

    return render_template('students/login.html', company=company)


@students_bp.route('/logout')
def logout():
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('student_code', None)
    return redirect(url_for('students.login'))


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

        # Programs accessible via:
        # 1. Direct lms_student_program_access record
        # 2. Batch membership + lms_batch_program_access
        # 3. Invoice for the course (invoice_items → course_id → lms_programs.course_id)
        programs = conn.execute("""
            SELECT DISTINCT
                lp.id, lp.program_name, lp.description,
                (
                    SELECT COUNT(*) FROM lms_chapters lc WHERE lc.program_id = lp.id AND lc.is_active = 1
                ) AS chapter_count,
                (
                    SELECT COUNT(*) FROM lms_topics lt
                    JOIN lms_chapters lc2 ON lt.chapter_id = lc2.id
                    WHERE lc2.program_id = lp.id AND lt.is_active = 1
                ) AS topic_count,
                (
                    SELECT COUNT(*) FROM lms_topic_progress tp2
                    JOIN lms_topics lt2 ON tp2.topic_id = lt2.id
                    JOIN lms_chapters lc3 ON lt2.chapter_id = lc3.id
                    WHERE lc3.program_id = lp.id AND tp2.student_id = ? AND tp2.is_completed = 1
                ) AS completed_count,
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
            WHERE lp.is_active = 1
            AND (
                EXISTS (
                    SELECT 1 FROM lms_student_program_access spa
                    WHERE spa.student_id = ? AND spa.program_id = lp.id
                      AND spa.is_active = 1
                      AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM lms_batch_program_access bpa
                    JOIN student_batches sb ON bpa.batch_id = sb.batch_id
                    WHERE sb.student_id = ? AND bpa.program_id = lp.id
                      AND bpa.is_active = 1
                      AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE i.student_id = ? AND ii.course_id = lp.course_id
                      AND lp.course_id IS NOT NULL
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    JOIN lms_course_program_map cpm
                         ON cpm.course_id = ii.course_id AND cpm.program_id = lp.id
                    WHERE i.student_id = ?
                )
            )
            ORDER BY CASE WHEN map_order IS NULL THEN 1 ELSE 0 END, map_order, lp.program_name
        """, (student_id, student_id, student_id, student_id, student_id, student_id, student_id)).fetchall()

    finally:
        conn.close()

    return render_template('students/dashboard.html',
                           programs=programs, company=company)


# ---------------------------------------------------------------------------
# Program — chapter list
# ---------------------------------------------------------------------------
@students_bp.route('/program/<int:program_id>')
@student_login_required
def program_view(program_id):
    student_id = session['student_id']
    conn = get_conn()
    try:
        company = conn.execute("SELECT * FROM company_profile LIMIT 1").fetchone()

        # Verify access
        access = conn.execute("""
            SELECT 1 FROM lms_programs lp
            WHERE lp.id = ? AND lp.is_active = 1
            AND (
                EXISTS (
                    SELECT 1 FROM lms_student_program_access spa
                    WHERE spa.student_id = ? AND spa.program_id = lp.id AND spa.is_active = 1
                      AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM lms_batch_program_access bpa
                    JOIN student_batches sb ON bpa.batch_id = sb.batch_id
                    WHERE sb.student_id = ? AND bpa.program_id = lp.id AND bpa.is_active = 1
                      AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE i.student_id = ? AND ii.course_id = lp.course_id
                      AND lp.course_id IS NOT NULL
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    JOIN lms_course_program_map cpm
                         ON cpm.course_id = ii.course_id AND cpm.program_id = lp.id
                    WHERE i.student_id = ?
                )
            )
        """, (program_id, student_id, student_id, student_id, student_id)).fetchone()

        if not access:
            flash('You do not have access to this program.', 'danger')
            return redirect(url_for('students.dashboard'))

        program = conn.execute("SELECT * FROM lms_programs WHERE id = ?", (program_id,)).fetchone()

        # Find the first topic in the program (redirect Tally-style directly into viewer)
        first_topic = conn.execute("""
            SELECT lt.id FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            WHERE lc.program_id = ? AND lc.is_active = 1 AND lt.is_active = 1
            ORDER BY lc.chapter_order, lt.topic_order
            LIMIT 1
        """, (program_id,)).fetchone()

        # Also get chapters for fallback
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
    if first_topic:
        return redirect(url_for('students.topic_view', topic_id=first_topic['id']))

    # Fallback: show chapter list if no topics exist
    return render_template('students/program.html',
                           program=program, chapters=chapters, company=company)


# ---------------------------------------------------------------------------
# Chapter — topic list
# ---------------------------------------------------------------------------
@students_bp.route('/chapter/<int:chapter_id>')
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
        access = conn.execute("""
            SELECT 1 FROM lms_programs lp
            WHERE lp.id = ? AND lp.is_active = 1
            AND (
                EXISTS (
                    SELECT 1 FROM lms_student_program_access spa
                    WHERE spa.student_id = ? AND spa.program_id = lp.id AND spa.is_active = 1
                      AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM lms_batch_program_access bpa
                    JOIN student_batches sb ON bpa.batch_id = sb.batch_id
                    WHERE sb.student_id = ? AND bpa.program_id = lp.id AND bpa.is_active = 1
                      AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE i.student_id = ? AND ii.course_id = lp.course_id
                      AND lp.course_id IS NOT NULL
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    JOIN lms_course_program_map cpm
                         ON cpm.course_id = ii.course_id AND cpm.program_id = lp.id
                    WHERE i.student_id = ?
                )
            )
        """, (chapter['program_id'], student_id, student_id, student_id, student_id)).fetchone()

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
        access = conn.execute("""
            SELECT 1 FROM lms_programs lp
            WHERE lp.id = ? AND lp.is_active = 1
            AND (
                EXISTS (
                    SELECT 1 FROM lms_student_program_access spa
                    WHERE spa.student_id = ? AND spa.program_id = lp.id AND spa.is_active = 1
                      AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM lms_batch_program_access bpa
                    JOIN student_batches sb ON bpa.batch_id = sb.batch_id
                    WHERE sb.student_id = ? AND bpa.program_id = lp.id AND bpa.is_active = 1
                      AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE i.student_id = ? AND ii.course_id = lp.course_id
                      AND lp.course_id IS NOT NULL
                )
                OR EXISTS (
                    SELECT 1 FROM invoices i
                    JOIN invoice_items ii ON ii.invoice_id = i.id
                    JOIN lms_course_program_map cpm
                         ON cpm.course_id = ii.course_id AND cpm.program_id = lp.id
                    WHERE i.student_id = ?
                )
            )
        """, (topic['program_id'], student_id, student_id, student_id, student_id)).fetchone()

        if not access:
            flash('You do not have access to this program.', 'danger')
            return redirect(url_for('students.dashboard'))

        contents = conn.execute("""
            SELECT * FROM lms_topic_contents
            WHERE topic_id = ?
            ORDER BY display_order
        """, (topic_id,)).fetchall()

        # Extract single item of each type (one-per-type system)
        video_content = next((c for c in contents if c['content_mode'] == 'youtube'), None)
        lesson_content = next((c for c in contents if c['content_mode'] in ('pdf', 'rich_text', 'interactive_image')), None)
        download_content = next((c for c in contents if c['content_mode'] == 'download'), None)

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
                           download_content=download_content,
                           prev_topic_id=prev_topic_id,
                           next_topic_id=next_topic_id,
                           chapters_sidebar=chapters_sidebar,
                           topics_by_chapter=topics_by_chapter,
                           total_topics=total_topics,
                           completed_topics=completed_topics,
                           is_completed=is_completed,
                           company=company)


# ---------------------------------------------------------------------------
# Mark topic as complete / incomplete (AJAX POST)
# ---------------------------------------------------------------------------
@students_bp.route('/topic/<int:topic_id>/complete', methods=['POST'])
@student_login_required
def mark_complete(topic_id):
    from flask import jsonify
    student_id = session['student_id']
    action = request.form.get('action', 'complete')  # 'complete' or 'incomplete'
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
        conn.commit()
        return jsonify({'status': 'ok', 'action': action})
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
                   i.total_amount - COALESCE((SELECT SUM(r.amount_received) FROM receipts r WHERE r.invoice_id = i.id), 0) AS balance_amount
            FROM invoices i
            WHERE i.student_id = ?
            ORDER BY i.invoice_date DESC
        """, (student_id,)).fetchall()

    finally:
        conn.close()

    return render_template('students/profile.html',
                           student=student, batches=batches,
                           invoice_courses=invoice_courses,
                           invoices=invoices, company=company)
