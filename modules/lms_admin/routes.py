from flask import render_template, request, jsonify, send_from_directory
from . import lms_admin_bp
from db import get_conn, log_activity
from flask import session, redirect, url_for, flash
from extensions import csrf
from datetime import datetime
import re
import os
import json
import sqlite3
import bleach
from bleach.css_sanitizer import CSSSanitizer
from werkzeug.utils import secure_filename
from config import Config, DB_PATH
from modules.core.utils import login_required, admin_required, lms_content_manager_required

# ── Rich text sanitization config ──────────────────────────────────────────
_BLEACH_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 's', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'blockquote', 'pre', 'code',
    'a', 'img',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'colgroup', 'col', 'caption',
    'div', 'span', 'hr', 'sub', 'sup',
]
def _BLEACH_ATTRS(tag, name, value):
    """Allow standard attributes plus data-* on div (for embedded hotspot blocks)."""
    if name in ('class', 'style'):
        return True
    if tag == 'a' and name in ('href', 'title', 'target'):
        return True
    if tag == 'img' and name in ('src', 'alt', 'width', 'height'):
        return True
    if tag in ('td', 'th') and name in ('colspan', 'rowspan', 'width', 'height', 'align', 'valign', 'bgcolor'):
        return True
    # Allow deprecated-but-harmless table presentation attributes for backward compatibility
    # (browsers render these; new content uses table_style_by_css instead)
    if tag == 'table' and name in ('border', 'bordercolor', 'cellpadding', 'cellspacing', 'width', 'height', 'align', 'bgcolor', 'summary'):
        return True
    if tag == 'tr' and name in ('align', 'valign', 'bgcolor', 'height'):
        return True
    if tag in ('col', 'colgroup') and name in ('span', 'width', 'align', 'valign'):
        return True
    if tag == 'div' and name.startswith('data-'):
        return True
    if tag == 'div' and name == 'contenteditable':
        return True
    return False

# bleach 6.x requires an explicit CSSSanitizer when style attributes are allowed.
# Without it, bleach silently drops ALL style="..." attributes — the behaviour that
# was causing table background/border colours to disappear after save.
_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=[
    # Text
    'color', 'background-color',
    'font-size', 'font-weight', 'font-style', 'font-family', 'font-variant',
    'text-align', 'text-decoration', 'text-indent', 'text-transform',
    'line-height', 'letter-spacing', 'word-spacing', 'white-space',
    'vertical-align',
    # Box model
    'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
    'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
    'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    # Borders
    'border', 'border-top', 'border-right', 'border-bottom', 'border-left',
    'border-color', 'border-style', 'border-width',
    'border-collapse', 'border-spacing',
    'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
    'border-top-style', 'border-right-style', 'border-bottom-style', 'border-left-style',
    'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width',
    'border-radius',
    # Layout (safe subset — no position/z-index)
    'display', 'float', 'clear', 'overflow',
    'list-style-type', 'caption-side',
])

_ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
_MASTER_BRIDGE_PROGRAM_SLUG = '__lms_master_bridge__'
_MASTER_BRIDGE_PROGRAM_NAME = 'LMS Master Bridge (System)'
_MASTER_BRIDGE_CHAPTER_TITLE = 'Master Topic Bridge Chapter'


def sanitize_rich_text(html):
    """Strip script tags and unsafe JS from editor HTML while preserving safe CSS."""
    return bleach.clean(
        html,
        tags=_BLEACH_TAGS,
        attributes=_BLEACH_ATTRS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
    )


def _to_positive_int(value, default=1):
    """Convert value to a positive integer with a safe default."""
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _strict_positive_int(value):
    """Return positive integer only for strict int-like input, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit():
            parsed = int(cleaned)
            return parsed if parsed > 0 else None
    return None


def _renumber_chapter_topics(cur, chapter_id, ordered_topic_ids=None):
    """Ensure topic_order is sequential (1..n) for one chapter only."""
    rows = cur.execute(
        """
            SELECT id
            FROM lms_topics
            WHERE chapter_id = ?
            ORDER BY topic_order ASC, id ASC
        """,
        (chapter_id,)
    ).fetchall()

    if not rows:
        return []

    existing_ids = [row['id'] for row in rows]
    ordered_ids = []

    if ordered_topic_ids:
        seen = set()
        for topic_id in ordered_topic_ids:
            if topic_id in existing_ids and topic_id not in seen:
                ordered_ids.append(topic_id)
                seen.add(topic_id)
        for topic_id in existing_ids:
            if topic_id not in seen:
                ordered_ids.append(topic_id)
    else:
        ordered_ids = existing_ids

    now = datetime.now().isoformat(timespec='seconds')
    for next_order, topic_id in enumerate(ordered_ids, start=1):
        cur.execute(
            """
                UPDATE lms_topics
                SET topic_order = ?,
                    updated_at = ?
                WHERE id = ?
            """,
            (next_order, now, topic_id)
        )

    return ordered_ids


def _renumber_program_chapter_links(cur, program_id, ordered_link_ids=None):
    """Normalize lms_program_chapters.chapter_order to sequential values for one program."""
    rows = cur.execute(
        """
            SELECT id
            FROM lms_program_chapters
            WHERE program_id = ?
            ORDER BY chapter_order ASC, id ASC
        """,
        (program_id,)
    ).fetchall()

    if not rows:
        return []

    existing_ids = [row['id'] for row in rows]
    ordered_ids = []

    if ordered_link_ids:
        seen = set()
        for link_id in ordered_link_ids:
            if link_id in existing_ids and link_id not in seen:
                ordered_ids.append(link_id)
                seen.add(link_id)
        for link_id in existing_ids:
            if link_id not in seen:
                ordered_ids.append(link_id)
    else:
        ordered_ids = existing_ids

    for next_order, link_id in enumerate(ordered_ids, start=1):
        cur.execute(
            """
                UPDATE lms_program_chapters
                SET chapter_order = ?
                WHERE id = ?
            """,
            (next_order, link_id)
        )

    return ordered_ids


def _create_db_backup_snapshot(conn, label='phase5'):
    """Create SQLite backup snapshot using native backup API and return backup file path."""
    backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backup')
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'{label}_{stamp}.db')

    backup_conn = sqlite3.connect(backup_path)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    return backup_path


def _migrate_legacy_chapter_to_master(cur, program_id, chapter_id, actor_user_id):
    """Non-destructive chapter migration: create master rows + link, map existing content/attachments by master_topic_id."""
    now = datetime.now().isoformat(timespec='seconds')

    chapter = cur.execute(
        """
            SELECT id, program_id, chapter_title, chapter_order, description, is_active
            FROM lms_chapters
            WHERE id = ? AND program_id = ?
        """,
        (chapter_id, program_id)
    ).fetchone()
    if not chapter:
        return None, 'Chapter not found for this program.'

    topics = cur.execute(
        """
            SELECT id, topic_title, topic_order, short_description, is_active
            FROM lms_topics
            WHERE chapter_id = ?
            ORDER BY topic_order ASC, id ASC
        """,
        (chapter_id,)
    ).fetchall()
    if not topics:
        return None, 'Chapter has no topics to migrate.'

    # Guard against repeat migration of the same legacy chapter topics.
    already_migrated = cur.execute(
        """
            SELECT 1
            FROM lms_master_topic_bridge b
            JOIN lms_topics t ON t.id = b.legacy_topic_id
            WHERE t.chapter_id = ?
            LIMIT 1
        """,
        (chapter_id,)
    ).fetchone()
    if already_migrated:
        return None, 'This chapter appears to be already migrated (bridge mapping exists).'

    master_status = 'active' if chapter['is_active'] else 'archived'
    cur.execute(
        """
            INSERT INTO lms_master_chapters (
                title, description, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            chapter['chapter_title'],
            chapter['description'] or '',
            master_status,
            actor_user_id,
            now,
            now,
        )
    )
    master_chapter_id = cur.lastrowid

    cur.execute(
        """
            INSERT INTO lms_program_chapters (
                program_id, master_chapter_id, chapter_order, custom_title, is_visible, created_at
            ) VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            program_id,
            master_chapter_id,
            chapter['chapter_order'] if chapter['chapter_order'] else 1,
            None,
            now,
        )
    )
    link_id = cur.lastrowid

    migrated_count = 0
    for topic in topics:
        topic_status = 'active' if topic['is_active'] else 'archived'
        cur.execute(
            """
                INSERT INTO lms_master_topics (
                    master_chapter_id, title, short_description, topic_order,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_chapter_id,
                topic['topic_title'],
                topic['short_description'] or '',
                topic['topic_order'] if topic['topic_order'] else 1,
                topic_status,
                now,
                now,
            )
        )
        master_topic_id = cur.lastrowid

        # Reuse existing content rows by tagging them with master_topic_id.
        cur.execute(
            """
                UPDATE lms_topic_contents
                SET master_topic_id = ?
                WHERE topic_id = ?
                  AND (master_topic_id IS NULL OR master_topic_id = '')
            """,
            (master_topic_id, topic['id'])
        )
        cur.execute(
            """
                UPDATE lms_topic_attachments
                SET master_topic_id = ?
                WHERE topic_id = ?
                  AND (master_topic_id IS NULL OR master_topic_id = '')
            """,
            (master_topic_id, topic['id'])
        )

        # Bridge map points master topic to original legacy topic for future edits/uploads.
        cur.execute(
            """
                INSERT INTO lms_master_topic_bridge (master_topic_id, legacy_topic_id, created_at)
                VALUES (?, ?, ?)
            """,
            (master_topic_id, topic['id'], now)
        )
        migrated_count += 1

    _renumber_program_chapter_links(cur, program_id)

    return {
        'master_chapter_id': master_chapter_id,
        'program_link_id': link_id,
        'migrated_topics': migrated_count,
        'legacy_chapter_title': chapter['chapter_title'],
    }, None


