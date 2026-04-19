from flask import render_template, request, jsonify, send_from_directory
from . import lms_admin_bp
from db import get_conn, log_activity
from functools import wraps
from flask import session, redirect, url_for, flash
from datetime import datetime
import re
import os
from werkzeug.utils import secure_filename
from config import Config

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('core.login'))
        return f(*args, **kwargs)
    return decorated_function


# File Upload Handler
def upload_file(file_obj, content_type):
    """
    Save uploaded file to static/lms/<subdir>/ and return the Flask static path.
    content_type: 'pdf' or 'download'
    Returns: (success: bool, path_or_error: str)
    """
    if not file_obj or file_obj.filename == '':
        return False, f"No file selected"

    allowed_exts = {
        'pdf':      {'pdf'},
        'download': {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'txt', 'ppt', 'pptx'},
    }
    max_sizes = {
        'pdf':      50 * 1024 * 1024,   # 50 MB
        'download': 100 * 1024 * 1024,  # 100 MB
    }

    filename = secure_filename(file_obj.filename)
    if not filename:
        return False, "Invalid filename"

    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    exts = allowed_exts.get(content_type, set())
    if file_ext not in exts:
        return False, f"File type .{file_ext} not allowed. Allowed: {', '.join(sorted(exts))}"

    file_obj.seek(0, os.SEEK_END)
    file_size = file_obj.tell()
    file_obj.seek(0)
    max_size = max_sizes.get(content_type, 50 * 1024 * 1024)
    if file_size > max_size:
        return False, f"File too large ({file_size/(1024*1024):.1f} MB). Max: {max_size/(1024*1024):.0f} MB"

    subdir = 'pdfs' if content_type == 'pdf' else 'downloads'
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'lms', subdir))
    os.makedirs(base_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
    unique_filename = timestamp + filename
    full_path = os.path.join(base_dir, unique_filename)

    try:
        file_obj.save(full_path)
        # Store as Flask static path: static/lms/pdfs/filename or static/lms/downloads/filename
        return True, f"static/lms/{subdir}/{unique_filename}"
    except Exception as e:
        return False, f"Error saving file: {str(e)}"


@lms_admin_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    """LMS Admin Dashboard - Phase 1: LMS Structure Setup"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get counts for dashboard metrics
        cur.execute("SELECT COUNT(*) as count FROM lms_programs")
        total_programs = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM lms_chapters")
        total_chapters = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM lms_topics")
        total_topics = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM lms_mock_tests")
        total_tests = cur.fetchone()['count']
        
        # Get recent LMS activity (last 10 records)
        cur.execute("""
            SELECT 
                al.id,
                al.action_type,
                al.module_name,
                al.description,
                al.created_at,
                u.full_name
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE al.module_name LIKE '%lms%'
            ORDER BY al.created_at DESC
            LIMIT 10
        """)
        recent_activity = cur.fetchall()
        
        metrics = {
            'total_programs': total_programs,
            'total_chapters': total_chapters,
            'total_topics': total_topics,
            'total_tests': total_tests,
            'recent_activity': recent_activity
        }
        
        return render_template('lms_dashboard.html', metrics=metrics)
    finally:
        conn.close()


@lms_admin_bp.route('/programs', methods=['GET'])
@login_required
def list_programs():
    """List all LMS Programs with chapter count and details"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get all programs with related information
        cur.execute("""
            SELECT 
                lp.id,
                lp.program_name,
                lp.slug,
                lp.description,
                lp.is_published,
                lp.is_active,
                lp.created_at,
                lp.updated_at,
                c.course_name,
                COUNT(DISTINCT lc.id) as chapter_count
            FROM lms_programs lp
            LEFT JOIN courses c ON lp.course_id = c.id
            LEFT JOIN lms_chapters lc ON lp.id = lc.program_id
            GROUP BY lp.id
            ORDER BY lp.created_at DESC
        """)
        programs = cur.fetchall()
        
        return render_template('lms_programs.html', programs=programs)
    finally:
        conn.close()


def generate_slug(title):
    """Generate URL-friendly slug from title"""
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


@lms_admin_bp.route('/program/new', methods=['GET', 'POST'])
@login_required
def program_new():
    """Add new LMS program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        if request.method == 'POST':
            program_name = request.form.get('program_name', '').strip()
            course_id = request.form.get('course_id', '')
            slug = request.form.get('slug', '').strip()
            description = request.form.get('description', '').strip()
            thumbnail_path = request.form.get('thumbnail_path', '').strip()
            is_published = request.form.get('is_published', 0)
            
            # Validate program name
            if not program_name:
                flash('Program name is required.', 'danger')
                return redirect(url_for('lms_admin.program_new'))
            
            # Generate slug if not provided or if program name changed
            if not slug or slug == '':
                slug = generate_slug(program_name)
            
            # Check if slug already exists
            cur.execute("""
                SELECT id FROM lms_programs WHERE slug = ?
            """, (slug,))
            if cur.fetchone():
                flash('This slug already exists. Please use a different one.', 'danger')
                return redirect(url_for('lms_admin.program_new'))
            
            # Convert course_id to None if empty
            course_id = int(course_id) if course_id and course_id != '' else None
            is_published = 1 if is_published == 'on' or is_published == '1' else 0
            
            now = datetime.now().isoformat(timespec='seconds')
            
            cur.execute("""
                INSERT INTO lms_programs (
                    course_id,
                    program_name,
                    slug,
                    description,
                    thumbnail_path,
                    is_published,
                    is_active,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                course_id,
                program_name,
                slug,
                description,
                thumbnail_path,
                is_published,
                1,
                session['user_id'],
                now,
                now
            ))
            
            program_id = cur.lastrowid
            
            conn.commit()
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_programs',
                record_id=program_id,
                description=f'Created LMS program: {program_name}'
            )
            
            flash('Program created successfully.', 'success')
            return redirect(url_for('lms_admin.list_programs'))
        
        # GET: Show form with courses
        cur.execute("""
            SELECT id, course_name
            FROM courses
            WHERE is_active = 1
            ORDER BY course_name ASC
        """)
        courses = cur.fetchall()
        
        return render_template('lms_program_form.html', program=None, courses=courses)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/edit', methods=['GET', 'POST'])