def _ensure_master_bridge_topic(cur, master_topic_id, master_topic_title):
    """Return a dedicated legacy topic_id used only to satisfy FK/topic_id NOT NULL for master-topic content rows."""
    existing = cur.execute(
        "SELECT legacy_topic_id FROM lms_master_topic_bridge WHERE master_topic_id = ?",
        (master_topic_id,)
    ).fetchone()
    if existing:
        return existing['legacy_topic_id']

    now = datetime.now().isoformat(timespec='seconds')

    bridge_program = cur.execute(
        "SELECT id FROM lms_programs WHERE slug = ?",
        (_MASTER_BRIDGE_PROGRAM_SLUG,)
    ).fetchone()
    if bridge_program:
        bridge_program_id = bridge_program['id']
    else:
        cur.execute(
            """
                INSERT INTO lms_programs (
                    course_id, program_name, slug, description, thumbnail_path,
                    is_published, is_active, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                _MASTER_BRIDGE_PROGRAM_NAME,
                _MASTER_BRIDGE_PROGRAM_SLUG,
                'System-only bridge program for reusable master-topic content compatibility.',
                '',
                0,
                0,
                session.get('user_id'),
                now,
                now,
            )
        )
        bridge_program_id = cur.lastrowid

    bridge_chapter = cur.execute(
        """
            SELECT id
            FROM lms_chapters
            WHERE program_id = ? AND chapter_title = ?
            ORDER BY id ASC
            LIMIT 1
        """,
        (bridge_program_id, _MASTER_BRIDGE_CHAPTER_TITLE)
    ).fetchone()
    if bridge_chapter:
        bridge_chapter_id = bridge_chapter['id']
    else:
        cur.execute(
            """
                INSERT INTO lms_chapters (
                    program_id, chapter_title, chapter_order, description,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bridge_program_id,
                _MASTER_BRIDGE_CHAPTER_TITLE,
                1,
                'System bridge chapter for master-topic content compatibility.',
                0,
                now,
                now,
            )
        )
        bridge_chapter_id = cur.lastrowid

    cur.execute(
        """
            INSERT INTO lms_topics (
                chapter_id, topic_title, topic_order, short_description,
                estimated_minutes, content_type, is_preview, is_active,
                is_required, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            bridge_chapter_id,
            f'[MASTER BRIDGE] {master_topic_title}',
            1,
            'System bridge topic for master content rows.',
            None,
            'lesson',
            0,
            0,
            0,
            now,
            now,
        )
    )
    legacy_topic_id = cur.lastrowid

    cur.execute(
        """
            INSERT INTO lms_master_topic_bridge (master_topic_id, legacy_topic_id, created_at)
            VALUES (?, ?, ?)
        """,
        (master_topic_id, legacy_topic_id, now)
    )
    return legacy_topic_id


# File Upload Handler
def upload_file(file_obj, content_type):
    """
    Save uploaded file to static/lms/<subdir>/ and return the Flask static path.
    content_type: 'pdf', 'download', or 'interactive_image'
    Returns: (success: bool, path_or_error: str)
    """
    if not file_obj or file_obj.filename == '':
        return False, f"No file selected"

    allowed_exts = {
        'pdf':               {'pdf'},
        'download':          {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'txt', 'ppt', 'pptx'},
        'interactive_image': _ALLOWED_IMAGE_EXTS,
    }
    max_sizes = {
        'pdf':               50 * 1024 * 1024,   # 50 MB
        'download':          100 * 1024 * 1024,  # 100 MB
        'interactive_image': 10 * 1024 * 1024,   # 10 MB
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

    if content_type == 'pdf':
        subdir = 'pdfs'
    elif content_type == 'interactive_image':
        subdir = 'images'
    else:
        subdir = 'downloads'

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'lms', subdir))
    os.makedirs(base_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
    unique_filename = timestamp + filename
    full_path = os.path.join(base_dir, unique_filename)

    try:
        file_obj.save(full_path)
        # Store as Flask static path: static/lms/<subdir>/filename
        return True, f"static/lms/{subdir}/{unique_filename}"
    except Exception as e:
        return False, f"Error saving file: {str(e)}"


# ── Demo Mode ──────────────────────────────────────────────────────────────
@lms_admin_bp.route('/demo/launch')
@login_required
def launch_demo():
    """Start a read-only demo session in the student portal (admin only)."""
    # Preserve admin session keys; inject a demo student identity
    session['student_id']   = 0          # sentinel: 0 means demo (never a real student pk)
    session['student_name'] = 'Demo Student'
    session['student_code'] = 'DEMO'
    session['demo_mode']    = True
    log_activity(session.get('user_id'), session.get('branch_id'), 'launch_demo', 'lms', None, f"{session.get('role','user').title()} launched demo student view")
    flash('Demo mode active — you are viewing the student portal in read-only mode.', 'info')
    return redirect(url_for('students.dashboard'))


@lms_admin_bp.route('/demo/exit')
def exit_demo():
    """End demo session and return to LMS admin."""
    for key in ('student_id', 'student_name', 'student_code', 'demo_mode'):
        session.pop(key, None)
    return redirect(url_for('lms_admin.dashboard'))


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
        
        # Get all programs with related information and content coverage.
        # Counts include both legacy chapters/topics and linked master chapters/topics.
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
                (
                    (SELECT COUNT(DISTINCT lc2.id)
                     FROM lms_chapters lc2
                     WHERE lc2.program_id = lp.id)
                    +
                    (SELECT COUNT(DISTINCT pc.master_chapter_id)
                     FROM lms_program_chapters pc
                     WHERE pc.program_id = lp.id)
                ) as chapter_count,
                (
                    (SELECT COUNT(*)
                     FROM lms_topics lt
                     JOIN lms_chapters lc2 ON lc2.id = lt.chapter_id
                     WHERE lc2.program_id = lp.id)
                    +
                    (SELECT COUNT(*)
                     FROM lms_master_topics mt
                     JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                     WHERE pc.program_id = lp.id
                       AND mt.status = 'active')
                ) as total_topics,
                (
                    (SELECT COUNT(DISTINCT lt.id)
                     FROM lms_topics lt
                     JOIN lms_chapters lc2 ON lc2.id = lt.chapter_id
                     JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
                     WHERE lc2.program_id = lp.id)
                    +
                    (SELECT COUNT(DISTINCT mt.id)
                     FROM lms_master_topics mt
                     JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                     JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                     WHERE pc.program_id = lp.id
                       AND mt.status = 'active')
                ) as topics_with_content
            FROM lms_programs lp
            LEFT JOIN courses c ON lp.course_id = c.id
            WHERE lp.slug != ?
            ORDER BY lp.created_at DESC
        """, (_MASTER_BRIDGE_PROGRAM_SLUG,))
        programs = cur.fetchall()
        
        return render_template('lms_programs.html', programs=programs)
    finally:
        conn.close()


@lms_admin_bp.route('/master/chapters', methods=['GET'])
@login_required
def list_master_chapters():
    """List reusable master chapters for the content library."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
                SELECT
                    mc.id,
                    mc.title,
                    mc.description,
                    mc.status,
                    mc.created_at,
                    mc.updated_at,
                    COUNT(mt.id) AS topic_count
                FROM lms_master_chapters mc
                LEFT JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
                GROUP BY mc.id
                ORDER BY mc.created_at DESC
            """
        )
        chapters = cur.fetchall()
        return render_template('master_chapters.html', chapters=chapters)
    finally:
        conn.close()


@lms_admin_bp.route('/master/chapter/new', methods=['GET', 'POST'])
@lms_content_manager_required
def master_chapter_new():
    """Create a reusable master chapter."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            status = request.form.get('status', 'active').strip().lower()

            if not title:
                flash('Chapter title is required.', 'danger')
                return redirect(url_for('lms_admin.master_chapter_new'))

            if status not in ('active', 'archived'):
                status = 'active'

            now = datetime.now().isoformat(timespec='seconds')
            cur.execute(
                """
                    INSERT INTO lms_master_chapters (
                        title,
                        description,
                        status,
                        created_by,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, description, status, session.get('user_id'), now, now)
            )
            chapter_id = cur.lastrowid
            conn.commit()

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_master_chapters',
                record_id=chapter_id,
                description=f'Created master chapter: {title}'
            )
            flash('Master chapter created successfully.', 'success')
            return redirect(url_for('lms_admin.list_master_chapters'))

        return render_template('master_chapter_form.html', chapter=None)
    finally:
        conn.close()


@lms_admin_bp.route('/master/chapter/<int:master_chapter_id>/edit', methods=['GET', 'POST'])
@lms_content_manager_required
def master_chapter_edit(master_chapter_id):
    """Edit reusable master chapter metadata."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        chapter = cur.execute(
            """
                SELECT id, title, description, status, created_at, updated_at
                FROM lms_master_chapters
                WHERE id = ?
            """,
            (master_chapter_id,)
        ).fetchone()

        if not chapter:
            flash('Master chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            status = request.form.get('status', 'active').strip().lower()

            if not title:
                flash('Chapter title is required.', 'danger')
                return redirect(url_for('lms_admin.master_chapter_edit', master_chapter_id=master_chapter_id))

            if status not in ('active', 'archived'):
                status = 'active'

            now = datetime.now().isoformat(timespec='seconds')
            cur.execute(
                """
                    UPDATE lms_master_chapters
                    SET title = ?,
                        description = ?,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                """,
                (title, description, status, now, master_chapter_id)
            )
            conn.commit()

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='update',
                module_name='lms_master_chapters',
                record_id=master_chapter_id,
                description=f'Updated master chapter: {title}'
            )
            flash('Master chapter updated successfully.', 'success')
            return redirect(url_for('lms_admin.list_master_chapters'))

        return render_template('master_chapter_form.html', chapter=chapter)
    finally:
        conn.close()


@lms_admin_bp.route('/master/chapter/<int:master_chapter_id>/archive', methods=['POST'])
@admin_required
def master_chapter_archive(master_chapter_id):
    """Archive a master chapter (soft delete)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        chapter = cur.execute(
            "SELECT id, title FROM lms_master_chapters WHERE id = ?",
            (master_chapter_id,)
        ).fetchone()
        if not chapter:
            flash('Master chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        now = datetime.now().isoformat(timespec='seconds')
        cur.execute(
            """
                UPDATE lms_master_chapters
                SET status = 'archived',
                    updated_at = ?
                WHERE id = ?
            """,
            (now, master_chapter_id)
        )
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='archive',
            module_name='lms_master_chapters',
            record_id=master_chapter_id,
            description=f'Archived master chapter: {chapter["title"]}'
        )
        flash('Master chapter archived.', 'success')
        return redirect(url_for('lms_admin.list_master_chapters'))
    finally:
        conn.close()


@lms_admin_bp.route('/master/chapter/<int:master_chapter_id>/topics', methods=['GET'])
@login_required
def list_master_topics(master_chapter_id):
    """List master topics under one master chapter."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        chapter = cur.execute(
            """
                SELECT id, title, description, status, created_at, updated_at
                FROM lms_master_chapters
                WHERE id = ?
            """,
            (master_chapter_id,)
        ).fetchone()
        if not chapter:
            flash('Master chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        topics = cur.execute(
            """
                SELECT
                    mt.id,
                    mt.master_chapter_id,
                    mt.title,
                    mt.short_description,
                    mt.topic_order,
                    mt.status,
                    mt.created_at,
                    mt.updated_at,
                    COUNT(ltc.id) AS content_count
                FROM lms_master_topics mt
                LEFT JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                WHERE mt.master_chapter_id = ?
                GROUP BY mt.id
                ORDER BY mt.topic_order ASC, mt.id ASC
            """,
            (master_chapter_id,)
        ).fetchall()

        return render_template('master_topics.html', chapter=chapter, topics=topics)
    finally:
        conn.close()


@lms_admin_bp.route('/master/topic/<int:master_topic_id>/contents', methods=['GET'])
@login_required
def list_master_topic_contents(master_topic_id):
    """List one-per-type content slots for a master topic."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        topic = cur.execute(
            """
                SELECT
                    mt.id,
                    mt.master_chapter_id,
                    mt.title,
                    mt.topic_order,
                    mt.short_description,
                    mt.status,
                    mc.title AS chapter_title
                FROM lms_master_topics mt
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                WHERE mt.id = ?
            """,
            (master_topic_id,)
        ).fetchone()
        if not topic:
            flash('Master topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        video_content = cur.execute(
            """
                SELECT * FROM lms_topic_contents
                WHERE master_topic_id = ? AND content_mode = 'youtube'
                ORDER BY display_order ASC LIMIT 1
            """,
            (master_topic_id,)
        ).fetchone()
        lesson_content = cur.execute(
            """
                SELECT * FROM lms_topic_contents
                WHERE master_topic_id = ? AND content_mode IN ('pdf', 'rich_text', 'interactive_image')
                ORDER BY display_order ASC LIMIT 1
            """,
            (master_topic_id,)
        ).fetchone()
        download_content = cur.execute(
            """
                SELECT * FROM lms_topic_contents
                WHERE master_topic_id = ? AND content_mode = 'download'
                ORDER BY display_order ASC LIMIT 1
            """,
            (master_topic_id,)
        ).fetchone()

        data = {
            'chapter': {
                'id': topic['master_chapter_id'],
                'title': topic['chapter_title'],
            },
            'topic': topic,
            'video_content': video_content,
            'lesson_content': lesson_content,
            'download_content': download_content,
        }
        return render_template('master_topic_contents.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/master/topic/<int:master_topic_id>/content/new', methods=['GET', 'POST'])
@lms_content_manager_required
def master_content_new(master_topic_id):
    """Add content to master topic using compatibility bridge topic_id + master_topic_id."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        topic = cur.execute(
            """
                SELECT
                    mt.id,
                    mt.master_chapter_id,
                    mt.title,
                    mc.title AS chapter_title
                FROM lms_master_topics mt
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                WHERE mt.id = ?
            """,
            (master_topic_id,)
        ).fetchone()
        if not topic:
            flash('Master topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content_mode = request.form.get('content_mode', 'youtube')
            description = request.form.get('content_body', '').strip()
            display_order = request.form.get('display_order', '1')
            external_url = request.form.get('external_url', '').strip()

            if content_mode == 'rich_text' and not title:
                title = topic['title']

            if not title:
                flash('Content title is required.', 'danger')
                return redirect(url_for('lms_admin.master_content_new', master_topic_id=master_topic_id))

            if content_mode not in ['youtube', 'pdf', 'rich_text', 'download']:
                content_mode = 'youtube'

            try:
                display_order = int(display_order) if display_order else 1
            except ValueError:
                display_order = 1

            file_path = ''
            hotspots_json = ''

            if content_mode == 'youtube':
                if not external_url:
                    flash('YouTube URL is required.', 'danger')
                    return redirect(url_for('lms_admin.master_content_new', master_topic_id=master_topic_id))
            elif content_mode in ['pdf', 'download']:
                file_field = 'pdf_file' if content_mode == 'pdf' else 'download_file'
                if file_field not in request.files or not request.files[file_field].filename:
                    flash('Please select a file to upload.', 'danger')
                    return redirect(url_for('lms_admin.master_content_new', master_topic_id=master_topic_id))
                success, result = upload_file(request.files[file_field], content_mode)
                if not success:
                    flash(f'Upload failed: {result}', 'danger')
                    return redirect(url_for('lms_admin.master_content_new', master_topic_id=master_topic_id))
                file_path = result
            elif content_mode == 'rich_text':
                description = sanitize_rich_text(description)
                if not description.strip():
                    flash('Rich text content cannot be empty.', 'danger')
                    return redirect(url_for('lms_admin.master_content_new', master_topic_id=master_topic_id))

            if content_mode in ('pdf', 'rich_text'):
                existing = cur.execute(
                    """
                        SELECT id FROM lms_topic_contents
                        WHERE master_topic_id = ? AND content_mode IN ('pdf', 'rich_text', 'interactive_image')
                    """,
                    (master_topic_id,)
                ).fetchone()
            else:
                existing = cur.execute(
                    """
                        SELECT id FROM lms_topic_contents
                        WHERE master_topic_id = ? AND content_mode = ?
                    """,
                    (master_topic_id, content_mode)
                ).fetchone()

            if existing:
                flash('This content slot is already configured for the master topic. Edit or remove it first.', 'danger')
                return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=master_topic_id))

            bridge_topic_id = _ensure_master_bridge_topic(cur, master_topic_id, topic['title'])
            now = datetime.now().isoformat(timespec='seconds')
            cur.execute(
                """
                    INSERT INTO lms_topic_contents (
                        topic_id, master_topic_id, content_title, content_mode,
                        content_body, external_url, file_path, hotspots_json,
                        display_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bridge_topic_id,
                    master_topic_id,
                    title,
                    content_mode,
                    description,
                    external_url if content_mode == 'youtube' else '',
                    file_path,
                    hotspots_json,
                    display_order,
                    now,
                    now,
                )
            )
            content_id = cur.lastrowid
            conn.commit()

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_topic_contents',
                record_id=content_id,
                description=f'Created master-topic content: {title} for master topic {topic["title"]}'
            )

            flash('Master topic content added successfully.', 'success')
            return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=master_topic_id))

        next_order_row = cur.execute(
            "SELECT MAX(display_order) AS max_order FROM lms_topic_contents WHERE master_topic_id = ?",
            (master_topic_id,)
        ).fetchone()
        next_order = (next_order_row['max_order'] or 0) + 1

        program = {'id': 0, 'program_name': 'Master Library'}
        chapter = {'id': topic['master_chapter_id'], 'chapter_title': topic['chapter_title']}
        template_topic = {'id': topic['id'], 'topic_title': topic['title']}
        preset_type = request.args.get('type', '')
        if preset_type not in ['youtube', 'pdf', 'rich_text', 'interactive_image', 'download']:
            preset_type = ''

        return render_template(
            'lms_admin/lms_topic_content_form.html',
            program=program,
            chapter=chapter,
            topic=template_topic,
            content=None,
            next_order=next_order,
            preset_type=preset_type,
            is_master_topic=True,
        )
    finally:
        conn.close()


@lms_admin_bp.route('/master/chapter/<int:master_chapter_id>/topic/new', methods=['GET', 'POST'])
@lms_content_manager_required
def master_topic_new(master_chapter_id):
    """Create a reusable master topic (metadata only in Phase 2)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        chapter = cur.execute(
            "SELECT id, title, status FROM lms_master_chapters WHERE id = ?",
            (master_chapter_id,)
        ).fetchone()
        if not chapter:
            flash('Master chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            short_description = request.form.get('short_description', '').strip()
            topic_order = request.form.get('topic_order', '1').strip()
            status = request.form.get('status', 'active').strip().lower()

            if not title:
                flash('Topic title is required.', 'danger')
                return redirect(url_for('lms_admin.master_topic_new', master_chapter_id=master_chapter_id))

            try:
                topic_order = int(topic_order) if topic_order else 1
            except ValueError:
                topic_order = 1

            if status not in ('active', 'archived'):
                status = 'active'

            now = datetime.now().isoformat(timespec='seconds')
            cur.execute(
                """
                    INSERT INTO lms_master_topics (
                        master_chapter_id,
                        title,
                        short_description,
                        topic_order,
                        status,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (master_chapter_id, title, short_description, topic_order, status, now, now)
            )
            topic_id = cur.lastrowid
            conn.commit()

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_master_topics',
                record_id=topic_id,
                description=f'Created master topic: {title} in chapter {chapter["title"]}'
            )

            flash('Master topic created. Content slots will be enabled in the next compatibility step.', 'success')
            return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

        next_order_row = cur.execute(
            "SELECT MAX(topic_order) AS max_order FROM lms_master_topics WHERE master_chapter_id = ?",
            (master_chapter_id,)
        ).fetchone()
        next_order = (next_order_row['max_order'] or 0) + 1

        return render_template('master_topic_form.html', chapter=chapter, topic=None, next_order=next_order)
    finally:
        conn.close()