@login_required
def program_edit(program_id):
    """Edit existing LMS program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get program details
        cur.execute("""
            SELECT * FROM lms_programs WHERE id = ?
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            program_name = request.form.get('program_name', '').strip()
            course_id = request.form.get('course_id', '')
            slug = request.form.get('slug', '').strip()
            description = request.form.get('description', '').strip()
            thumbnail_path = request.form.get('thumbnail_path', '').strip()
            is_published = request.form.get('is_published', 0)
            
            # Validate program name
            if not program_name:
                flash('Program name is required.', 'danger')
                return redirect(url_for('lms_admin.program_edit', program_id=program_id))
            
            # Generate slug if not provided
            if not slug or slug == '':
                slug = generate_slug(program_name)
            
            # Check if slug already exists (excluding current program)
            cur.execute("""
                SELECT id FROM lms_programs WHERE slug = ? AND id != ?
            """, (slug, program_id))
            if cur.fetchone():
                flash('This slug already exists. Please use a different one.', 'danger')
                return redirect(url_for('lms_admin.program_edit', program_id=program_id))
            
            # Convert course_id to None if empty
            course_id = int(course_id) if course_id and course_id != '' else None
            is_published = 1 if is_published == 'on' or is_published == '1' else 0
            
            now = datetime.now().isoformat(timespec='seconds')
            
            cur.execute("""
                UPDATE lms_programs
                SET course_id = ?,
                    program_name = ?,
                    slug = ?,
                    description = ?,
                    thumbnail_path = ?,
                    is_published = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                course_id,
                program_name,
                slug,
                description,
                thumbnail_path,
                is_published,
                now,
                program_id
            ))
            
            conn.commit()
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='update',
                module_name='lms_programs',
                record_id=program_id,
                description=f'Updated LMS program: {program_name}'
            )
            
            flash('Program updated successfully.', 'success')
            return redirect(url_for('lms_admin.list_programs'))
        
        # GET: Show form with courses
        cur.execute("""
            SELECT id, course_name
            FROM courses
            WHERE is_active = 1
            ORDER BY course_name ASC
        """)
        courses = cur.fetchall()
        
        return render_template('lms_program_form.html', program=program, courses=courses)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/view', methods=['GET'])
@login_required
def program_view(program_id):
    """View detailed summary of a single LMS program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get program details with course info
        cur.execute("""
            SELECT 
                lp.id,
                lp.program_name,
                lp.slug,
                lp.description,
                lp.thumbnail_path,
                lp.is_published,
                lp.is_active,
                lp.created_at,
                lp.updated_at,
                lp.created_by,
                c.course_name,
                c.fee as course_fee
            FROM lms_programs lp
            LEFT JOIN courses c ON lp.course_id = c.id
            WHERE lp.id = ?
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get chapter count and list
        cur.execute("""
            SELECT 
                id,
                chapter_title,
                chapter_order,
                is_active,
                created_at,
                (SELECT COUNT(*) FROM lms_topics WHERE chapter_id = lms_chapters.id) as topic_count
            FROM lms_chapters
            WHERE program_id = ?
            ORDER BY chapter_order ASC
        """, (program_id,))
        chapters = cur.fetchall()
        total_chapters = len(chapters)
        
        # Get total topics count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topics
            WHERE chapter_id IN (
                SELECT id FROM lms_chapters WHERE program_id = ?
            )
        """, (program_id,))
        total_topics = cur.fetchone()['count']
        
        # Get total students assigned
        cur.execute("""
            SELECT COUNT(DISTINCT student_id) as count
            FROM lms_student_program_access
            WHERE program_id = ? AND access_status = 'active'
        """, (program_id,))
        total_students = cur.fetchone()['count']
        
        # Get total tests
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_mock_tests
            WHERE program_id = ? OR chapter_id IN (
                SELECT id FROM lms_chapters WHERE program_id = ?
            ) OR topic_id IN (
                SELECT id FROM lms_topics WHERE chapter_id IN (
                    SELECT id FROM lms_chapters WHERE program_id = ?
                )
            )
        """, (program_id, program_id, program_id))
        total_tests = cur.fetchone()['count']
        
        # Get resources
        cur.execute("""
            SELECT 
                id,
                resource_title,
                resource_type,
                file_path,
                is_active,
                created_at,
                updated_at
            FROM lms_program_resources
            WHERE program_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """, (program_id,))
        resources = cur.fetchall()
        
        # Get recent activity for this program
        cur.execute("""
            SELECT 
                al.id,
                al.action_type,
                al.description,
                al.created_at,
                u.full_name
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE al.module_name = 'lms_programs' AND al.record_id = ?
            ORDER BY al.created_at DESC
            LIMIT 5
        """, (program_id,))
        recent_activity = cur.fetchall()
        
        summary = {
            'program': program,
            'chapters': chapters,
            'total_chapters': total_chapters,
            'total_topics': total_topics,
            'total_students': total_students,
            'total_tests': total_tests,
            'resources': resources,
            'resource_count': len(resources),
            'recent_activity': recent_activity
        }
        
        return render_template('lms_program_view.html', summary=summary)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapters', methods=['GET'])
@login_required
def list_chapters(program_id):
    """List all chapters for a program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get program details
        cur.execute("""
            SELECT id, program_name, slug
            FROM lms_programs
            WHERE id = ?
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all chapters with topic count
        cur.execute("""
            SELECT 
                lc.id,
                lc.chapter_title,
                lc.chapter_order,
                lc.description,
                lc.is_active,
                lc.created_at,
                lc.updated_at,
                COUNT(DISTINCT lt.id) as topic_count
            FROM lms_chapters lc
            LEFT JOIN lms_topics lt ON lc.id = lt.chapter_id
            WHERE lc.program_id = ?
            GROUP BY lc.id
            ORDER BY lc.chapter_order ASC
        """, (program_id,))
        chapters = cur.fetchall()
        
        data = {
            'program': program,
            'chapters': chapters,
            'total_chapters': len(chapters)
        }
        
        return render_template('lms_chapters.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter/new', methods=['GET', 'POST'])
@login_required
def chapter_new(program_id):
    """Add new chapter to a program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get program details
        cur.execute("""
            SELECT id, program_name
            FROM lms_programs
            WHERE id = ?
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            chapter_title = request.form.get('chapter_title', '').strip()
            chapter_order = request.form.get('chapter_order', '1')
            description = request.form.get('description', '').strip()
            is_active = request.form.get('is_active', 0)
            
            # Validate chapter title
            if not chapter_title:
                flash('Chapter title is required.', 'danger')
                return redirect(url_for('lms_admin.chapter_new', program_id=program_id))
            
            # Convert order to integer
            try:
                chapter_order = int(chapter_order) if chapter_order else 1
            except ValueError:
                chapter_order = 1
            
            is_active = 1 if is_active == 'on' or is_active == '1' else 0
            
            now = datetime.now().isoformat(timespec='seconds')
            
            cur.execute("""
                INSERT INTO lms_chapters (
                    program_id,
                    chapter_title,
                    chapter_order,
                    description,
                    is_active,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                program_id,
                chapter_title,
                chapter_order,
                description,
                is_active,
                now,
                now
            ))
            
            chapter_id = cur.lastrowid
            conn.commit()
            
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_chapters',
                record_id=chapter_id,
                description=f'Created chapter: {chapter_title} for program {program["program_name"]}'
            )
            
            flash('Chapter created successfully.', 'success')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
        
        # GET: Get next chapter order
        cur.execute("""
            SELECT MAX(chapter_order) as max_order
            FROM lms_chapters
            WHERE program_id = ?
        """, (program_id,))
        result = cur.fetchone()
        next_order = (result['max_order'] or 0) + 1
        
        return render_template('lms_chapter_form.html', program=program, chapter=None, next_order=next_order)
    finally:
        conn.close()


@lms_admin_bp.route('/chapter/<int:chapter_id>/edit', methods=['GET', 'POST'])
@login_required
def chapter_edit(chapter_id):
    """Edit existing chapter"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get chapter and program details
        cur.execute("""
            SELECT 
                lc.id,
                lc.program_id,
                lc.chapter_title,
                lc.chapter_order,
                lc.description,
                lc.is_active,
                lc.created_at,
                lc.updated_at,
                lp.program_name
            FROM lms_chapters lc
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lc.id = ?
        """, (chapter_id,))
        chapter = cur.fetchone()
        
        if not chapter:
            flash('Chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get program details
        program = {
            'id': chapter['program_id'],
            'program_name': chapter['program_name']
        }
        
        if request.method == 'POST':
            chapter_title = request.form.get('chapter_title', '').strip()
            chapter_order = request.form.get('chapter_order', str(chapter['chapter_order']))
            description = request.form.get('description', '').strip()
            is_active = request.form.get('is_active', 0)
            
            # Validate chapter title
            if not chapter_title:
                flash('Chapter title is required.', 'danger')
                return redirect(url_for('lms_admin.chapter_edit', chapter_id=chapter_id))
            
            # Convert order to integer
            try:
                chapter_order = int(chapter_order) if chapter_order else 1
            except ValueError:
                chapter_order = 1
            
            is_active = 1 if is_active == 'on' or is_active == '1' else 0
            
            now = datetime.now().isoformat(timespec='seconds')
            
            cur.execute("""
                UPDATE lms_chapters
                SET chapter_title = ?,
                    chapter_order = ?,
                    description = ?,
                    is_active = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                chapter_title,
                chapter_order,
                description,
                is_active,
                now,
                chapter_id
            ))
            
            conn.commit()
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='update',
                module_name='lms_chapters',
                record_id=chapter_id,
                description=f'Updated chapter: {chapter_title} in program {chapter["program_name"]}'
            )
            
            flash('Chapter updated successfully.', 'success')
            return redirect(url_for('lms_admin.list_chapters', program_id=chapter['program_id']))
        
        return render_template('lms_chapter_form.html', program=program, chapter=chapter, next_order=None)
    finally:
        conn.close()


@lms_admin_bp.route('/chapter/<int:chapter_id>/delete', methods=['POST'])
@login_required
def delete_chapter(chapter_id):
    """Delete a chapter (soft delete pattern - set is_deleted flag)"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get chapter details
        cur.execute("""
            SELECT lc.id, lc.chapter_title, lc.program_id, lp.program_name
            FROM lms_chapters lc
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lc.id = ?
        """, (chapter_id,))
        chapter = cur.fetchone()
        
        if not chapter:
            flash('Chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Delete the chapter
        now = datetime.now().isoformat(timespec='seconds')
        cur.execute("""
            DELETE FROM lms_chapters
            WHERE id = ?
        """, (chapter_id,))
        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_chapters',
            record_id=chapter_id,
            description=f'Deleted chapter: {chapter["chapter_title"]} from program {chapter["program_name"]}'
        )
        
        flash('Chapter deleted successfully.', 'success')
        return redirect(url_for('lms_admin.list_chapters', program_id=chapter['program_id']))
    except Exception as e:
        flash(f'Error deleting chapter: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_chapters', program_id=chapter['program_id']))
    finally:
        conn.close()


@lms_admin_bp.route('/chapter/<int:chapter_id>/topics', methods=['GET'])
@login_required
def list_topics(chapter_id):
    """List all topics under a chapter"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get chapter, program details
        cur.execute("""
            SELECT 
                lc.id,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_chapters lc
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lc.id = ?
        """, (chapter_id,))
        chapter = cur.fetchone()
        
        if not chapter:
            flash('Chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all topics for this chapter with content count
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lt.short_description,
                lt.estimated_minutes,
                lt.content_type,
                lt.is_preview,
                lt.is_active,
                lt.created_at,
                lt.updated_at,
                COUNT(DISTINCT lc.id) as content_count
            FROM lms_topics lt
            LEFT JOIN lms_topic_contents lc ON lt.id = lc.topic_id
            WHERE lt.chapter_id = ?
            GROUP BY lt.id
            ORDER BY lt.topic_order ASC
        """, (chapter_id,))
        topics = cur.fetchall()
        
        # Get total topic count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topics
            WHERE chapter_id = ?
        """, (chapter_id,))
        total_topics = cur.fetchone()['count']
        
        data = {
            'program': {
                'id': chapter['program_id'],
                'program_name': chapter['program_name']
            },
            'chapter': chapter,
            'topics': topics,
            'total_topics': total_topics
        }
        
        return render_template('lms_topics.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/chapter/<int:chapter_id>/topic/new', methods=['GET', 'POST'])