@lms_admin_bp.route('/master/topic/<int:master_topic_id>/edit', methods=['GET', 'POST'])
@lms_content_manager_required
def master_topic_edit(master_topic_id):
    """Edit reusable master topic metadata."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        topic = cur.execute(
            """
                SELECT
                    mt.id,
                    mt.master_chapter_id,
                    mt.title,
                    mt.short_description,
                    mt.topic_order,
                    mt.status,
                    mt.created_at,
                    mt.updated_at,
                    mc.title AS chapter_title
                FROM lms_master_topics mt
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                WHERE mt.id = ?
            """,
            (master_topic_id,)
        ).fetchone()
        if not topic:
            flash('Master topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        chapter = {
            'id': topic['master_chapter_id'],
            'title': topic['chapter_title'],
        }

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            short_description = request.form.get('short_description', '').strip()
            topic_order = request.form.get('topic_order', str(topic['topic_order'])).strip()
            status = request.form.get('status', 'active').strip().lower()

            if not title:
                flash('Topic title is required.', 'danger')
                return redirect(url_for('lms_admin.master_topic_edit', master_topic_id=master_topic_id))

            try:
                topic_order = int(topic_order) if topic_order else 1
            except ValueError:
                topic_order = 1

            if status not in ('active', 'archived'):
                status = 'active'

            now = datetime.now().isoformat(timespec='seconds')
            cur.execute(
                """
                    UPDATE lms_master_topics
                    SET title = ?,
                        short_description = ?,
                        topic_order = ?,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                """,
                (title, short_description, topic_order, status, now, master_topic_id)
            )
            conn.commit()

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='update',
                module_name='lms_master_topics',
                record_id=master_topic_id,
                description=f'Updated master topic: {title}'
            )

            flash('Master topic updated.', 'success')
            return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=topic['master_chapter_id']))

        return render_template('master_topic_form.html', chapter=chapter, topic=topic, next_order=None)
    finally:
        conn.close()


@lms_admin_bp.route('/master/topic/<int:master_topic_id>/archive', methods=['POST'])
@admin_required
def master_topic_archive(master_topic_id):
    """Archive a master topic (soft delete)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        topic = cur.execute(
            "SELECT id, master_chapter_id, title FROM lms_master_topics WHERE id = ?",
            (master_topic_id,)
        ).fetchone()
        if not topic:
            flash('Master topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        now = datetime.now().isoformat(timespec='seconds')
        cur.execute(
            """
                UPDATE lms_master_topics
                SET status = 'archived',
                    updated_at = ?
                WHERE id = ?
            """,
            (now, master_topic_id)
        )
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='archive',
            module_name='lms_master_topics',
            record_id=master_topic_id,
            description=f'Archived master topic: {topic["title"]}'
        )

        flash('Master topic archived.', 'success')
        return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=topic['master_chapter_id']))
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
@admin_required
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
@admin_required
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
        # Include master-linked chapters in the top-level chapter metric.
        cur.execute(
            "SELECT COUNT(*) as count FROM lms_program_chapters WHERE program_id = ?",
            (program_id,)
        )
        linked_master_chapters = cur.fetchone()['count']
        total_chapters = len(chapters) + (linked_master_chapters or 0)
        
        # Get total topics count
        cur.execute("""
            SELECT (
                (SELECT COUNT(*)
                 FROM lms_topics lt
                 JOIN lms_chapters lc ON lc.id = lt.chapter_id
                 WHERE lc.program_id = ?)
                +
                (SELECT COUNT(*)
                 FROM lms_master_topics mt
                 JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                 WHERE pc.program_id = ?
                   AND mt.status = 'active')
            ) as count
        """, (program_id, program_id))
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
            'linked_master_chapters': linked_master_chapters or 0,
            'total_topics': total_topics,
            'total_students': total_students,
            'total_tests': total_tests,
            'resources': resources,
            'resource_count': len(resources),
            'recent_activity': recent_activity
        }

        # Fetch topics for each chapter (for accordion display)
        topics_by_chapter = {}
        if chapters:
            placeholders = ','.join('?' for _ in chapters)
            chapter_ids = [c['id'] for c in chapters]
            cur.execute(f"""
                SELECT lt.id, lt.chapter_id, lt.topic_title, lt.topic_order, lt.content_type,
                       lt.estimated_minutes, lt.is_active, lt.is_preview,
                       COUNT(ltc.id) AS content_count
                FROM lms_topics lt
                LEFT JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
                WHERE lt.chapter_id IN ({placeholders})
                GROUP BY lt.id
                ORDER BY lt.chapter_id, lt.topic_order
            """, chapter_ids)
            for t in cur.fetchall():
                topics_by_chapter.setdefault(t['chapter_id'], []).append(dict(t))
        summary['topics_by_chapter'] = topics_by_chapter

        # Content coverage: count topics that have each content type
        if total_topics > 0:
            cur.execute("""
                SELECT
                    (
                        (SELECT COUNT(DISTINCT lt.id)
                         FROM lms_topics lt
                         JOIN lms_chapters lc ON lc.id = lt.chapter_id
                         JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
                         WHERE lc.program_id = ?
                           AND ltc.content_mode = 'youtube')
                        +
                        (SELECT COUNT(DISTINCT mt.id)
                         FROM lms_master_topics mt
                         JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                         JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                         WHERE pc.program_id = ?
                           AND mt.status = 'active'
                           AND ltc.content_mode = 'youtube')
                    ) AS topics_with_video,
                    (
                        (SELECT COUNT(DISTINCT lt.id)
                         FROM lms_topics lt
                         JOIN lms_chapters lc ON lc.id = lt.chapter_id
                         JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
                         WHERE lc.program_id = ?
                           AND ltc.content_mode = 'pdf')
                        +
                        (SELECT COUNT(DISTINCT mt.id)
                         FROM lms_master_topics mt
                         JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                         JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                         WHERE pc.program_id = ?
                           AND mt.status = 'active'
                           AND ltc.content_mode = 'pdf')
                    ) AS topics_with_pdf,
                    (
                        (SELECT COUNT(DISTINCT lt.id)
                         FROM lms_topics lt
                         JOIN lms_chapters lc ON lc.id = lt.chapter_id
                         JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
                         WHERE lc.program_id = ?
                           AND ltc.content_mode = 'download')
                        +
                        (SELECT COUNT(DISTINCT mt.id)
                         FROM lms_master_topics mt
                         JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                         JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                         WHERE pc.program_id = ?
                           AND mt.status = 'active'
                           AND ltc.content_mode = 'download')
                    ) AS topics_with_download
            """, (program_id, program_id, program_id, program_id, program_id, program_id))
            coverage = cur.fetchone()
            summary['topics_with_video'] = coverage['topics_with_video'] or 0
            summary['topics_with_pdf'] = coverage['topics_with_pdf'] or 0
            summary['topics_with_download'] = coverage['topics_with_download'] or 0
        else:
            summary['topics_with_video'] = 0
            summary['topics_with_pdf'] = 0
            summary['topics_with_download'] = 0

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
        
        # Get all legacy chapters with topic count and content coverage
        cur.execute("""
            SELECT 
                lc.id,
                lc.chapter_title,
                lc.chapter_order,
                lc.description,
                lc.is_active,
                lc.created_at,
                lc.updated_at,
                COUNT(DISTINCT lt.id) as topic_count,
                COUNT(DISTINCT CASE WHEN ltc.id IS NOT NULL THEN lt.id END) as topics_with_content,
                COUNT(DISTINCT CASE WHEN ltc.master_topic_id IS NOT NULL THEN lt.id END) as topics_mapped_master
            FROM lms_chapters lc
            LEFT JOIN lms_topics lt ON lc.id = lt.chapter_id
            LEFT JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
            WHERE lc.program_id = ?
            GROUP BY lc.id
            ORDER BY lc.chapter_order ASC
        """, (program_id,))
        chapters = cur.fetchall()

        # Get linked master chapters for this program
        cur.execute(
            """
                SELECT
                    pc.id AS link_id,
                    pc.program_id,
                    pc.master_chapter_id,
                    pc.chapter_order,
                    pc.custom_title,
                    pc.is_visible,
                    pc.created_at,
                    mc.title AS master_title,
                    mc.description,
                    mc.status,
                    COUNT(DISTINCT mt.id) AS topic_count,
                    COUNT(DISTINCT CASE WHEN ltc.id IS NOT NULL THEN mt.id END) AS topics_with_content
                FROM lms_program_chapters pc
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                LEFT JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id AND mt.status = 'active'
                LEFT JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                WHERE pc.program_id = ?
                GROUP BY pc.id
                ORDER BY pc.chapter_order ASC, pc.id ASC
            """,
            (program_id,)
        )
        linked_master_chapters = cur.fetchall()

        # Get available active master chapters not yet linked to this program
        cur.execute(
            """
                SELECT
                    mc.id,
                    mc.title,
                    mc.description,
                    mc.status,
                    COUNT(mt.id) AS topic_count
                FROM lms_master_chapters mc
                LEFT JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id AND mt.status = 'active'
                WHERE mc.status = 'active'
                  AND mc.id NOT IN (
                      SELECT master_chapter_id
                      FROM lms_program_chapters
                      WHERE program_id = ?
                  )
                GROUP BY mc.id
                ORDER BY mc.title ASC
            """,
            (program_id,)
        )
        available_master_chapters = cur.fetchall()
        
        data = {
            'program': program,
            'chapters': chapters,
            'linked_master_chapters': linked_master_chapters,
            'available_master_chapters': available_master_chapters,
            'legacy_chapter_count': len(chapters),
            'linked_master_chapter_count': len(linked_master_chapters),
            'total_chapters': len(chapters) + len(linked_master_chapters),
        }
        
        return render_template('lms_chapters.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter/<int:chapter_id>/migrate-to-master-pilot', methods=['POST'])