@login_required
def topic_new(chapter_id):
    """Add new topic to a chapter"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get chapter and program details
        cur.execute("""
            SELECT 
                lc.id,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_chapters lc
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lc.id = ?
        """, (chapter_id,))
        chapter = cur.fetchone()
        
        if not chapter:
            flash('Chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            topic_title = request.form.get('topic_title', '').strip()
            topic_order = request.form.get('topic_order', '1')
            short_description = request.form.get('short_description', '').strip()
            estimated_minutes = request.form.get('estimated_minutes', '')
            content_type = request.form.get('content_type', 'video').strip() or 'video'
            is_preview = request.form.get('is_preview', 0)
            is_active = request.form.get('is_active', 0)
            
            # Validate topic title
            if not topic_title:
                flash('Topic title is required.', 'danger')
                return redirect(url_for('lms_admin.topic_new', chapter_id=chapter_id))
            
            # Validate content type
            valid_content_types = ['video', 'pdf', 'download']
            if content_type not in valid_content_types:
                content_type = 'video'
            
            # Convert order to integer
            try:
                topic_order = int(topic_order) if topic_order else 1
            except ValueError:
                topic_order = 1
            
            # Convert estimated_minutes to integer or None
            try:
                estimated_minutes = int(estimated_minutes) if estimated_minutes else None
            except ValueError:
                estimated_minutes = None
            
            # Convert checkbox values
            is_preview = 1 if is_preview == 'on' or is_preview == '1' else 0
            is_active = 1 if is_active == 'on' or is_active == '1' else 0
            
            now = datetime.now().isoformat(timespec='seconds')
            
            try:
                cur.execute("""
                    INSERT INTO lms_topics (
                        chapter_id,
                        topic_title,
                        topic_order,
                        short_description,
                        estimated_minutes,
                        content_type,
                        is_preview,
                        is_active,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chapter_id,
                    topic_title,
                    topic_order,
                    short_description,
                    estimated_minutes,
                    content_type,
                    is_preview,
                    is_active,
                    now,
                    now
                ))
            except Exception as e:
                print(f"ERROR inserting topic: {e}")
                print(f"Values: chapter_id={chapter_id}, topic_title={topic_title}, topic_order={topic_order}, content_type={content_type}, is_preview={is_preview}, is_active={is_active}")
                raise
            
            topic_id = cur.lastrowid
            conn.commit()
            
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_topics',
                record_id=topic_id,
                description=f'Created topic: {topic_title} in chapter {chapter["chapter_title"]}'
            )
            
            flash('Topic created successfully.', 'success')
            return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))
        
        # GET: Get next topic order
        cur.execute("""
            SELECT MAX(topic_order) as max_order
            FROM lms_topics
            WHERE chapter_id = ?
        """, (chapter_id,))
        result = cur.fetchone()
        next_order = (result['max_order'] or 0) + 1
        
        program = {
            'id': chapter['program_id'],
            'program_name': chapter['program_name']
        }
        
        return render_template('lms_topic_form.html', program=program, chapter=chapter, topic=None, next_order=next_order)
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/edit', methods=['GET', 'POST'])
@login_required
def topic_edit(topic_id):
    """Edit existing topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lt.short_description,
                lt.estimated_minutes,
                lt.content_type,
                lt.is_preview,
                lt.is_active,
                lt.created_at,
                lt.updated_at,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get chapter and program details
        chapter = {
            'id': topic['chapter_id'],
            'chapter_title': topic['chapter_title']
        }
        
        program = {
            'id': topic['program_id'],
            'program_name': topic['program_name']
        }
        
        if request.method == 'POST':
            topic_title = request.form.get('topic_title', '').strip()
            topic_order = request.form.get('topic_order', str(topic['topic_order']))
            short_description = request.form.get('short_description', '').strip()
            estimated_minutes = request.form.get('estimated_minutes', '')
            content_type = request.form.get('content_type', topic['content_type'])
            is_preview = request.form.get('is_preview', 0)
            is_active = request.form.get('is_active', 0)
            
            # Validate topic title
            if not topic_title:
                flash('Topic title is required.', 'danger')
                return redirect(url_for('lms_admin.topic_edit', topic_id=topic_id))
            
            # Validate content type
            if content_type not in ['video', 'pdf', 'download']:
                content_type = 'video'
            try:
                topic_order = int(topic_order) if topic_order else 1
            except ValueError:
                topic_order = 1
            
            # Convert estimated_minutes to integer or None
            try:
                estimated_minutes = int(estimated_minutes) if estimated_minutes else None
            except ValueError:
                estimated_minutes = None
            
            # Convert checkbox values
            is_preview = 1 if is_preview == 'on' or is_preview == '1' else 0
            is_active = 1 if is_active == 'on' or is_active == '1' else 0
            
            now = datetime.now().isoformat(timespec='seconds')
            
            cur.execute("""
                UPDATE lms_topics
                SET topic_title = ?,
                    topic_order = ?,
                    short_description = ?,
                    estimated_minutes = ?,
                    content_type = ?,
                    is_preview = ?,
                    is_active = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                topic_title,
                topic_order,
                short_description,
                estimated_minutes,
                content_type,
                is_preview,
                is_active,
                now,
                topic_id
            ))
            
            conn.commit()
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='update',
                module_name='lms_topics',
                record_id=topic_id,
                description=f'Updated topic: {topic_title} in chapter {topic["chapter_title"]}'
            )
            
            flash('Topic updated successfully.', 'success')
            return redirect(url_for('lms_admin.list_topics', chapter_id=topic['chapter_id']))
        
        return render_template('lms_topic_form.html', program=program, chapter=chapter, topic=topic, next_order=None)
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/delete', methods=['POST'])
@login_required
def delete_topic(topic_id):
    """Delete a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic details
        cur.execute("""
            SELECT lt.id, lt.topic_title, lt.chapter_id, lc.chapter_title
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Delete the topic
        cur.execute("""
            DELETE FROM lms_topics
            WHERE id = ?
        """, (topic_id,))
        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_topics',
            record_id=topic_id,
            description=f'Deleted topic: {topic["topic_title"]} from chapter {topic["chapter_title"]}'
        )
        
        flash('Topic deleted successfully.', 'success')
        return redirect(url_for('lms_admin.list_topics', chapter_id=topic['chapter_id']))
    except Exception as e:
        flash(f'Error deleting topic: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_topics', chapter_id=topic['chapter_id']))
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/view', methods=['GET'])
@login_required
def topic_view(topic_id):
    """View topic details with content"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lt.short_description,
                lt.estimated_minutes,
                lt.content_type,
                lt.is_preview,
                lt.is_active,
                lt.created_at,
                lt.updated_at,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all content items for this topic
        cur.execute("""
            SELECT 
                id,
                topic_id,
                content_mode,
                content_title,
                external_url,
                file_path,
                content_body,
                display_order,
                created_at,
                updated_at
            FROM lms_topic_contents
            WHERE topic_id = ?
            ORDER BY display_order ASC
        """, (topic_id,))
        content_items = cur.fetchall()
        
        # Get content count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topic_contents
            WHERE topic_id = ?
        """, (topic_id,))
        content_count = cur.fetchone()['count']
        
        # Get any associated tests (if any)
        cur.execute("""
            SELECT 
                id,
                test_title,
                description,
                total_marks,
                pass_marks,
                is_active,
                created_at
            FROM lms_mock_tests
            WHERE topic_id = ?
            ORDER BY created_at DESC
        """, (topic_id,))
        tests = cur.fetchall()
        
        # Get test count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_mock_tests
            WHERE topic_id = ?
        """, (topic_id,))
        test_count = cur.fetchone()['count']
        
        # Get recent activity for this topic
        cur.execute("""
            SELECT 
                al.id,
                al.action_type,
                al.description,
                al.created_at,
                u.full_name
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE al.module_name = 'lms_topics' 
            AND al.record_id = ?
            ORDER BY al.created_at DESC
            LIMIT 5
        """, (topic_id,))
        recent_activity = cur.fetchall()
        
        # Organize content by type
        content_by_type = {}
        for item in content_items:
            content_mode = item['content_mode']
            if content_mode not in content_by_type:
                content_by_type[content_mode] = []
            content_by_type[content_mode].append(item)
        
        data = {
            'topic': topic,
            'chapter': {
                'id': topic['chapter_id'],
                'chapter_title': topic['chapter_title']
            },
            'program': {
                'id': topic['program_id'],
                'program_name': topic['program_name']
            },
            'content_items': content_items,
            'content_by_type': content_by_type,
            'content_count': content_count,
            'tests': tests,
            'test_count': test_count,
            'recent_activity': recent_activity
        }
        
        return render_template('lms_topic_view.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/contents', methods=['GET'])
@login_required
def list_topic_contents(topic_id):
    """List all content items for a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all content items for this topic
        cur.execute("""
            SELECT 
                id,
                topic_id,
                content_mode,
                content_title,
                external_url,
                file_path,
                content_body,
                display_order,
                created_at,
                updated_at
            FROM lms_topic_contents
            WHERE topic_id = ?
            ORDER BY display_order ASC
        """, (topic_id,))
        content_items = cur.fetchall()
        
        # Get total content count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topic_contents
            WHERE topic_id = ?
        """, (topic_id,))
        total_content = cur.fetchone()['count']
        
        # Organize by content type
        content_by_type = {}
        for item in content_items:
            ctype = item['content_mode']
            if ctype not in content_by_type:
                content_by_type[ctype] = []
            content_by_type[ctype].append(item)
        
        data = {
            'program': {
                'id': topic['program_id'],
                'program_name': topic['program_name']
            },
            'chapter': {
                'id': topic['chapter_id'],
                'chapter_title': topic['chapter_title']
            },
            'topic': topic,
            'content_items': content_items,
            'content_by_type': content_by_type,
            'total_content': total_content
        }
        
        return render_template('lms_topic_contents.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/content', methods=['GET'])
@login_required
def topic_student_view(topic_id):
    """View how content is displayed to students in a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lt.short_description,
                lt.estimated_minutes,
                lt.content_type,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all content items for this topic in display order
        cur.execute("""
            SELECT 
                id,
                topic_id,
                content_mode,
                content_title,
                external_url,
                file_path,
                content_body,
                display_order,
                created_at,
                updated_at
            FROM lms_topic_contents
            WHERE topic_id = ?
            ORDER BY display_order ASC
        """, (topic_id,))
        contents = cur.fetchall()
        
        data = {
            'program': {
                'id': topic['program_id'],
                'program_name': topic['program_name']
            },
            'chapter': {
                'id': topic['chapter_id'],
                'chapter_title': topic['chapter_title']
            },
            'topic': topic,
            'contents': contents
        }
        
        return render_template('lms_admin/lms_topic_student_view.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/content/new', methods=['GET', 'POST'])
@login_required
def content_new(topic_id):
    """Add new content to a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content_mode = request.form.get('content_mode', 'youtube')
            description = request.form.get('content_body', '').strip()
            display_order = request.form.get('display_order', '1')
            external_url = request.form.get('external_url', '').strip()

            if not title:
                flash('Content title is required.', 'danger')
                return redirect(url_for('lms_admin.content_new', topic_id=topic_id))

            if content_mode not in ['youtube', 'pdf', 'download']:
                content_mode = 'youtube'

            try:
                display_order = int(display_order) if display_order else 1
            except ValueError:
                display_order = 1

            file_path = ''

            if content_mode == 'youtube':
                if not external_url:
                    flash('YouTube URL is required.', 'danger')
                    return redirect(url_for('lms_admin.content_new', topic_id=topic_id))

            elif content_mode in ['pdf', 'download']:
                file_field = 'pdf_file' if content_mode == 'pdf' else 'download_file'
                if file_field not in request.files or not request.files[file_field].filename:
                    flash('Please select a file to upload.', 'danger')
                    return redirect(url_for('lms_admin.content_new', topic_id=topic_id))
                success, result = upload_file(request.files[file_field], content_mode)
                if not success:
                    flash(f'Upload failed: {result}', 'danger')
                    return redirect(url_for('lms_admin.content_new', topic_id=topic_id))
                file_path = result

            now = datetime.now().isoformat(timespec='seconds')

            try:
                cur.execute("""
                    INSERT INTO lms_topic_contents (
                        topic_id, content_title, content_mode, content_body,
                        external_url, file_path, display_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    topic_id, title, content_mode, description,
                    external_url if content_mode == 'youtube' else '',
                    file_path, display_order, now, now
                ))

                content_id = cur.lastrowid

                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='create',
                    module_name='lms_topic_contents',
                    record_id=content_id,
                    description=f'Created content: {title} in topic {topic["topic_title"]}'
                )

                flash('Content added successfully.', 'success')
                return redirect(url_for('lms_admin.list_topic_contents', topic_id=topic_id))

            except Exception as e:
                flash(f'Error saving content: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.content_new', topic_id=topic_id))
        
        # GET: Get next content order
        cur.execute("""
            SELECT MAX(display_order) as max_order
            FROM lms_topic_contents
            WHERE topic_id = ?
        """, (topic_id,))
        result = cur.fetchone()
        next_order = (result['max_order'] or 0) + 1
        
        program = {
            'id': topic['program_id'],
            'program_name': topic['program_name']
        }
        
        chapter = {
            'id': topic['chapter_id'],
            'chapter_title': topic['chapter_title']
        }
        
        return render_template('lms_admin/lms_topic_content_form.html', program=program, chapter=chapter, topic=topic, content=None, next_order=next_order)
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/view', methods=['GET'])
@login_required
def content_view(content_id):
    """View content in read-only mode"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get content, topic, chapter and program details
        cur.execute("""
            SELECT 
                ltc.id,
                ltc.topic_id,
                ltc.content_mode,
                ltc.content_title,
                ltc.external_url,
                ltc.file_path,
                ltc.content_body,
                ltc.display_order,
                ltc.created_at,
                ltc.updated_at,
                lt.topic_title,
                lt.chapter_id,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topic_contents ltc
            JOIN lms_topics lt ON ltc.topic_id = lt.id
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE ltc.id = ?
        """, (content_id,))
        content = cur.fetchone()
        
        if not content:
            flash('Content not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        # Convert YouTube watch URL to embed URL
        embed_url = None
        if content['content_mode'] == 'youtube' and content['external_url']:
            raw = content['external_url'].strip()
            video_id = None
            # Handle youtu.be/VIDEO_ID
            if 'youtu.be/' in raw:
                video_id = raw.split('youtu.be/')[-1].split('?')[0].split('&')[0]
            # Handle youtube.com/watch?v=VIDEO_ID
            elif 'youtube.com/watch' in raw:
                import urllib.parse
                qs = urllib.parse.urlparse(raw).query
                params = urllib.parse.parse_qs(qs)
                video_id = params.get('v', [None])[0]
            # Already an embed URL
            elif 'youtube.com/embed/' in raw:
                embed_url = raw
            if video_id:
                embed_url = f'https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1&disablekb=0'

        # Format data for display
        return render_template('lms_admin/lms_topic_content_view.html',
                              content=content,
                              embed_url=embed_url,
                              is_preview=True)
    
    except Exception as e:
        flash(f'Error viewing content: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_programs'))
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/download', methods=['GET'])
@login_required
def serve_protected_file(content_id):
    """Serve a downloadable file without exposing the real path"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT file_path, content_title FROM lms_topic_contents WHERE id = ?", (content_id,))
        row = cur.fetchone()
        if not row or not row['file_path']:
            flash('File not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        # file_path stored as e.g. "static/lms/downloads/filename.zip"
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        abs_path = os.path.join(base_dir, row['file_path'].replace('/', os.sep))
        directory = os.path.dirname(abs_path)
        filename = os.path.basename(abs_path)
        return send_from_directory(directory, filename, as_attachment=True, download_name=filename)
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/pdf', methods=['GET'])
@login_required
def serve_pdf(content_id):
    """Serve PDF inline for PDF.js rendering — actual file path never exposed to browser"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM lms_topic_contents WHERE id = ? AND content_mode = 'pdf'", (content_id,))
        row = cur.fetchone()
        if not row or not row['file_path']:
            return "Not found", 404
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        abs_path = os.path.join(base_dir, row['file_path'].replace('/', os.sep))
        directory = os.path.dirname(abs_path)
        filename = os.path.basename(abs_path)
        response = send_from_directory(directory, filename, mimetype='application/pdf')
        response.headers['Content-Disposition'] = 'inline'
        response.headers['Cache-Control'] = 'no-store, no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/edit', methods=['GET', 'POST'])
@login_required
def content_edit(content_id):
    """Edit existing content"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get content, topic, chapter and program details
        cur.execute("""
            SELECT 
                ltc.id,
                ltc.topic_id,
                ltc.content_mode,
                ltc.content_title,
                ltc.external_url,
                ltc.file_path,
                ltc.content_body,
                ltc.display_order,
                ltc.created_at,
                ltc.updated_at,
                lt.topic_title,
                lt.chapter_id,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topic_contents ltc
            JOIN lms_topics lt ON ltc.topic_id = lt.id
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE ltc.id = ?
        """, (content_id,))
        content = cur.fetchone()
        
        if not content:
            flash('Content not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Format topic data
        topic = {
            'id': content['topic_id'],
            'topic_title': content['topic_title']
        }
        
        chapter = {
            'id': content['chapter_id'],
            'chapter_title': content['chapter_title']
        }
        
        program = {
            'id': content['program_id'],
            'program_name': content['program_name']
        }
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content_mode = request.form.get('content_mode', content['content_mode'])
            description = request.form.get('content_body', '').strip()
            display_order = request.form.get('display_order', str(content['display_order']))
            external_url = request.form.get('external_url', '').strip()
            file_path = content['file_path']  # keep existing by default

            if not title:
                flash('Content title is required.', 'danger')
                return redirect(url_for('lms_admin.content_edit', content_id=content_id))

            if content_mode not in ['youtube', 'pdf', 'download']:
                content_mode = 'youtube'

            try:
                display_order = int(display_order) if display_order else 1
            except ValueError:
                display_order = 1

            if content_mode == 'youtube':
                if not external_url:
                    flash('YouTube URL is required.', 'danger')
                    return redirect(url_for('lms_admin.content_edit', content_id=content_id))
                file_path = ''

            elif content_mode in ['pdf', 'download']:
                file_field = 'pdf_file' if content_mode == 'pdf' else 'download_file'
                if file_field in request.files and request.files[file_field].filename:
                    # Delete old file if it exists in static/lms/
                    if file_path and file_path.startswith('static/lms/'):
                        old_full = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), file_path)
                        if os.path.exists(old_full):
                            try:
                                os.remove(old_full)
                            except Exception:
                                pass
                    success, result = upload_file(request.files[file_field], content_mode)
                    if not success:
                        flash(f'Upload failed: {result}', 'danger')
                        return redirect(url_for('lms_admin.content_edit', content_id=content_id))
                    file_path = result
                external_url = ''

            now = datetime.now().isoformat(timespec='seconds')

            try:
                cur.execute("""
                    UPDATE lms_topic_contents
                    SET content_mode = ?, content_title = ?, external_url = ?,
                        file_path = ?, content_body = ?, display_order = ?, updated_at = ?
                    WHERE id = ?
                """, (content_mode, title, external_url, file_path, description, display_order, now, content_id))

                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='update',
                    module_name='lms_topic_contents',
                    record_id=content_id,
                    description=f'Updated content: {title} in topic {topic["topic_title"]}'
                )

                flash('Content updated successfully.', 'success')
                return redirect(url_for('lms_admin.list_topic_contents', topic_id=content['topic_id']))

            except Exception as e:
                flash(f'Error updating content: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.content_edit', content_id=content_id))
        
        return render_template('lms_admin/lms_topic_content_form.html', program=program, chapter=chapter, topic=topic, content=content, next_order=None)
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/delete', methods=['POST'])
@login_required
def delete_content(content_id):
    """Delete content from a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get content and topic details
        cur.execute("""
            SELECT ltc.id, ltc.content_title, ltc.topic_id, lt.topic_title
            FROM lms_topic_contents ltc
            JOIN lms_topics lt ON ltc.topic_id = lt.id
            WHERE ltc.id = ?
        """, (content_id,))
        content = cur.fetchone()
        
        if not content:
            flash('Content not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Delete the content
        cur.execute("""
            DELETE FROM lms_topic_contents
            WHERE id = ?
        """, (content_id,))
        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_topic_contents',
            record_id=content_id,
            description=f'Deleted content: {content["content_title"]} from topic {content["topic_title"]}'
        )
        
        flash('Content deleted successfully.', 'success')
        return redirect(url_for('lms_admin.list_topic_contents', topic_id=content['topic_id']))
    except Exception as e:
        flash(f'Error deleting content: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_topic_contents', topic_id=content['topic_id']))
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/attachments', methods=['GET'])
@login_required
def list_topic_attachments(topic_id):
    """List all attachments for a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all attachments for this topic
        cur.execute("""
            SELECT 
                id,
                topic_id,
                attachment_type,
                file_name,
                file_size,
                file_path,
                description,
                uploaded_by,
                is_required,
                created_at,
                updated_at
            FROM lms_topic_attachments
            WHERE topic_id = ?
            ORDER BY created_at DESC
        """, (topic_id,))
        attachments = cur.fetchall()
        
        # Get total attachments count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topic_attachments
            WHERE topic_id = ?
        """, (topic_id,))
        total_attachments = cur.fetchone()['count']
        
        # Calculate total file size
        total_size = 0
        for attachment in attachments:
            if attachment['file_size']:
                total_size += attachment['file_size']
        
        def format_file_size(size_bytes):
            """Format bytes to human readable format"""
            if not size_bytes:
                return "Unknown"
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f} TB"
        
        data = {
            'program': {
                'id': topic['program_id'],
                'program_name': topic['program_name']
            },
            'chapter': {
                'id': topic['chapter_id'],
                'chapter_title': topic['chapter_title']
            },
            'topic': topic,
            'attachments': attachments,
            'total_attachments': total_attachments,
            'total_size': format_file_size(total_size),
            'format_file_size': format_file_size
        }
        
        return render_template('lms_topic_attachments.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/topic/<int:topic_id>/attachment/new', methods=['GET', 'POST'])
@login_required
def add_topic_attachment(topic_id):
    """Add a new attachment to a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get topic, chapter and program details
        cur.execute("""
            SELECT 
                lt.id,
                lt.chapter_id,
                lt.topic_title,
                lt.topic_order,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topics lt
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lt.id = ?
        """, (topic_id,))
        topic = cur.fetchone()
        
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            # Get form data
            file_name = request.form.get('file_name', '').strip()
            attachment_type = request.form.get('attachment_type', 'other')
            description = request.form.get('description', '').strip()
            file_path = request.form.get('file_path', '').strip()
            is_required = request.form.get('is_required') == 'on'
            
            # Validate
            if not file_name:
                flash('File name is required.', 'danger')
                return redirect(url_for('lms_admin.add_topic_attachment', topic_id=topic_id))
            
            if not file_path:
                flash('File path is required.', 'danger')
                return redirect(url_for('lms_admin.add_topic_attachment', topic_id=topic_id))
            
            if len(description) > 500:
                flash('Description cannot exceed 500 characters.', 'danger')
                return redirect(url_for('lms_admin.add_topic_attachment', topic_id=topic_id))
            
            # Validate attachment type
            valid_types = ['pdf', 'excel', 'word', 'image', 'zip', 'other']
            if attachment_type not in valid_types:
                attachment_type = 'other'
            
            # For now, estimate file size as 0 (would be set by actual file upload)
            file_size = 0
            
            try:
                cur.execute("""
                    INSERT INTO lms_topic_attachments 
                    (topic_id, attachment_type, file_name, file_size, file_path, description, uploaded_by, is_required, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """, (topic_id, attachment_type, file_name, file_size, file_path, description, session['user_id'], is_required))
                
                # Log activity
                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='create',
                    module_name='lms_topic_attachments',
                    record_id=topic_id,
                    description=f"Added attachment: {file_name}"
                )
                
                flash(f'Attachment "{file_name}" added successfully!', 'success')
                return redirect(url_for('lms_admin.list_topic_attachments', topic_id=topic_id))
            except Exception as e:
                flash(f'Error adding attachment: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.add_topic_attachment', topic_id=topic_id))
        
        data = {
            'program': {
                'id': topic['program_id'],
                'program_name': topic['program_name']
            },
            'chapter': {
                'id': topic['chapter_id'],
                'chapter_title': topic['chapter_title']
            },
            'topic': topic,
            'attachment': None
        }
        
        return render_template('lms_topic_attachment_form.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/attachment/<int:attachment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_topic_attachment(attachment_id):
    """Edit an existing attachment"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get attachment and all related data
        cur.execute("""
            SELECT 
                lta.id,
                lta.topic_id,
                lta.attachment_type,
                lta.file_name,
                lta.file_size,
                lta.file_path,
                lta.description,
                lta.uploaded_by,
                lta.is_required,
                lta.created_at,
                lta.updated_at,
                lt.id as t_id,
                lt.chapter_id,
                lt.topic_title,
                lc.chapter_title,
                lc.program_id,
                lp.program_name
            FROM lms_topic_attachments lta
            JOIN lms_topics lt ON lta.topic_id = lt.id
            JOIN lms_chapters lc ON lt.chapter_id = lc.id
            JOIN lms_programs lp ON lc.program_id = lp.id
            WHERE lta.id = ?
        """, (attachment_id,))
        attachment = cur.fetchone()
        
        if not attachment:
            flash('Attachment not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            # Get form data
            file_name = request.form.get('file_name', '').strip()
            attachment_type = request.form.get('attachment_type', 'other')
            description = request.form.get('description', '').strip()
            file_path = request.form.get('file_path', '').strip()
            is_required = request.form.get('is_required') == 'on'
            
            # Validate
            if not file_name:
                flash('File name is required.', 'danger')
                return redirect(url_for('lms_admin.edit_topic_attachment', attachment_id=attachment_id))
            
            if not file_path:
                flash('File path is required.', 'danger')
                return redirect(url_for('lms_admin.edit_topic_attachment', attachment_id=attachment_id))
            
            if len(description) > 500:
                flash('Description cannot exceed 500 characters.', 'danger')
                return redirect(url_for('lms_admin.edit_topic_attachment', attachment_id=attachment_id))
            
            # Validate attachment type
            valid_types = ['pdf', 'excel', 'word', 'image', 'zip', 'other']
            if attachment_type not in valid_types:
                attachment_type = 'other'
            
            try:
                cur.execute("""
                    UPDATE lms_topic_attachments
                    SET attachment_type = ?,
                        file_name = ?,
                        file_path = ?,
                        description = ?,
                        is_required = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (attachment_type, file_name, file_path, description, is_required, attachment_id))
                
                # Log activity
                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='update',
                    module_name='lms_topic_attachments',
                    record_id=attachment['topic_id'],
                    description=f"Updated attachment: {file_name}"
                )
                
                flash(f'Attachment "{file_name}" updated successfully!', 'success')
                return redirect(url_for('lms_admin.list_topic_attachments', topic_id=attachment['topic_id']))
            except Exception as e:
                flash(f'Error updating attachment: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.edit_topic_attachment', attachment_id=attachment_id))
        
        data = {
            'program': {
                'id': attachment['program_id'],
                'program_name': attachment['program_name']
            },
            'chapter': {
                'id': attachment['chapter_id'],
                'chapter_title': attachment['chapter_title']
            },
            'topic': {
                'id': attachment['t_id'],
                'topic_title': attachment['topic_title'],
                'topic_order': None
            },
            'attachment': attachment
        }
        
        return render_template('lms_topic_attachment_form.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_topic_attachment(attachment_id):
    """Delete an attachment"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get attachment details for logging
        cur.execute("""
            SELECT id, topic_id, file_name FROM lms_topic_attachments WHERE id = ?
        """, (attachment_id,))
        attachment = cur.fetchone()
        
        if not attachment:
            flash('Attachment not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        topic_id = attachment['topic_id']
        file_name = attachment['file_name']
        
        # Delete attachment
        cur.execute("""
            DELETE FROM lms_topic_attachments WHERE id = ?
        """, (attachment_id,))
        
        # Log activity
        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_topic_attachments',
            record_id=topic_id,
            description=f"Deleted attachment: {file_name}"
        )
        
        flash(f'Attachment "{file_name}" deleted successfully!', 'success')
        return redirect(url_for('lms_admin.list_topic_attachments', topic_id=topic_id))
    except Exception as e:
        flash(f'Error deleting attachment: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_topic_attachments', topic_id=topic_id))
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/resources', methods=['GET'])
@login_required
def list_program_resources(program_id):
    """List all resources for a program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get program details
        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE id = ?
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Get all resources for this program
        cur.execute("""
            SELECT 
                id,
                program_id,
                resource_title,
                resource_type,
                file_path,
                is_active,
                created_at,
                updated_at
            FROM lms_program_resources
            WHERE program_id = ?
            ORDER BY created_at DESC
        """, (program_id,))
        resources = cur.fetchall()
        
        # Get total resources count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_program_resources
            WHERE program_id = ?
        """, (program_id,))
        total_resources = cur.fetchone()['count']
        
        # Note: file_size not available in current schema
        total_size = 0
        
        def format_file_size(size_bytes):
            """Format bytes to human readable format"""
            if not size_bytes:
                return "Unknown"
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f} TB"
        
        data = {
            'program': program,
            'resources': resources,
            'total_resources': total_resources,
            'total_size': format_file_size(total_size),
            'format_file_size': format_file_size
        }
        
        return render_template('lms_program_resources.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/resource/new', methods=['GET', 'POST'])
@login_required
def add_program_resource(program_id):
    """Add a new resource to a program"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get program details
        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE id = ?
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            # Get form data
            resource_title = request.form.get('resource_title', '').strip()
            resource_type = request.form.get('resource_type', 'other')
            is_active = request.form.get('is_active') == 'on'
            
            # Validate
            if not resource_title:
                flash('Resource title is required.', 'danger')
                return redirect(url_for('lms_admin.add_program_resource', program_id=program_id))
            
            # Handle file upload (required)
            if 'pdf_file' not in request.files or not request.files['pdf_file'].filename:
                flash('PDF file upload is required.', 'danger')
                return redirect(url_for('lms_admin.add_program_resource', program_id=program_id))
            
            pdf_file = request.files['pdf_file']
            success, result = upload_file(pdf_file, 'pdf')
            if not success:
                flash(f'PDF upload error: {result}', 'danger')
                return redirect(url_for('lms_admin.add_program_resource', program_id=program_id))
            
            file_path = result
            
            # Validate resource type
            valid_types = ['ebook', 'workbook', 'pdf', 'ppt', 'other']
            if resource_type not in valid_types:
                resource_type = 'other'
            
            try:
                cur.execute("""
                    INSERT INTO lms_program_resources 
                    (program_id, resource_title, resource_type, file_path, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (program_id, resource_title, resource_type, file_path, 1 if is_active else 0))
                
                # Log activity
                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='create',
                    module_name='lms_program_resources',
                    record_id=program_id,
                    description=f"Added resource: {resource_title}"
                )
                
                flash(f'Resource "{resource_title}" added successfully!', 'success')
                return redirect(url_for('lms_admin.list_program_resources', program_id=program_id))
            except Exception as e:
                flash(f'Error adding resource: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.add_program_resource', program_id=program_id))
        
        data = {
            'program': program,
            'resource': None
        }
        
        return render_template('lms_program_resource_form.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/resource/<int:resource_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_program_resource(resource_id):
    """Edit an existing resource"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get resource and program details
        cur.execute("""
            SELECT 
                lr.id,
                lr.program_id,
                lr.resource_title,
                lr.resource_type,
                lr.file_path,
                lr.is_active,
                lr.created_at,
                lr.updated_at,
                lp.program_name
            FROM lms_program_resources lr
            JOIN lms_programs lp ON lr.program_id = lp.id
            WHERE lr.id = ?
        """, (resource_id,))
        resource = cur.fetchone()
        
        if not resource:
            flash('Resource not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        if request.method == 'POST':
            # Get form data
            resource_title = request.form.get('resource_title', '').strip()
            resource_type = request.form.get('resource_type', 'other')
            is_active = request.form.get('is_active') == 'on'
            
            # Validate
            if not resource_title:
                flash('Resource title is required.', 'danger')
                return redirect(url_for('lms_admin.edit_program_resource', resource_id=resource_id))
            
            # Handle file upload (required)
            if 'pdf_file' not in request.files or not request.files['pdf_file'].filename:
                flash('PDF file upload is required.', 'danger')
                return redirect(url_for('lms_admin.edit_program_resource', resource_id=resource_id))
            
            pdf_file = request.files['pdf_file']
            success, result = upload_file(pdf_file, 'pdf')
            if not success:
                flash(f'PDF upload error: {result}', 'danger')
                return redirect(url_for('lms_admin.edit_program_resource', resource_id=resource_id))
            
            file_path = result
            
            # Validate resource type
            valid_types = ['ebook', 'workbook', 'pdf', 'ppt', 'other']
            if resource_type not in valid_types:
                resource_type = 'other'
            
            try:
                cur.execute("""
                    UPDATE lms_program_resources
                    SET resource_type = ?,
                        resource_title = ?,
                        file_path = ?,
                        is_active = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (resource_type, resource_title, file_path, 1 if is_active else 0, resource_id))
                
                # Log activity
                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='update',
                    module_name='lms_program_resources',
                    record_id=resource['program_id'],
                    description=f"Updated resource: {resource_title}"
                )
                
                flash(f'Resource "{resource_title}" updated successfully!', 'success')
                return redirect(url_for('lms_admin.list_program_resources', program_id=resource['program_id']))
            except Exception as e:
                flash(f'Error updating resource: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.edit_program_resource', resource_id=resource_id))
        
        data = {
            'program': {
                'id': resource['program_id'],
                'program_name': resource['program_name']
            },
            'resource': resource
        }
        
        return render_template('lms_program_resource_form.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/resource/<int:resource_id>/delete', methods=['POST'])
@login_required
def delete_program_resource(resource_id):
    """Delete a resource"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get resource details for logging
        cur.execute("""
            SELECT id, program_id, resource_title FROM lms_program_resources WHERE id = ?
        """, (resource_id,))
        resource = cur.fetchone()
        
        if not resource:
            flash('Resource not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        program_id = resource['program_id']
        resource_title = resource['resource_title']
        
        # Delete resource
        cur.execute("""
            DELETE FROM lms_program_resources WHERE id = ?
        """, (resource_id,))
        
        # Log activity
        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_program_resources',
            record_id=program_id,
            description=f"Deleted resource: {resource_title}"
        )
        
        flash(f'Resource "{resource_title}" deleted successfully!', 'success')
        return redirect(url_for('lms_admin.list_program_resources', program_id=program_id))
    except Exception as e:
        flash(f'Error deleting resource: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_program_resources', program_id=program_id))
    finally:
        conn.close()


@lms_admin_bp.route('/batch-programs', methods=['GET'])
@login_required
def list_batch_programs():
    """List all batch-to-program assignments"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get all batch-program assignments with program and batch details
        cur.execute("""
            SELECT 
                lbpa.id,
                lbpa.batch_id,
                lbpa.program_id,
                lbpa.access_start_date,
                lbpa.access_end_date,
                lbpa.is_active,
                lbpa.created_at,
                lbpa.updated_at,
                lp.program_name,
                (SELECT COUNT(*) FROM lms_student_program_access WHERE batch_id = lbpa.batch_id AND program_id = lbpa.program_id) as student_count
            FROM lms_batch_program_access lbpa
            JOIN lms_programs lp ON lbpa.program_id = lp.id
            ORDER BY lbpa.is_active DESC, lbpa.access_start_date DESC
        """)
        batch_programs = cur.fetchall()
        
        # Get summary counts
        cur.execute("""
            SELECT COUNT(*) as total FROM lms_batch_program_access
        """)
        total_assignments = cur.fetchone()['total']
        
        cur.execute("""
            SELECT COUNT(*) as active FROM lms_batch_program_access WHERE is_active = 1
        """)
        active_assignments = cur.fetchone()['active']
        
        # Get unique batches and programs
        cur.execute("""
            SELECT COUNT(DISTINCT batch_id) as count FROM lms_batch_program_access
        """)
        total_batches = cur.fetchone()['count']
        
        cur.execute("""
            SELECT COUNT(DISTINCT program_id) as count FROM lms_batch_program_access
        """)
        total_programs = cur.fetchone()['count']
        
        def format_date(date_str):
            """Format date string for display"""
            if not date_str:
                return "—"
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                return date_obj.strftime('%d %b %Y')
            except:
                return date_str
        
        data = {
            'batch_programs': batch_programs,
            'total_assignments': total_assignments,
            'active_assignments': active_assignments,
            'total_batches': total_batches,
            'total_programs': total_programs,
            'format_date': format_date
        }
        
        return render_template('lms_batch_programs.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/batch-program/new', methods=['GET', 'POST'])
@login_required
def add_batch_program():
    """Assign a program to a batch"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        if request.method == 'POST':
            # Get form data
            batch_id = request.form.get('batch_id', '').strip()
            program_id = request.form.get('program_id', '').strip()
            access_start_date = request.form.get('access_start_date', '').strip()
            access_end_date = request.form.get('access_end_date', '').strip()
            is_active = request.form.get('is_active') == 'on'
            
            # Validate
            if not batch_id:
                flash('Batch is required.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            if not program_id:
                flash('Program is required.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            if not access_start_date:
                flash('Access start date is required.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            # Convert to integers
            try:
                batch_id = int(batch_id)
                program_id = int(program_id)
            except ValueError:
                flash('Invalid batch or program.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            # Check if batch exists
            cur.execute("SELECT id FROM batches WHERE id = ?", (batch_id,))
            if not cur.fetchone():
                flash('Batch not found.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            # Check if program exists
            cur.execute("SELECT id FROM lms_programs WHERE id = ?", (program_id,))
            if not cur.fetchone():
                flash('Program not found.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            # Check for duplicate assignment
            cur.execute("""
                SELECT id FROM lms_batch_program_access 
                WHERE batch_id = ? AND program_id = ?
            """, (batch_id, program_id))
            if cur.fetchone():
                flash('This batch is already assigned to this program.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            # Validate dates
            try:
                from datetime import datetime
                start_date = datetime.strptime(access_start_date, '%Y-%m-%d')
                if access_end_date:
                    end_date = datetime.strptime(access_end_date, '%Y-%m-%d')
                    if end_date < start_date:
                        flash('End date cannot be before start date.', 'danger')
                        return redirect(url_for('lms_admin.add_batch_program'))
            except ValueError:
                flash('Invalid date format.', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
            
            try:
                cur.execute("""
                    INSERT INTO lms_batch_program_access 
                    (batch_id, program_id, access_start_date, access_end_date, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """, (batch_id, program_id, access_start_date, access_end_date if access_end_date else None, is_active))
                
                # Log activity
                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='create',
                    module_name='lms_batch_program_access',
                    record_id=batch_id,
                    description=f"Assigned program {program_id} to batch {batch_id}"
                )
                
                flash('Batch-program assignment created successfully!', 'success')
                return redirect(url_for('lms_admin.list_batch_programs'))
            except Exception as e:
                flash(f'Error creating assignment: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.add_batch_program'))
        
        # Get all available batches
        cur.execute("""
            SELECT id, batch_name FROM batches WHERE status = 'active' ORDER BY batch_name ASC
        """)
        batches = cur.fetchall()
        
        # Get all available programs
        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE is_published = 1 ORDER BY program_name ASC
        """)
        programs = cur.fetchall()
        
        data = {
            'batches': batches,
            'programs': programs,
            'assignment': None
        }
        
        return render_template('lms_batch_program_form.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/batch-program/<int:assignment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_batch_program(assignment_id):
    """Edit a batch-program assignment"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get assignment details
        cur.execute("""
            SELECT 
                lbpa.id,
                lbpa.batch_id,
                lbpa.program_id,
                lbpa.access_start_date,
                lbpa.access_end_date,
                lbpa.is_active,
                ab.batch_name,
                lp.program_name
            FROM lms_batch_program_access lbpa
            JOIN batches ab ON lbpa.batch_id = ab.id
            JOIN lms_programs lp ON lbpa.program_id = lp.id
            WHERE lbpa.id = ?
        """, (assignment_id,))
        assignment = cur.fetchone()
        
        if not assignment:
            flash('Assignment not found.', 'danger')
            return redirect(url_for('lms_admin.list_batch_programs'))
        
        if request.method == 'POST':
            # Get form data
            access_start_date = request.form.get('access_start_date', '').strip()
            access_end_date = request.form.get('access_end_date', '').strip()
            is_active = request.form.get('is_active') == 'on'
            
            # Validate dates
            if not access_start_date:
                flash('Access start date is required.', 'danger')
                return redirect(url_for('lms_admin.edit_batch_program', assignment_id=assignment_id))
            
            try:
                from datetime import datetime
                start_date = datetime.strptime(access_start_date, '%Y-%m-%d')
                if access_end_date:
                    end_date = datetime.strptime(access_end_date, '%Y-%m-%d')
                    if end_date < start_date:
                        flash('End date cannot be before start date.', 'danger')
                        return redirect(url_for('lms_admin.edit_batch_program', assignment_id=assignment_id))
            except ValueError:
                flash('Invalid date format.', 'danger')
                return redirect(url_for('lms_admin.edit_batch_program', assignment_id=assignment_id))
            
            try:
                cur.execute("""
                    UPDATE lms_batch_program_access
                    SET access_start_date = ?,
                        access_end_date = ?,
                        is_active = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (access_start_date, access_end_date if access_end_date else None, is_active, assignment_id))
                
                # Log activity
                conn.commit()
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='update',
                    module_name='lms_batch_program_access',
                    record_id=assignment['batch_id'],
                    description=f"Updated access for program {assignment['program_id']} in batch {assignment['batch_id']}"
                )
                
                flash('Assignment updated successfully!', 'success')
                return redirect(url_for('lms_admin.list_batch_programs'))
            except Exception as e:
                flash(f'Error updating assignment: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.edit_batch_program', assignment_id=assignment_id))
        
        # Get all available batches
        cur.execute("""
            SELECT id, batch_name FROM batches WHERE status = 'active' ORDER BY batch_name ASC
        """)
        batches = cur.fetchall()
        
        # Get all available programs
        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE is_published = 1 ORDER BY program_name ASC
        """)
        programs = cur.fetchall()
        
        data = {
            'batches': batches,
            'programs': programs,
            'assignment': assignment
        }
        
        return render_template('lms_batch_program_form.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/batch-program/<int:assignment_id>/delete', methods=['POST'])
@login_required
def delete_batch_program(assignment_id):
    """Delete a batch-program assignment"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get assignment details for logging
        cur.execute("""
            SELECT id, batch_id, program_id FROM lms_batch_program_access WHERE id = ?
        """, (assignment_id,))
        assignment = cur.fetchone()
        
        if not assignment:
            flash('Assignment not found.', 'danger')
            return redirect(url_for('lms_admin.list_batch_programs'))
        
        # Delete assignment
        cur.execute("""
            DELETE FROM lms_batch_program_access WHERE id = ?
        """, (assignment_id,))
        
        # Log activity
        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_batch_program_access',
            record_id=assignment['batch_id'],
            description=f"Removed program {assignment['program_id']} from batch {assignment['batch_id']}"
        )
        
        flash('Assignment deleted successfully!', 'success')
        return redirect(url_for('lms_admin.list_batch_programs'))
    except Exception as e:
        flash(f'Error deleting assignment: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_batch_programs'))
    finally:
        conn.close()


# ===========================
# PHASE 3: STUDENT PROGRESS MONITORING
# ===========================

@lms_admin_bp.route('/progress-dashboard', methods=['GET'])
@login_required
def progress_dashboard():
    """Overall student progress monitoring dashboard"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get overall statistics
        # Total active students in LMS
        cur.execute("""
            SELECT COUNT(DISTINCT student_id) as count
            FROM lms_student_program_access
            WHERE is_active = 1
        """)
        active_students = cur.fetchone()['count']
        
        # Total completed topics
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topic_progress
            WHERE is_completed = 1
        """)
        completed_topics = cur.fetchone()['count']
        
        # In progress (binary state — no partial completion)
        in_progress_topics = 0
        
        # Total not started (records exist but not completed)
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_topic_progress
            WHERE is_completed = 0
        """)
        not_started_topics = cur.fetchone()['count']
        
        # Overall completion percentage
        cur.execute("""
            SELECT
                CASE WHEN COUNT(*) = 0 THEN 0
                ELSE ROUND(100.0 * SUM(is_completed) / COUNT(*), 1)
                END as avg_completion
            FROM lms_topic_progress
        """)
        result = cur.fetchone()
        overall_completion = result['avg_completion'] if result['avg_completion'] else 0
        
        # Top 5 progressing students (by completion)
        cur.execute("""
            SELECT 
                stp.student_id,
                ast.full_name as first_name,
                '' as last_name,
                COUNT(stp.topic_id) as topics_count,
                ROUND(100.0 * SUM(stp.is_completed) / COUNT(*), 1) as avg_completion,
                MAX(stp.completed_at) as last_accessed
            FROM lms_topic_progress stp
            LEFT JOIN students ast ON stp.student_id = ast.id
            GROUP BY stp.student_id
            ORDER BY avg_completion DESC
            LIMIT 5
        """)
        top_students = cur.fetchall()
        
        # Bottom 5 low engagement students: have program access but least/no progress
        cur.execute("""
            SELECT 
                spa.student_id,
                ast.full_name as first_name,
                '' as last_name,
                COUNT(DISTINCT stp.topic_id) as topics_count,
                COALESCE(ROUND(100.0 * SUM(CASE WHEN stp.is_completed = 1 THEN 1 ELSE 0 END) / 
                    NULLIF(COUNT(DISTINCT stp.topic_id), 0), 1), 0) as avg_completion,
                MAX(stp.completed_at) as last_accessed
            FROM lms_student_program_access spa
            JOIN students ast ON spa.student_id = ast.id
            LEFT JOIN lms_topic_progress stp ON spa.student_id = stp.student_id
            WHERE spa.is_active = 1
            GROUP BY spa.student_id
            ORDER BY avg_completion ASC, topics_count ASC
            LIMIT 5
        """)
        low_engagement_students = cur.fetchall()
        
        # Recent activity - last 10 completions
        cur.execute("""
            SELECT 
                stp.student_id,
                ast.full_name as first_name,
                '' as last_name,
                lt.topic_title,
                CASE WHEN stp.is_completed = 1 THEN 100 ELSE 0 END as completion_percentage,
                stp.completed_at as last_accessed
            FROM lms_topic_progress stp
            LEFT JOIN students ast ON stp.student_id = ast.id
            LEFT JOIN lms_topics lt ON stp.topic_id = lt.id
            WHERE stp.is_completed = 1
            ORDER BY stp.completed_at DESC
            LIMIT 10
        """)
        recent_activity = cur.fetchall()
        
        # Completion distribution (binary: completed or not started)
        cur.execute("""
            SELECT 
                CASE WHEN is_completed = 1 THEN '100%' ELSE 'Not Started' END as completion_range,
                COUNT(*) as count
            FROM lms_topic_progress
            GROUP BY is_completed
            ORDER BY is_completed
        """)
        completion_distribution = cur.fetchall()
        
        # Get batches with LMS programs
        cur.execute("""
            SELECT 
                ab.id,
                ab.batch_name,
                COUNT(DISTINCT lbpa.program_id) as programs_count,
                COUNT(DISTINCT CASE WHEN lbpa.is_active = 1 THEN lbpa.program_id END) as active_programs,
                COUNT(DISTINCT sb.student_id) as students_count,
                ROUND(
                    CASE WHEN COUNT(stp.id) = 0 THEN 0
                    ELSE 100.0 * SUM(CASE WHEN stp.is_completed = 1 THEN 1 ELSE 0 END) / COUNT(stp.id)
                    END, 1) as avg_completion
            FROM batches ab
            LEFT JOIN lms_batch_program_access lbpa ON ab.id = lbpa.batch_id
            LEFT JOIN student_batches sb ON ab.id = sb.batch_id AND sb.status = 'active'
            LEFT JOIN lms_topic_progress stp ON sb.student_id = stp.student_id
            WHERE lbpa.program_id IS NOT NULL
            GROUP BY ab.id
            ORDER BY ab.batch_name
        """)
        batches_with_lms = cur.fetchall()
        
        def format_date(date_str):
            """Format date string for display"""
            if not date_str:
                return "—"
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                return date_obj.strftime('%d %b %Y, %I:%M %p')
            except:
                return date_str
        
        data = {
            'active_students': active_students,
            'completed_topics': completed_topics,
            'in_progress_topics': in_progress_topics,
            'not_started_topics': not_started_topics,
            'overall_completion': round(overall_completion, 1),
            'top_students': top_students,
            'low_engagement_students': low_engagement_students,
            'recent_activity': recent_activity,
            'completion_distribution': completion_distribution,
            'batches': batches_with_lms,
            'format_date': format_date
        }
        
        return render_template('lms_progress_dashboard.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/student/<int:student_id>/progress', methods=['GET'])
@login_required
def view_student_progress(student_id):
    """Detailed progress page for a single student"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get student info
        cur.execute("""
            SELECT id, full_name as first_name, '' as last_name,
                   student_code as roll_number, email
            FROM students
            WHERE id = ?
        """, (student_id,))
        student = cur.fetchone()
        
        if not student:
            flash('Student not found', 'danger')
            return redirect(url_for('lms_admin.progress_dashboard'))
        
        # Get student's assigned programs with access info
        cur.execute("""
            SELECT 
                spa.id as assignment_id,
                spa.program_id,
                spa.access_start_date,
                spa.access_end_date,
                spa.is_active,
                lp.program_name,
                lp.description,
                (SELECT COUNT(*) FROM lms_chapters WHERE program_id = lp.id) as total_chapters
            FROM lms_student_program_access spa
            LEFT JOIN lms_programs lp ON spa.program_id = lp.id
            WHERE spa.student_id = ?
            ORDER BY spa.access_start_date DESC
        """, (student_id,))
        programs = cur.fetchall()
        
        # Build hierarchical data for each program
        programs_with_details = []
        
        for prog in programs:
            program_id = prog['program_id']
            
            # Get chapters for this program
            cur.execute("""
                SELECT 
                    lc.id,
                    lc.chapter_title,
                    lc.chapter_order,
                    lc.description,
                    (SELECT COUNT(*) FROM lms_topics WHERE chapter_id = lc.id) as total_topics,
                    (SELECT COUNT(*) FROM lms_topic_progress 
                     WHERE student_id = ? AND topic_id IN 
                     (SELECT id FROM lms_topics WHERE chapter_id = lc.id) 
                     AND is_completed = 1) as completed_topics
                FROM lms_chapters lc
                WHERE lc.program_id = ?
                ORDER BY lc.chapter_order
            """, (student_id, program_id))
            chapters = cur.fetchall()
            
            # Build chapter details with topics
            chapters_with_topics = []
            for chap in chapters:
                chapter_id = chap['id']
                
                # Get topics for this chapter
                cur.execute("""
                    SELECT 
                        lt.id,
                        lt.topic_title,
                        lt.topic_order,
                        lt.is_required,
                        COALESCE(CASE WHEN stp.is_completed = 1 THEN 100 ELSE 0 END, 0) as completion_percentage,
                        COALESCE(stp.completed_at, 'Not started') as last_accessed,
                        0 as time_spent_minutes
                    FROM lms_topics lt
                    LEFT JOIN lms_topic_progress stp ON lt.id = stp.topic_id AND stp.student_id = ?
                    WHERE lt.chapter_id = ?
                    ORDER BY lt.topic_order
                """, (student_id, chapter_id))
                topics = cur.fetchall()
                
                chapters_with_topics.append({
                    'id': chap['id'],
                    'chapter_title': chap['chapter_title'],
                    'chapter_order': chap['chapter_order'],
                    'description': chap['description'],
                    'total_topics': chap['total_topics'],
                    'completed_topics': chap['completed_topics'],
                    'topics': topics
                })
            
            # Calculate program completion percentage
            total_topics = sum(ch['total_topics'] for ch in chapters_with_topics)
            total_completed = sum(ch['completed_topics'] for ch in chapters_with_topics)
            program_completion = (total_completed / total_topics * 100) if total_topics > 0 else 0
            
            programs_with_details.append({
                'assignment_id': prog['assignment_id'],
                'program_id': prog['program_id'],
                'program_name': prog['program_name'],
                'description': prog['description'],
                'access_start_date': prog['access_start_date'],
                'access_end_date': prog['access_end_date'],
                'is_active': prog['is_active'],
                'total_chapters': prog['total_chapters'],
                'total_topics': total_topics,
                'total_completed': total_completed,
                'completion_percentage': round(program_completion, 1),
                'chapters': chapters_with_topics
            })
        
        # Get student's test results if any
        cur.execute("""
            SELECT 
                str.test_id,
                lmt.test_title,
                str.score,
                str.total_marks,
                str.obtained_percentage,
                str.test_date
            FROM lms_student_test_results str
            LEFT JOIN lms_mock_tests lmt ON str.test_id = lmt.id
            WHERE str.student_id = ?
            ORDER BY str.test_date DESC
            LIMIT 10
        """, (student_id,))
        test_results = cur.fetchall()
        
        # Get overall statistics
        total_topics = sum(p['total_topics'] for p in programs_with_details)
        total_completed = sum(p['total_completed'] for p in programs_with_details)
        overall_completion = (total_completed / total_topics * 100) if total_topics > 0 else 0
        
        # Get most recent activity
        cur.execute("""
            SELECT 
                stp.student_id,
                lt.topic_title,
                CASE WHEN stp.is_completed = 1 THEN 100 ELSE 0 END as completion_percentage,
                stp.completed_at as last_accessed
            FROM lms_topic_progress stp
            LEFT JOIN lms_topics lt ON stp.topic_id = lt.id
            WHERE stp.student_id = ?
            ORDER BY stp.completed_at DESC
            LIMIT 5
        """, (student_id,))
        recent_activities = cur.fetchall()
        
        def format_date(date_str):
            """Format date string for display"""
            if not date_str or date_str == 'Not started':
                return "Not started"
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                return date_obj.strftime('%d %b %Y, %I:%M %p')
            except:
                return date_str
        
        data = {
            'student': student,
            'programs': programs_with_details,
            'test_results': test_results,
            'total_topics': total_topics,
            'total_completed': total_completed,
            'overall_completion': round(overall_completion, 1),
            'recent_activities': recent_activities,
            'format_date': format_date
        }
        
        return render_template('lms_progress_student_view.html', data=data)
    except Exception as e:
        flash(f'Error loading student progress: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.progress_dashboard'))
    finally:
        conn.close()


@lms_admin_bp.route('/batch/<int:batch_id>/progress', methods=['GET'])
@login_required
def view_batch_progress(batch_id):
    """Detailed progress page for entire batch"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get batch info
        cur.execute("""
            SELECT id, batch_name
            FROM batches
            WHERE id = ?
        """, (batch_id,))
        batch = cur.fetchone()
        
        if not batch:
            flash('Batch not found', 'danger')
            return redirect(url_for('lms_admin.progress_dashboard'))
        
        # Get all students in batch with their LMS progress
        cur.execute("""
            SELECT 
                ast.id,
                ast.full_name as first_name,
                '' as last_name,
                ast.student_code as roll_number,
                COUNT(DISTINCT spa.program_id) as programs_assigned,
                COUNT(DISTINCT CASE WHEN spa.is_active = 1 THEN spa.program_id END) as programs_active,
                COUNT(DISTINCT stp.topic_id) as topics_accessed,
                ROUND(
                    CASE WHEN COUNT(stp.id) = 0 THEN 0
                    ELSE 100.0 * SUM(CASE WHEN stp.is_completed = 1 THEN 1 ELSE 0 END) / COUNT(stp.id)
                    END, 1) as avg_completion,
                MAX(stp.completed_at) as last_activity,
                COUNT(DISTINCT CASE WHEN stp.is_completed = 1 THEN stp.topic_id END) as topics_completed
            FROM students ast
            JOIN student_batches sb ON ast.id = sb.student_id AND sb.batch_id = ? AND sb.status = 'active'
            LEFT JOIN lms_student_program_access spa ON ast.id = spa.student_id
            LEFT JOIN lms_topic_progress stp ON ast.id = stp.student_id
            GROUP BY ast.id
            ORDER BY ast.student_code
        """, (batch_id,))
        batch_students = cur.fetchall()
        
        # Get programs accessible by this batch
        cur.execute("""
            SELECT DISTINCT 
                lp.id,
                lp.program_name
            FROM lms_batch_program_access lbpa
            JOIN lms_programs lp ON lbpa.program_id = lp.id
            WHERE lbpa.batch_id = ? AND lbpa.is_active = 1
            ORDER BY lp.program_name
        """, (batch_id,))
        batch_programs = cur.fetchall()
        
        # Build detailed progress data per program-student combination
        student_program_details = {}
        
        for prog in batch_programs:
            program_id = prog['id']
            
            # For each student, get their progress in this program's chapters
            for student in batch_students:
                student_id = student['id']
                key = f"{student_id}_{program_id}"
                
                # Get chapter-wise completion for this student in this program
                cur.execute("""
                    SELECT 
                        lc.id,
                        lc.chapter_title,
                        lc.chapter_order,
                        COUNT(lt.id) as total_topics,
                        COUNT(CASE WHEN stp.is_completed = 1 THEN lt.id END) as completed_topics
                    FROM lms_chapters lc
                    LEFT JOIN lms_topics lt ON lc.id = lt.chapter_id
                    LEFT JOIN lms_topic_progress stp ON lt.id = stp.topic_id AND stp.student_id = ?
                    WHERE lc.program_id = ?
                    GROUP BY lc.id
                    ORDER BY lc.chapter_order
                """, (student_id, program_id))
                chapters_data = cur.fetchall()
                
                student_program_details[key] = chapters_data
        
        # Get batch-level statistics
        total_students = len(batch_students)
        active_students = len([s for s in batch_students if s['programs_active'] > 0])
        inactive_students = total_students - active_students
        
        # Calculate overall batch completion
        avg_batch_completion = 0
        topics_started_count = 0
        topics_completed_count = 0
        
        if batch_students:
            completions = [s['avg_completion'] for s in batch_students if s['avg_completion']]
            if completions:
                avg_batch_completion = sum(completions) / len(completions)
            
            topics_started_count = len([s for s in batch_students if s['topics_accessed'] and s['topics_accessed'] > 0])
            topics_completed_count = sum([s['topics_completed'] or 0 for s in batch_students])
        
        # Top performers (highest completion)
        top_performers = sorted(
            [s for s in batch_students if s['avg_completion']],
            key=lambda x: x['avg_completion'] or 0,
            reverse=True
        )[:5]
        
        # Low performers
        low_performers = sorted(
            [s for s in batch_students if s['avg_completion']],
            key=lambda x: x['avg_completion'] or 0
        )[:5]
        
        # Recent batch activity
        cur.execute("""
            SELECT 
                ast.full_name as first_name,
                '' as last_name,
                lt.topic_title,
                CASE WHEN stp.is_completed = 1 THEN 100 ELSE 0 END as completion_percentage,
                stp.completed_at as last_accessed
            FROM lms_topic_progress stp
            JOIN students ast ON stp.student_id = ast.id
            JOIN student_batches sb ON ast.id = sb.student_id AND sb.batch_id = ?
            LEFT JOIN lms_topics lt ON stp.topic_id = lt.id
            WHERE stp.is_completed = 1
            ORDER BY stp.completed_at DESC
            LIMIT 10
        """, (batch_id,))
        batch_activity = cur.fetchall()
        
        # Chapter-wise summary for all students in batch
        chapter_summary = {}
        if batch_programs:
            for prog in batch_programs:
                program_id = prog['id']
                
                cur.execute("""
                    SELECT 
                        lc.id,
                        lc.chapter_title,
                        lc.chapter_order,
                        COUNT(DISTINCT ast.id) as total_students,
                        COUNT(DISTINCT CASE WHEN stp.is_completed = 1 THEN ast.id END) as students_completed,
                        ROUND(
                            CASE WHEN COUNT(stp.id) = 0 THEN 0
                            ELSE 100.0 * SUM(CASE WHEN stp.is_completed = 1 THEN 1 ELSE 0 END) / COUNT(stp.id)
                            END, 1) as avg_completion
                    FROM lms_chapters lc
                    LEFT JOIN lms_topics lt ON lc.id = lt.chapter_id
                    LEFT JOIN lms_topic_progress stp ON lt.id = stp.topic_id
                    LEFT JOIN students ast ON stp.student_id = ast.id
                    LEFT JOIN student_batches astb ON ast.id = astb.student_id AND astb.batch_id = ?
                    WHERE lc.program_id = ?
                    GROUP BY lc.id
                    ORDER BY lc.chapter_order
                """, (batch_id, program_id))
                
                chapter_summary[prog['program_name']] = cur.fetchall()
        
        def format_date(date_str):
            """Format date string for display"""
            if not date_str:
                return "—"
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                return date_obj.strftime('%d %b %Y, %I:%M %p')
            except:
                return date_str
        
        def get_status_badge(completion):
            """Get status badge for completion percentage"""
            if not completion:
                return {'text': 'Not Started', 'class': 'bg-secondary'}
            elif completion == 100:
                return {'text': 'Complete', 'class': 'bg-success'}
            elif completion >= 75:
                return {'text': 'Excellent', 'class': 'bg-success'}
            elif completion >= 50:
                return {'text': 'Good', 'class': 'bg-info'}
            elif completion >= 25:
                return {'text': 'Fair', 'class': 'bg-warning'}
            else:
                return {'text': 'Poor', 'class': 'bg-danger'}
        
        data = {
            'batch': batch,
            'batch_students': batch_students,
            'batch_programs': batch_programs,
            'student_program_details': student_program_details,
            'total_students': total_students,
            'active_students': active_students,
            'inactive_students': inactive_students,
            'avg_batch_completion': round(avg_batch_completion, 1),
            'topics_started_count': topics_started_count,
            'topics_completed_count': topics_completed_count,
            'top_performers': top_performers,
            'low_performers': low_performers,
            'batch_activity': batch_activity,
            'chapter_summary': chapter_summary,
            'format_date': format_date,
            'get_status_badge': get_status_badge
        }
        
        return render_template('lms_progress_batch_view.html', data=data)
    except Exception as e:
        flash(f'Error loading batch progress: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.progress_dashboard'))
    finally:
        conn.close()