@admin_required
def migrate_legacy_chapter_pilot(program_id, chapter_id):
    """Phase 5 pilot: migrate one legacy chapter to master tables for one program."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        program = cur.execute(
            "SELECT id, program_name FROM lms_programs WHERE id = ?",
            (program_id,)
        ).fetchone()
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        # Snapshot backup before any write.
        backup_path = _create_db_backup_snapshot(conn, label='phase5_pilot')

        migration, error = _migrate_legacy_chapter_to_master(
            cur,
            program_id=program_id,
            chapter_id=chapter_id,
            actor_user_id=session.get('user_id'),
        )

        if error:
            conn.rollback()
            flash(error, 'warning')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='migrate',
            module_name='lms_phase5_pilot',
            record_id=migration['master_chapter_id'],
            description=(
                f"Phase 5 pilot migrated chapter '{migration['legacy_chapter_title']}' "
                f"to master chapter id {migration['master_chapter_id']} with "
                f"{migration['migrated_topics']} topics; backup={os.path.basename(backup_path)}"
            )
        )

        flash(
            f"Pilot migration completed: '{migration['legacy_chapter_title']}' -> master chapter "
            f"({migration['migrated_topics']} topics). Backup: {os.path.basename(backup_path)}",
            'success'
        )
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    except Exception as e:
        conn.rollback()
        flash(f'Pilot migration failed: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    finally:
        conn.close()


@lms_admin_bp.route('/phase6/rollout', methods=['GET'])
@admin_required
def phase6_rollout_view():
    """Phase 6 rollout dashboard: discover unmigrated legacy chapters by program."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        programs = cur.execute(
            """
                SELECT id, program_name, slug
                FROM lms_programs
                WHERE is_active = 1
                  AND slug != ?
                ORDER BY program_name ASC
            """,
            (_MASTER_BRIDGE_PROGRAM_SLUG,)
        ).fetchall()

        rollout_rows = []
        for p in programs:
            legacy_chapters = cur.execute(
                """
                    SELECT
                        lc.id,
                        lc.chapter_title,
                        lc.chapter_order,
                        (
                            SELECT COUNT(*)
                            FROM lms_topics lt
                            WHERE lt.chapter_id = lc.id
                        ) AS topic_count
                    FROM lms_chapters lc
                    WHERE lc.program_id = ?
                    ORDER BY lc.chapter_order ASC, lc.id ASC
                """,
                (p['id'],)
            ).fetchall()

            unmigrated = []
            for ch in legacy_chapters:
                mapped = cur.execute(
                    """
                        SELECT 1
                        FROM lms_master_topic_bridge b
                        JOIN lms_topics t ON t.id = b.legacy_topic_id
                        WHERE t.chapter_id = ?
                        LIMIT 1
                    """,
                    (ch['id'],)
                ).fetchone()
                if not mapped:
                    unmigrated.append(ch)

            linked_master_count = cur.execute(
                "SELECT COUNT(*) AS c FROM lms_program_chapters WHERE program_id = ?",
                (p['id'],)
            ).fetchone()['c']

            rollout_rows.append({
                'program': p,
                'linked_master_count': linked_master_count,
                'legacy_total': len(legacy_chapters),
                'unmigrated': unmigrated,
            })

        return render_template('lms_admin/phase6_rollout.html', rows=rollout_rows)
    finally:
        conn.close()


@lms_admin_bp.route('/phase6/rollout/migrate', methods=['POST'])
@admin_required
def phase6_rollout_migrate():
    """Phase 6 controlled migration for selected legacy chapters of one program."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        program_id = _strict_positive_int(request.form.get('program_id'))
        if program_id is None:
            flash('Invalid program selected.', 'danger')
            return redirect(url_for('lms_admin.phase6_rollout_view'))

        program = cur.execute(
            "SELECT id, program_name FROM lms_programs WHERE id = ?",
            (program_id,)
        ).fetchone()
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.phase6_rollout_view'))

        selected_raw = request.form.getlist('chapter_ids')
        selected_ids = []
        for value in selected_raw:
            parsed = _strict_positive_int(value)
            if parsed is not None:
                selected_ids.append(parsed)

        if not selected_ids:
            flash('No chapters selected for migration.', 'warning')
            return redirect(url_for('lms_admin.phase6_rollout_view'))

        # Validate chapter ownership
        owned_ids = {
            row['id']
            for row in cur.execute(
                "SELECT id FROM lms_chapters WHERE program_id = ?",
                (program_id,)
            ).fetchall()
        }
        chapter_ids = [cid for cid in selected_ids if cid in owned_ids]
        if not chapter_ids:
            flash('Selected chapters are not valid for this program.', 'danger')
            return redirect(url_for('lms_admin.phase6_rollout_view'))

        backup_path = _create_db_backup_snapshot(conn, label='phase6_rollout')

        migrated = []
        skipped = []
        for chapter_id in chapter_ids:
            migration, error = _migrate_legacy_chapter_to_master(
                cur,
                program_id=program_id,
                chapter_id=chapter_id,
                actor_user_id=session.get('user_id'),
            )
            if error:
                skipped.append({'chapter_id': chapter_id, 'reason': error})
                continue
            migrated.append(migration)

        if not migrated:
            conn.rollback()
            flash('No chapters were migrated. ' + ('; '.join(s['reason'] for s in skipped[:2]) if skipped else ''), 'warning')
            return redirect(url_for('lms_admin.phase6_rollout_view'))

        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='migrate',
            module_name='lms_phase6_rollout',
            record_id=program_id,
            description=(
                f"Phase 6 rollout migrated {len(migrated)} chapter(s) in program {program['program_name']}; "
                f"skipped {len(skipped)}; backup={os.path.basename(backup_path)}"
            )
        )

        flash(
            f"Phase 6 rollout complete for {program['program_name']}: migrated {len(migrated)} chapter(s), "
            f"skipped {len(skipped)}. Backup: {os.path.basename(backup_path)}",
            'success'
        )
        return redirect(url_for('lms_admin.phase6_rollout_view'))
    except Exception as e:
        conn.rollback()
        flash(f'Phase 6 rollout failed: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.phase6_rollout_view'))
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/attach-chapter', methods=['POST'])
@lms_content_manager_required
def attach_master_chapter_to_program(program_id):
    """Attach an existing active master chapter to a program."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        program = cur.execute(
            "SELECT id, program_name FROM lms_programs WHERE id = ?",
            (program_id,)
        ).fetchone()
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        master_chapter_id = _strict_positive_int(request.form.get('master_chapter_id'))
        custom_title = request.form.get('custom_title', '').strip()
        desired_order = _strict_positive_int(request.form.get('chapter_order'))

        if master_chapter_id is None:
            flash('Please select a master chapter.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        master_chapter = cur.execute(
            "SELECT id, title, status FROM lms_master_chapters WHERE id = ?",
            (master_chapter_id,)
        ).fetchone()
        if not master_chapter:
            flash('Master chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
        if master_chapter['status'] != 'active':
            flash('Only active master chapters can be attached.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        already_linked = cur.execute(
            """
                SELECT id
                FROM lms_program_chapters
                WHERE program_id = ? AND master_chapter_id = ?
            """,
            (program_id, master_chapter_id)
        ).fetchone()
        if already_linked:
            flash('This master chapter is already linked to the program.', 'warning')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        max_row = cur.execute(
            "SELECT MAX(chapter_order) AS max_order FROM lms_program_chapters WHERE program_id = ?",
            (program_id,)
        ).fetchone()
        next_order = (max_row['max_order'] or 0) + 1
        insert_order = desired_order if desired_order else next_order

        now = datetime.now().isoformat(timespec='seconds')
        cur.execute(
            """
                INSERT INTO lms_program_chapters (
                    program_id,
                    master_chapter_id,
                    chapter_order,
                    custom_title,
                    is_visible,
                    created_at
                ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (program_id, master_chapter_id, insert_order, custom_title if custom_title else None, now)
        )
        new_link_id = cur.lastrowid

        link_ids = [
            row['id']
            for row in cur.execute(
                """
                    SELECT id
                    FROM lms_program_chapters
                    WHERE program_id = ? AND id != ?
                    ORDER BY chapter_order ASC, id ASC
                """,
                (program_id, new_link_id)
            ).fetchall()
        ]
        insert_index = min(max(insert_order, 1) - 1, len(link_ids))
        ordered_ids = link_ids[:insert_index] + [new_link_id] + link_ids[insert_index:]
        _renumber_program_chapter_links(cur, program_id, ordered_ids)

        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='create',
            module_name='lms_program_chapters',
            record_id=new_link_id,
            description=f'Attached master chapter {master_chapter["title"]} to program {program["program_name"]}'
        )
        flash('Master chapter attached successfully.', 'success')
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter-link/<int:link_id>/remove', methods=['POST'])
@lms_content_manager_required
def unlink_master_chapter_from_program(program_id, link_id):
    """Unlink a master chapter from a program without deleting master content."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        link_row = cur.execute(
            """
                SELECT pc.id, pc.program_id, mc.title AS master_title
                FROM lms_program_chapters pc
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE pc.id = ? AND pc.program_id = ?
            """,
            (link_id, program_id)
        ).fetchone()
        if not link_row:
            flash('Linked chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        cur.execute("DELETE FROM lms_program_chapters WHERE id = ?", (link_id,))
        _renumber_program_chapter_links(cur, program_id)
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_program_chapters',
            record_id=link_id,
            description=f'Unlinked master chapter {link_row["master_title"]} from program id {program_id}'
        )
        flash('Master chapter unlinked from program.', 'success')
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter-links/reorder', methods=['POST'])
@lms_content_manager_required
def reorder_program_master_chapters(program_id):
    """Reorder linked master chapters for one program."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        link_id = _strict_positive_int(request.form.get('link_id'))
        desired_order = _strict_positive_int(request.form.get('chapter_order'))

        if link_id is None or desired_order is None:
            flash('Invalid reorder request.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        rows = cur.execute(
            """
                SELECT id
                FROM lms_program_chapters
                WHERE program_id = ?
                ORDER BY chapter_order ASC, id ASC
            """,
            (program_id,)
        ).fetchall()
        existing_ids = [row['id'] for row in rows]
        if link_id not in existing_ids:
            flash('Linked chapter not found for this program.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        remaining_ids = [row_id for row_id in existing_ids if row_id != link_id]
        insert_index = min(max(desired_order, 1) - 1, len(remaining_ids))
        ordered_ids = remaining_ids[:insert_index] + [link_id] + remaining_ids[insert_index:]
        _renumber_program_chapter_links(cur, program_id, ordered_ids)
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='update',
            module_name='lms_program_chapters',
            record_id=link_id,
            description=f'Reordered linked master chapter in program id {program_id}'
        )
        flash('Linked chapter order updated.', 'success')
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter-link/<int:link_id>/toggle-visibility', methods=['POST'])
@lms_content_manager_required
def toggle_program_master_chapter_visibility(program_id, link_id):
    """Toggle visibility for a linked master chapter in one program."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        row = cur.execute(
            """
                SELECT id, is_visible
                FROM lms_program_chapters
                WHERE id = ? AND program_id = ?
            """,
            (link_id, program_id)
        ).fetchone()
        if not row:
            flash('Linked chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        new_visibility = 0 if row['is_visible'] else 1
        cur.execute(
            "UPDATE lms_program_chapters SET is_visible = ? WHERE id = ?",
            (new_visibility, link_id)
        )
        conn.commit()

        state_word = 'visible' if new_visibility else 'hidden'
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='update',
            module_name='lms_program_chapters',
            record_id=link_id,
            description=f'Set linked master chapter {link_id} to {state_word} in program id {program_id}'
        )
        flash(f'Linked chapter is now {state_word}.', 'success')
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter/new', methods=['GET', 'POST'])
@lms_content_manager_required
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
@lms_content_manager_required
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
@admin_required
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


@lms_admin_bp.route('/chapter/<int:chapter_id>/topics/reorder', methods=['POST'])
@lms_content_manager_required
def reorder_topics(chapter_id):
    """Reorder topics within a chapter and normalize topic_order sequentially."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        chapter = cur.execute(
            """
                SELECT id, chapter_title
                FROM lms_chapters
                WHERE id = ?
            """,
            (chapter_id,)
        ).fetchone()

        if not chapter:
            flash('Chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        topics = cur.execute(
            """
                SELECT id, topic_order
                FROM lms_topics
                WHERE chapter_id = ?
                ORDER BY topic_order ASC, id ASC
            """,
            (chapter_id,)
        ).fetchall()

        if not topics:
            flash('No topics found to reorder.', 'warning')
            return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

        payload = request.form.get('topic_orders', '').strip()
        requested_entries = []
        total_topics = len(topics)

        if payload:
            try:
                decoded = json.loads(payload)
                if isinstance(decoded, list):
                    requested_entries = decoded
            except json.JSONDecodeError:
                flash('Invalid reorder payload.', 'danger')
                return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

        if not isinstance(requested_entries, list) or len(requested_entries) != total_topics:
            flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
            return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

        valid_topic_ids = {row['id'] for row in topics}
        payload_topic_ids = []
        payload_orders = []

        for entry in requested_entries:
            if not isinstance(entry, dict):
                flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
                return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

            topic_id = _strict_positive_int(entry.get('id'))
            requested_order = _strict_positive_int(entry.get('order'))

            if topic_id is None or requested_order is None:
                flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
                return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

            payload_topic_ids.append(topic_id)
            payload_orders.append(requested_order)

        if set(payload_topic_ids) != valid_topic_ids or len(payload_topic_ids) != len(set(payload_topic_ids)):
            flash('Invalid topic selection for this chapter.', 'danger')
            return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

        valid_orders = set(range(1, total_topics + 1))
        if set(payload_orders) != valid_orders or len(payload_orders) != len(set(payload_orders)):
            flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
            return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))

        ranked = []
        for idx, entry in enumerate(requested_entries):
            ranked.append((int(entry['order']), idx, int(entry['id'])))

        ordered_topic_ids = [topic_id for _, _, topic_id in sorted(ranked, key=lambda x: (x[0], x[1]))]
        _renumber_chapter_topics(cur, chapter_id, ordered_topic_ids)

        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='update',
            module_name='lms_topics',
            record_id=chapter_id,
            description=f'Reordered topics in chapter {chapter["chapter_title"]}'
        )

        flash('Topic order updated successfully.', 'success')
        return redirect(url_for('lms_admin.list_topics', chapter_id=chapter_id))
    finally:
        conn.close()


@lms_admin_bp.route('/chapter/<int:chapter_id>/topic/new', methods=['GET', 'POST'])
@lms_content_manager_required
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

            # Place the new topic at the requested position, then normalize to 1..n.
            remaining_ids = [
                row['id']
                for row in cur.execute(
                    """
                        SELECT id
                        FROM lms_topics
                        WHERE chapter_id = ? AND id != ?
                        ORDER BY topic_order ASC, id ASC
                    """,
                    (chapter_id, topic_id)
                ).fetchall()
            ]
            insert_index = min(max(topic_order, 1) - 1, len(remaining_ids))
            ordered_topic_ids = remaining_ids[:insert_index] + [topic_id] + remaining_ids[insert_index:]
            _renumber_chapter_topics(cur, chapter_id, ordered_topic_ids)

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
@lms_content_manager_required
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

            # Reposition this topic inside its chapter and normalize order values.
            remaining_ids = [
                row['id']
                for row in cur.execute(
                    """
                        SELECT id
                        FROM lms_topics
                        WHERE chapter_id = ? AND id != ?
                        ORDER BY topic_order ASC, id ASC
                    """,
                    (topic['chapter_id'], topic_id)
                ).fetchall()
            ]
            insert_index = min(max(topic_order, 1) - 1, len(remaining_ids))
            ordered_topic_ids = remaining_ids[:insert_index] + [topic_id] + remaining_ids[insert_index:]
            _renumber_chapter_topics(cur, topic['chapter_id'], ordered_topic_ids)
            
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
@admin_required
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

        _renumber_chapter_topics(cur, topic['chapter_id'])

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
        
        # Fetch the first content item of each type (one-per-type system)
        video_content = cur.execute("""
            SELECT * FROM lms_topic_contents
            WHERE topic_id = ? AND content_mode = 'youtube'
            ORDER BY display_order ASC LIMIT 1
        """, (topic_id,)).fetchone()

        lesson_content = cur.execute("""
            SELECT * FROM lms_topic_contents
            WHERE topic_id = ? AND content_mode IN ('pdf', 'rich_text', 'interactive_image')
            ORDER BY display_order ASC LIMIT 1
        """, (topic_id,)).fetchone()

        download_content = cur.execute("""
            SELECT * FROM lms_topic_contents
            WHERE topic_id = ? AND content_mode = 'download'
            ORDER BY display_order ASC LIMIT 1
        """, (topic_id,)).fetchone()

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
            'video_content': video_content,
            'lesson_content': lesson_content,
            'download_content': download_content
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
@lms_content_manager_required
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

            # For rich_text, auto-use topic title if form didn't supply one
            if content_mode == 'rich_text' and not title:
                title = topic['topic_title']

            if not title:
                flash('Content title is required.', 'danger')
                return redirect(url_for('lms_admin.content_new', topic_id=topic_id))

            if content_mode not in ['youtube', 'pdf', 'rich_text', 'download']:
                content_mode = 'youtube'

            try:
                display_order = int(display_order) if display_order else 1
            except ValueError:
                display_order = 1

            file_path = ''
            hotspots_json = ''

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

            elif content_mode == 'rich_text':
                description = sanitize_rich_text(description)
                if not description.strip():
                    flash('Rich text content cannot be empty.', 'danger')
                    return redirect(url_for('lms_admin.content_new', topic_id=topic_id))

            # Enforce one-per-type: lesson content slot covers pdf, rich_text
            if content_mode in ('pdf', 'rich_text'):
                cur.execute(
                    "SELECT id FROM lms_topic_contents WHERE topic_id = ? AND content_mode IN ('pdf', 'rich_text', 'interactive_image')",
                    (topic_id,)
                )
            else:
                cur.execute(
                    "SELECT id FROM lms_topic_contents WHERE topic_id = ? AND content_mode = ?",
                    (topic_id, content_mode)
                )
            if cur.fetchone():
                mode_labels = {'youtube': 'Video', 'pdf': 'PDF', 'rich_text': 'Rich Text Lesson',
                               'interactive_image': 'Interactive Image', 'download': 'Download File'}
                flash(f'A {mode_labels.get(content_mode, content_mode)} is already set for this topic. Edit or remove it first.', 'danger')
                return redirect(url_for('lms_admin.list_topic_contents', topic_id=topic_id))

            now = datetime.now().isoformat(timespec='seconds')

            try:
                cur.execute("""
                    INSERT INTO lms_topic_contents (
                        topic_id, content_title, content_mode, content_body,
                        external_url, file_path, hotspots_json, display_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    topic_id, title, content_mode, description,
                    external_url if content_mode == 'youtube' else '',
                    file_path, hotspots_json, display_order, now, now
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
        
        # Read preset type from query string (e.g. ?type=youtube)
        preset_type = request.args.get('type', '')
        if preset_type not in ['youtube', 'pdf', 'rich_text', 'interactive_image', 'download']:
            preset_type = ''

        return render_template('lms_admin/lms_topic_content_form.html', program=program, chapter=chapter, topic=topic, content=None, next_order=next_order, preset_type=preset_type)
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
                ltc.hotspots_json,
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


# ── Inline Image Upload (for rich text hotspot embeds) ───────────────────────

@lms_admin_bp.route('/inline_image/upload', methods=['POST'])
@csrf.exempt
@lms_content_manager_required
def upload_inline_image():
    """AJAX: receive an image file, save to static/lms/images/inline/, return URL."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    file_obj = request.files['file']
    if not file_obj or file_obj.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    filename = secure_filename(file_obj.filename)
    if not filename:
        return jsonify({'success': False, 'error': 'Invalid filename'}), 400

    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in _ALLOWED_IMAGE_EXTS:
        return jsonify({'success': False, 'error': f'File type .{ext} not allowed. Allowed: jpg, jpeg, png, gif, webp'}), 400

    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > 10 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'File too large (max 10 MB)'}), 400

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'lms', 'images', 'inline'))
    os.makedirs(base_dir, exist_ok=True)

    unique_name = datetime.now().strftime('%Y%m%d_%H%M%S_') + filename
    try:
        file_obj.save(os.path.join(base_dir, unique_name))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, 'filename': unique_name,
                    'url': url_for('lms_admin.serve_inline_image', filename=unique_name)})


@lms_admin_bp.route('/inline_image/<path:filename>', methods=['GET'])
def serve_inline_image(filename):
    """Serve inline hotspot images — accessible to both admins and students."""
    if 'user_id' not in session and 'student_id' not in session:
        return 'Unauthorised', 403
    # Prevent path traversal
    safe_name = os.path.basename(filename)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'lms', 'images', 'inline'))
    ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                'gif': 'image/gif', 'webp': 'image/webp'}
    mimetype = mime_map.get(ext, 'image/jpeg')
    resp = send_from_directory(base_dir, safe_name, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'no-store, no-cache'
    return resp


@lms_admin_bp.route('/content/<int:content_id>/image', methods=['GET'])
@login_required
def serve_image_admin(content_id):
    """Serve interactive image for admin hotspot editor preview"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM lms_topic_contents WHERE id = ? AND content_mode = 'interactive_image'", (content_id,))
        row = cur.fetchone()
        if not row or not row['file_path']:
            return "Not found", 404
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        abs_path = os.path.join(base_dir, row['file_path'].replace('/', os.sep))
        ext = abs_path.rsplit('.', 1)[-1].lower()
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                    'gif': 'image/gif', 'webp': 'image/webp'}
        mimetype = mime_map.get(ext, 'image/jpeg')
        resp = send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), mimetype=mimetype)
        resp.headers['Cache-Control'] = 'no-store, no-cache'
        return resp
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/edit', methods=['GET', 'POST'])
@lms_content_manager_required
def content_edit(content_id):
    """Edit existing content"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        content = cur.execute(
            """
                SELECT
                    id,
                    topic_id,
                    master_topic_id,
                    content_mode,
                    content_title,
                    external_url,
                    file_path,
                    content_body,
                    hotspots_json,
                    display_order,
                    created_at,
                    updated_at
                FROM lms_topic_contents
                WHERE id = ?
            """,
            (content_id,)
        ).fetchone()
        
        if not content:
            flash('Content not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        is_master_topic = bool(content['master_topic_id'])

        if is_master_topic:
            master_meta = cur.execute(
                """
                    SELECT
                        mt.id AS topic_id,
                        mt.title AS topic_title,
                        mt.master_chapter_id AS chapter_id,
                        mc.title AS chapter_title
                    FROM lms_master_topics mt
                    JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                    WHERE mt.id = ?
                """,
                (content['master_topic_id'],)
            ).fetchone()
            if not master_meta:
                flash('Master topic not found for this content row.', 'danger')
                return redirect(url_for('lms_admin.list_master_chapters'))

            topic = {
                'id': master_meta['topic_id'],
                'topic_title': master_meta['topic_title']
            }
            chapter = {
                'id': master_meta['chapter_id'],
                'chapter_title': master_meta['chapter_title']
            }
            program = {
                'id': 0,
                'program_name': 'Master Library'
            }
        else:
            legacy_meta = cur.execute(
                """
                    SELECT
                        lt.id AS topic_id,
                        lt.topic_title,
                        lc.id AS chapter_id,
                        lc.chapter_title,
                        lp.id AS program_id,
                        lp.program_name
                    FROM lms_topics lt
                    JOIN lms_chapters lc ON lt.chapter_id = lc.id
                    JOIN lms_programs lp ON lc.program_id = lp.id
                    WHERE lt.id = ?
                """,
                (content['topic_id'],)
            ).fetchone()
            if not legacy_meta:
                flash('Topic not found for this content row.', 'danger')
                return redirect(url_for('lms_admin.list_programs'))

            topic = {
                'id': legacy_meta['topic_id'],
                'topic_title': legacy_meta['topic_title']
            }
            chapter = {
                'id': legacy_meta['chapter_id'],
                'chapter_title': legacy_meta['chapter_title']
            }
            program = {
                'id': legacy_meta['program_id'],
                'program_name': legacy_meta['program_name']
            }
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content_mode = request.form.get('content_mode', content['content_mode'])
            description = request.form.get('content_body', '').strip()
            display_order = request.form.get('display_order', str(content['display_order']))
            external_url = request.form.get('external_url', '').strip()
            file_path = content['file_path']  # keep existing by default

            # For rich_text, auto-use topic title if form didn't supply one
            if content_mode == 'rich_text' and not title:
                title = topic['topic_title']

            if not title:
                flash('Content title is required.', 'danger')
                return redirect(url_for('lms_admin.content_edit', content_id=content_id))

            if content_mode not in ['youtube', 'pdf', 'rich_text', 'download']:
                content_mode = 'youtube'

            try:
                display_order = int(display_order) if display_order else 1
            except ValueError:
                display_order = 1

            hotspots_json = content['hotspots_json'] or '' if content['hotspots_json'] else ''

            if content_mode == 'youtube':
                if not external_url:
                    flash('YouTube URL is required.', 'danger')
                    return redirect(url_for('lms_admin.content_edit', content_id=content_id))
                file_path = ''
                hotspots_json = ''

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
                hotspots_json = ''

            elif content_mode == 'rich_text':
                description = sanitize_rich_text(description)
                if not description.strip():
                    flash('Rich text content cannot be empty.', 'danger')
                    return redirect(url_for('lms_admin.content_edit', content_id=content_id))
                file_path = ''
                external_url = ''
                hotspots_json = ''

            now = datetime.now().isoformat(timespec='seconds')

            try:
                cur.execute("""
                    UPDATE lms_topic_contents
                    SET content_mode = ?, content_title = ?, external_url = ?,
                        file_path = ?, content_body = ?, hotspots_json = ?,
                        display_order = ?, updated_at = ?
                    WHERE id = ?
                """, (content_mode, title, external_url, file_path, description,
                      hotspots_json, display_order, now, content_id))

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
                if is_master_topic:
                    return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=content['master_topic_id']))
                return redirect(url_for('lms_admin.list_topic_contents', topic_id=content['topic_id']))

            except Exception as e:
                flash(f'Error updating content: {str(e)}', 'danger')
                return redirect(url_for('lms_admin.content_edit', content_id=content_id))
        
        return render_template(
            'lms_admin/lms_topic_content_form.html',
            program=program,
            chapter=chapter,
            topic=topic,
            content=content,
            next_order=None,
            is_master_topic=is_master_topic,
        )
    finally:
        conn.close()


@lms_admin_bp.route('/content/<int:content_id>/delete', methods=['POST'])
@admin_required
def delete_content(content_id):
    """Delete content from a topic"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get content and topic details
        cur.execute("""
            SELECT ltc.id, ltc.content_title, ltc.topic_id, ltc.master_topic_id
            FROM lms_topic_contents ltc
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
            description=f'Deleted content: {content["content_title"]}'
        )
        
        flash('Content deleted successfully.', 'success')
        if content['master_topic_id']:
            return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=content['master_topic_id']))
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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


# ─────────────────────────────────────────────────────────────────────────────
# LMS COURSE–PROGRAM MAPPING
# Maps a combo course (e.g. DFA) to multiple LMS programs so admin can
# bulk-assign batch/student access without creating a separate LMS program.
# ─────────────────────────────────────────────────────────────────────────────

@lms_admin_bp.route('/course-mapping', methods=['GET'])
@admin_required
def list_course_mappings():
    """List all course-to-program mappings grouped by course."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # All mappings with course and program names
        cur.execute("""
            SELECT
                m.id,
                m.course_id,
                m.program_id,
                m.display_order,
                m.created_at,
                c.course_name,
                lp.program_name
            FROM lms_course_program_map m
            JOIN courses c ON m.course_id = c.id
            JOIN lms_programs lp ON m.program_id = lp.id
            ORDER BY c.course_name, m.display_order, lp.program_name
        """)
        rows = cur.fetchall()

        # Group by course
        from collections import OrderedDict
        grouped = OrderedDict()
        for r in rows:
            key = r['course_id']
            if key not in grouped:
                grouped[key] = {'course_id': r['course_id'],
                                'course_name': r['course_name'],
                                'programs': []}
            grouped[key]['programs'].append({
                'map_id': r['id'],
                'program_id': r['program_id'],
                'program_name': r['program_name'],
                'display_order': r['display_order'],
                'created_at': r['created_at']
            })

        # All courses (for the Add Mapping form)
        cur.execute("""
            SELECT id, course_name FROM courses WHERE is_active = 1
            ORDER BY course_name
        """)
        all_courses = cur.fetchall()

        # All published LMS programs (for the Add Mapping form)
        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE is_active = 1
            ORDER BY program_name
        """)
        all_programs = cur.fetchall()

        return render_template(
            'lms_admin/lms_course_mapping.html',
            grouped=list(grouped.values()),
            all_courses=all_courses,
            all_programs=all_programs
        )
    finally:
        conn.close()


@lms_admin_bp.route('/course-mapping/add', methods=['POST'])
@admin_required
def add_course_mapping():
    """Add one or more program mappings for a course."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        course_id = request.form.get('course_id', '').strip()
        program_ids = request.form.getlist('program_ids')  # multiple checkboxes

        if not course_id:
            flash('Please select a course.', 'danger')
            return redirect(url_for('lms_admin.list_course_mappings'))

        if not program_ids:
            flash('Please select at least one program.', 'danger')
            return redirect(url_for('lms_admin.list_course_mappings'))

        try:
            course_id = int(course_id)
        except ValueError:
            flash('Invalid course.', 'danger')
            return redirect(url_for('lms_admin.list_course_mappings'))

        added = 0
        skipped = 0
        now = datetime.now().isoformat(timespec='seconds')

        for pid in program_ids:
            try:
                pid = int(pid)
            except ValueError:
                continue
            # Skip duplicates gracefully
            cur.execute("""
                SELECT id FROM lms_course_program_map
                WHERE course_id = ? AND program_id = ?
            """, (course_id, pid))
            if cur.fetchone():
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO lms_course_program_map
                    (course_id, program_id, created_by, created_at)
                VALUES (?, ?, ?, ?)
            """, (course_id, pid, session.get('user_id'), now))
            added += 1

        conn.commit()

        if added:
            cur.execute("SELECT course_name FROM courses WHERE id = ?", (course_id,))
            cname = cur.fetchone()['course_name']
            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_course_program_map',
                record_id=course_id,
                description=f'Added {added} program mapping(s) for course: {cname}'
            )
            flash(f'{added} mapping(s) added successfully.' +
                  (f' ({skipped} already existed, skipped.)' if skipped else ''),
                  'success')
        else:
            flash('All selected mappings already exist.', 'info')

        return redirect(url_for('lms_admin.list_course_mappings'))
    finally:
        conn.close()


@lms_admin_bp.route('/course-mapping/<int:map_id>/delete', methods=['POST'])
@admin_required
def delete_course_mapping(map_id):
    """Delete a single course-program mapping."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT m.id, m.course_id, m.program_id, c.course_name, lp.program_name
            FROM lms_course_program_map m
            JOIN courses c ON m.course_id = c.id
            JOIN lms_programs lp ON m.program_id = lp.id
            WHERE m.id = ?
        """, (map_id,))
        mapping = cur.fetchone()

        if not mapping:
            flash('Mapping not found.', 'danger')
            return redirect(url_for('lms_admin.list_course_mappings'))

        cur.execute("DELETE FROM lms_course_program_map WHERE id = ?", (map_id,))
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_course_program_map',
            record_id=map_id,
            description=f"Removed mapping: {mapping['course_name']} → {mapping['program_name']}"
        )
        flash('Mapping removed.', 'success')
        return redirect(url_for('lms_admin.list_course_mappings'))
    finally:
        conn.close()


@lms_admin_bp.route('/course-mapping/edit/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def manage_course_mapping(course_id):
    """Edit all program mappings for a single course at once."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Verify course exists
        cur.execute("SELECT id, course_name FROM courses WHERE id = ?", (course_id,))
        course = cur.fetchone()
        if not course:
            flash('Course not found.', 'danger')
            return redirect(url_for('lms_admin.list_course_mappings'))

        if request.method == 'POST':
            new_program_ids = {}  # {program_id: display_order}
            for pid in request.form.getlist('program_ids'):
                try:
                    pid_int = int(pid)
                    order_val = int(request.form.get(f'order_{pid}', 0) or 0)
                    new_program_ids[pid_int] = order_val
                except ValueError:
                    pass

            # Get currently mapped program IDs
            cur.execute("""
                SELECT program_id FROM lms_course_program_map WHERE course_id = ?
            """, (course_id,))
            existing_ids = {r['program_id'] for r in cur.fetchall()}

            to_add = set(new_program_ids.keys()) - existing_ids
            to_remove = existing_ids - set(new_program_ids.keys())
            to_update = existing_ids & set(new_program_ids.keys())

            now = datetime.now().isoformat(timespec='seconds')

            for pid in to_add:
                cur.execute("""
                    INSERT INTO lms_course_program_map
                        (course_id, program_id, display_order, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (course_id, pid, new_program_ids[pid], session.get('user_id'), now))

            for pid in to_update:
                cur.execute("""
                    UPDATE lms_course_program_map SET display_order = ?
                    WHERE course_id = ? AND program_id = ?
                """, (new_program_ids[pid], course_id, pid))

            for pid in to_remove:
                cur.execute("""
                    DELETE FROM lms_course_program_map WHERE course_id = ? AND program_id = ?
                """, (course_id, pid))

            conn.commit()

            changes = len(to_add) + len(to_remove) + len(to_update)
            if changes:
                log_activity(
                    user_id=session['user_id'],
                    branch_id=session.get('branch_id'),
                    action_type='update',
                    module_name='lms_course_program_map',
                    record_id=course_id,
                    description=f"Updated mappings for {course['course_name']}: +{len(to_add)} added, -{len(to_remove)} removed, {len(to_update)} reordered"
                )
                flash(f'Mappings updated for {course["course_name"]}.'
                      f' {len(to_add)} added, {len(to_remove)} removed, {len(to_update)} reordered.', 'success')
            else:
                flash('No changes made.', 'info')

            return redirect(url_for('lms_admin.list_course_mappings'))

        # GET — load all programs, mark which are already mapped
        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE is_active = 1 ORDER BY program_name
        """)
        all_programs = cur.fetchall()

        cur.execute("""
            SELECT program_id, display_order FROM lms_course_program_map
            WHERE course_id = ? ORDER BY display_order
        """, (course_id,))
        mapped_programs = {r['program_id']: r['display_order'] for r in cur.fetchall()}

        return render_template(
            'lms_admin/lms_course_mapping_edit.html',
            course=course,
            all_programs=all_programs,
            mapped_programs=mapped_programs
        )
    finally:
        conn.close()
@login_required
def api_batch_course(batch_id):
    """Return the course linked to a batch (looks up via invoices or enrollments)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Try to find course via invoices linked to this batch
        cur.execute("""
            SELECT c.id as course_id, c.course_name
            FROM invoices i
            JOIN courses c ON i.course_id = c.id
            WHERE i.batch_id = ?
            LIMIT 1
        """, (batch_id,))
        row = cur.fetchone()
        if row:
            return jsonify({'course_id': row['course_id'], 'course_name': row['course_name']})

        # Fallback: try enrollments → courses
        cur.execute("""
            SELECT c.id as course_id, c.course_name
            FROM student_batches sb
            JOIN enrollments e ON sb.student_id = e.student_id
            JOIN courses c ON e.course_id = c.id
            WHERE sb.batch_id = ?
            LIMIT 1
        """, (batch_id,))
        row = cur.fetchone()
        if row:
            return jsonify({'course_id': row['course_id'], 'course_name': row['course_name']})

        return jsonify({'course_id': None, 'course_name': None})
    finally:
        conn.close()


@lms_admin_bp.route('/course-mapping/api/programs-for-course/<int:course_id>', methods=['GET'])
@login_required
def api_programs_for_course(course_id):
    """Return JSON list of LMS programs mapped to a given course (used by batch assign form)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT lp.id, lp.program_name
            FROM lms_course_program_map m
            JOIN lms_programs lp ON m.program_id = lp.id
            WHERE m.course_id = ? AND lp.is_active = 1
            ORDER BY lp.program_name
        """, (course_id,))
        rows = cur.fetchall()
        return jsonify({'programs': [dict(r) for r in rows]})
    finally:
        conn.close()


@lms_admin_bp.route('/batch-program/bulk-assign', methods=['GET', 'POST'])
@admin_required
def bulk_assign_batch_programs():
    """
    Bulk-assign all mapped programs for a batch's course in one go.
    Perfect for combo courses like DFA (CCOM + Excel + Tally).
    """
    conn = get_conn()
    try:
        cur = conn.cursor()

        if request.method == 'POST':
            batch_id = request.form.get('batch_id', '').strip()
            program_ids = request.form.getlist('program_ids')
            access_start_date = request.form.get('access_start_date', '').strip()
            access_end_date = request.form.get('access_end_date', '').strip()
            is_active = request.form.get('is_active') == 'on'

            if not batch_id or not program_ids or not access_start_date:
                flash('Batch, at least one program, and start date are required.', 'danger')
                return redirect(url_for('lms_admin.bulk_assign_batch_programs'))

            try:
                batch_id = int(batch_id)
            except ValueError:
                flash('Invalid batch.', 'danger')
                return redirect(url_for('lms_admin.bulk_assign_batch_programs'))

            # Validate dates
            try:
                start_dt = datetime.strptime(access_start_date, '%Y-%m-%d')
                if access_end_date:
                    end_dt = datetime.strptime(access_end_date, '%Y-%m-%d')
                    if end_dt < start_dt:
                        flash('End date cannot be before start date.', 'danger')
                        return redirect(url_for('lms_admin.bulk_assign_batch_programs'))
            except ValueError:
                flash('Invalid date format.', 'danger')
                return redirect(url_for('lms_admin.bulk_assign_batch_programs'))

            added = 0
            skipped = 0
            now_dt = datetime.now().isoformat(timespec='seconds')

            for pid in program_ids:
                try:
                    pid = int(pid)
                except ValueError:
                    continue

                # Check for duplicate
                cur.execute("""
                    SELECT id FROM lms_batch_program_access
                    WHERE batch_id = ? AND program_id = ?
                """, (batch_id, pid))
                if cur.fetchone():
                    skipped += 1
                    continue

                cur.execute("""
                    INSERT INTO lms_batch_program_access
                        (batch_id, program_id, access_start_date, access_end_date, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, pid,
                    access_start_date,
                    access_end_date if access_end_date else None,
                    1 if is_active else 0,
                    now_dt, now_dt
                ))
                added += 1

            conn.commit()

            cur.execute("SELECT batch_name FROM batches WHERE id = ?", (batch_id,))
            brow = cur.fetchone()
            bname = brow['batch_name'] if brow else str(batch_id)

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_batch_program_access',
                record_id=batch_id,
                description=f'Bulk-assigned {added} program(s) to batch "{bname}"'
            )

            if added:
                flash(f'{added} program(s) assigned to batch "{bname}".' +
                      (f' ({skipped} already existed, skipped.)' if skipped else ''),
                      'success')
            else:
                flash('All selected programs were already assigned to this batch.', 'info')

            return redirect(url_for('lms_admin.list_batch_programs'))

        # GET – build form data
        cur.execute("""
            SELECT id, batch_name FROM batches WHERE status = 'active'
            ORDER BY batch_name
        """)
        batches = cur.fetchall()

        cur.execute("""
            SELECT id, program_name FROM lms_programs WHERE is_active = 1
            ORDER BY program_name
        """)
        all_programs = cur.fetchall()

        # Pass batch→course info so JS can pre-tick mapped programs
        # build: {batch_id: course_id}
        cur.execute("""
            SELECT sb.batch_id, c.id as course_id, c.course_name
            FROM (
                SELECT DISTINCT batch_id,
                    (SELECT course_id FROM invoices WHERE batch_id = batches.id LIMIT 1) as course_id
                FROM batches WHERE status = 'active'
            ) sb
            JOIN courses c ON sb.course_id = c.id
        """)
        # Simpler: get course_id directly from batches table if it exists,
        # otherwise from enrollments/invoices
        # Let's get it via student_batches → enrollments → courses
        cur.execute("""
            SELECT b.id as batch_id, b.batch_name,
                   c.id as course_id, c.course_name
            FROM batches b
            LEFT JOIN (
                SELECT sb.batch_id, e.course_id
                FROM student_batches sb
                JOIN enrollments e ON sb.student_id = e.student_id
                GROUP BY sb.batch_id
                LIMIT 1
            ) ec ON b.id = ec.batch_id
            LEFT JOIN courses c ON ec.course_id = c.id
            WHERE b.status = 'active'
            ORDER BY b.batch_name
        """)
        # Fallback – just use batches; course lookup happens via AJAX
        cur.execute("SELECT id, batch_name FROM batches WHERE status='active' ORDER BY batch_name")
        batches = cur.fetchall()

        today = datetime.now().strftime('%Y-%m-%d')

        return render_template(
            'lms_admin/lms_bulk_assign.html',
            batches=batches,
            all_programs=all_programs,
            today=today
        )
    finally:
        conn.close()
