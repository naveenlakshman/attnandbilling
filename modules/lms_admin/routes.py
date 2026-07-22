from flask import render_template, request, jsonify, send_from_directory
from . import lms_admin_bp
from db import get_conn, log_activity
from flask import session, redirect, url_for, flash, abort
from extensions import csrf
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import re
import os
import json
import sqlite3
import io
import mimetypes
from urllib.parse import quote
import bleach
from bleach.css_sanitizer import CSSSanitizer
from werkzeug.utils import secure_filename
from config import Config, DB_PATH
from modules.core.utils import login_required, admin_required, lms_content_manager_required
from services.storage import get_storage_service
import logging

logger = logging.getLogger("app.lms_admin")

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
#
# NOTE: The following CSS properties support TinyMCE paragraph formatting features:
#   - text-align: paragraph alignment (left, center, right, justify)
#   - line-height: line spacing (1, 1.15, 1.5, 1.75, 2, 2.5, 3)
#   - margin-top/bottom/left: paragraph spacing and indentation (tab stops)
#   - padding: spacing inside bordered/shaded paragraphs
#   - border/border-left: paragraph borders and accent lines
#   - background-color: paragraph shading (Light Shading, Light Blue, etc.)
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
_SUBMISSION_PREVIEW_TOKEN_SALT = 'lms-submission-preview'
_SUBMISSION_PREVIEW_TOKEN_MAX_AGE = 10 * 60

_SUBMISSION_MIME_TYPES = {
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'pdf': 'application/pdf',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
}


def _submission_mimetype(filename):
    ext = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    return _SUBMISSION_MIME_TYPES.get(ext) or mimetypes.guess_type(filename or '')[0] or 'application/octet-stream'


def _submission_storage_candidates(file_path):
    """Return canonical and legacy object paths for a submitted assignment file."""
    normalized = (file_path or '').replace('\\', '/').lstrip('/')
    if normalized and '/' not in normalized:
        return [f'documents/{normalized}', normalized]
    return [normalized] if normalized else []


def _current_lms_actor(conn):
    """Return the active admin/staff database identity for this session."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return conn.execute(
        """
        SELECT id, role, branch_id, can_view_all_branches
        FROM users
        WHERE id = ?
          AND is_active = 1
          AND role IN ('admin', 'staff')
        """,
        (user_id,),
    ).fetchone()


def _can_access_submission(conn, submission_id):
    """Authorize one submission without trusting URL/filter scope.

    Global administrators can access all submissions. Branch-scoped
    administrators are limited to students/batches in their branch. Staff are
    limited to students in their own active batches.
    """
    actor = _current_lms_actor(conn)
    if not actor:
        return False
    if actor['role'] == 'admin' and int(actor['can_view_all_branches'] or 0) == 1:
        return bool(conn.execute(
            "SELECT 1 FROM lms_assignment_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone())
    if actor['role'] == 'admin':
        return bool(conn.execute(
            """
            SELECT 1
            FROM lms_assignment_submissions s
            JOIN students st ON st.id = s.student_id
            WHERE s.id = ?
              AND (
                    st.branch_id = ?
                    OR EXISTS (
                        SELECT 1
                        FROM student_batches sb
                        JOIN batches b ON b.id = sb.batch_id
                        WHERE sb.student_id = s.student_id
                          AND sb.status = 'active'
                          AND LOWER(COALESCE(b.status, '')) = 'active'
                          AND b.branch_id = ?
                    )
              )
            """,
            (submission_id, actor['branch_id'], actor['branch_id']),
        ).fetchone())
    return bool(conn.execute(
        """
        SELECT 1
        FROM lms_assignment_submissions s
        WHERE s.id = ?
          AND EXISTS (
              SELECT 1
              FROM student_batches sb
              JOIN batches b ON b.id = sb.batch_id
              WHERE sb.student_id = s.student_id
                AND sb.status = 'active'
                AND LOWER(COALESCE(b.status, '')) = 'active'
                AND b.trainer_id = ?
          )
        """,
        (submission_id, actor['id']),
    ).fetchone())


def _require_submission_access(conn, submission_id):
    if not _can_access_submission(conn, submission_id):
        abort(403)


def _submission_preview_serializer():
    secret = (Config.SECRET_KEY or '').strip()
    if not secret:
        secret = 'fallback-preview-secret'
    return URLSafeTimedSerializer(secret)


def _make_submission_preview_token(submission_id):
    return _submission_preview_serializer().dumps({'sid': int(submission_id)}, salt=_SUBMISSION_PREVIEW_TOKEN_SALT)


def _read_submission_preview_token(token):
    if not token:
        return None
    try:
        data = _submission_preview_serializer().loads(
            token,
            salt=_SUBMISSION_PREVIEW_TOKEN_SALT,
            max_age=_SUBMISSION_PREVIEW_TOKEN_MAX_AGE,
        )
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    sid = data.get('sid') if isinstance(data, dict) else None
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return None
    return sid if sid > 0 else None


def sanitize_rich_text(html):
    """Strip script tags and unsafe JS from editor HTML while preserving safe CSS."""
    if not html:
        return ""
    if isinstance(html, str) and html.startswith("base64:"):
        import base64
        try:
            html = base64.b64decode(html[7:]).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to decode base64 rich text: {e}")

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


def _renumber_master_topics(cur, master_chapter_id, ordered_topic_ids=None):
    """Ensure master topic_order is sequential (1..n) within one master chapter."""
    rows = cur.execute(
        """
            SELECT id
            FROM lms_master_topics
            WHERE master_chapter_id = ?
            ORDER BY topic_order ASC, id ASC
        """,
        (master_chapter_id,)
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
                UPDATE lms_master_topics
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
                    course_id, program_name, program_reference_name, slug, description, thumbnail_path,
                    is_published, is_active, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                _MASTER_BRIDGE_PROGRAM_NAME,
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


def _master_chapter_id_for_legacy_chapter(cur, chapter_id):
    """Return the master chapter mapped from a legacy chapter, when migration bridge rows exist."""
    row = cur.execute(
        """
            SELECT mt.master_chapter_id, COUNT(*) AS mapped_topics
            FROM lms_master_topic_bridge b
            JOIN lms_topics lt ON lt.id = b.legacy_topic_id
            JOIN lms_master_topics mt ON mt.id = b.master_topic_id
            WHERE lt.chapter_id = ?
            GROUP BY mt.master_chapter_id
            ORDER BY mapped_topics DESC, mt.master_chapter_id ASC
            LIMIT 1
        """,
        (chapter_id,)
    ).fetchone()
    return row['master_chapter_id'] if row else None


def _master_topic_id_for_legacy_topic(cur, topic_id):
    row = cur.execute(
        "SELECT master_topic_id FROM lms_master_topic_bridge WHERE legacy_topic_id = ?",
        (topic_id,)
    ).fetchone()
    return row['master_topic_id'] if row else None


def _legacy_chapter_program_id(cur, chapter_id):
    row = cur.execute(
        "SELECT program_id FROM lms_chapters WHERE id = ?",
        (chapter_id,)
    ).fetchone()
    return row['program_id'] if row else None


def _legacy_topic_program_id(cur, topic_id):
    row = cur.execute(
        """
            SELECT lc.program_id
            FROM lms_topics lt
            JOIN lms_chapters lc ON lc.id = lt.chapter_id
            WHERE lt.id = ?
        """,
        (topic_id,)
    ).fetchone()
    return row['program_id'] if row else None


def _redirect_legacy_cleanup(program_id=None):
    flash(
        'Legacy program chapters are no longer edited directly. Use the Master Library flow, or migrate old content from Legacy Migration.',
        'info'
    )
    if session.get('role') == 'admin':
        return redirect(url_for('lms_admin.phase6_rollout_view'))
    if program_id:
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    return redirect(url_for('lms_admin.list_programs'))


def _redirect_legacy_chapter_to_master(cur, chapter_id, endpoint='topics'):
    master_chapter_id = _master_chapter_id_for_legacy_chapter(cur, chapter_id)
    if master_chapter_id:
        flash('This legacy chapter is now managed in the Master Library.', 'info')
        if endpoint == 'edit':
            return redirect(url_for('lms_admin.master_chapter_edit', master_chapter_id=master_chapter_id))
        if endpoint == 'new_topic':
            return redirect(url_for('lms_admin.master_topic_new', master_chapter_id=master_chapter_id))
        return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))
    return _redirect_legacy_cleanup(_legacy_chapter_program_id(cur, chapter_id))


def _redirect_legacy_topic_to_master(cur, topic_id, endpoint='contents'):
    master_topic_id = _master_topic_id_for_legacy_topic(cur, topic_id)
    if master_topic_id:
        flash('This legacy topic is now managed in the Master Library.', 'info')
        if endpoint == 'edit':
            return redirect(url_for('lms_admin.master_topic_edit', master_topic_id=master_topic_id))
        if endpoint == 'new_content':
            redirect_url = url_for('lms_admin.master_content_new', master_topic_id=master_topic_id)
            preset = request.args.get('type', '')
            if preset:
                redirect_url += f'?type={preset}'
            return redirect(redirect_url)
        return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=master_topic_id))
    return _redirect_legacy_cleanup(_legacy_topic_program_id(cur, topic_id))


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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
    unique_filename = timestamp + filename
    
    if content_type == 'interactive_image':
        dest_path = f"course_images/{unique_filename}"
    else:
        dest_path = f"documents/{unique_filename}"

    try:
        storage_service = get_storage_service()
        storage_service.upload_file(file_obj, dest_path, content_type=file_obj.content_type)
        return True, dest_path
    except Exception as e:
        logger.error(f"Error saving LMS file to storage: {e}", exc_info=True)
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
    session['student_login_at'] = int(datetime.utcnow().timestamp())
    session['demo_mode']    = True
    log_activity(session.get('user_id'), session.get('branch_id'), 'launch_demo', 'lms', None, f"{session.get('role','user').title()} launched demo student view")
    flash('Demo mode active — you are viewing the student portal in read-only mode.', 'info')
    return redirect(url_for('students.dashboard'))


@lms_admin_bp.route('/demo/exit')
def exit_demo():
    """End demo session and return to LMS admin."""
    for key in ('student_id', 'student_name', 'student_code', 'student_login_at', 'demo_mode'):
        session.pop(key, None)
    return redirect(url_for('lms_admin.dashboard'))


@lms_admin_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    """LMS content workspace for administrators and staff."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Get counts for dashboard metrics
        cur.execute("SELECT COUNT(*) as count FROM lms_programs WHERE is_deleted = 0 AND slug != ?", (_MASTER_BRIDGE_PROGRAM_SLUG,))
        total_programs = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM lms_master_chapters WHERE status = 'active'")
        total_chapters = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM lms_master_topics WHERE status = 'active'")
        total_topics = cur.fetchone()['count']

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM lms_master_topics mt
            WHERE mt.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM lms_topic_contents ltc
                  WHERE ltc.master_topic_id = mt.id
                    AND ltc.content_mode IN ('pdf', 'rich_text', 'interactive_image')
              )
        """)
        topics_missing_lesson = cur.fetchone()['count']

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM lms_master_chapters mc
            WHERE mc.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM lms_program_chapters pc
                  WHERE pc.master_chapter_id = mc.id
              )
        """)
        unlinked_chapters = cur.fetchone()['count']

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM lms_programs
            WHERE is_deleted = 0 AND slug != ? AND is_published = 0
        """, (_MASTER_BRIDGE_PROGRAM_SLUG,))
        draft_programs = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM lms_mock_tests")
        total_tests = cur.fetchone()['count']

        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_final_exam_applications
            WHERE status = 'PENDING'
        """)
        pending_final_exam_applications = cur.fetchone()['count']
        
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
            'topics_missing_lesson': topics_missing_lesson,
            'unlinked_chapters': unlinked_chapters,
            'draft_programs': draft_programs,
            'total_tests': total_tests,
            'pending_final_exam_applications': pending_final_exam_applications,
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

        _program_select = """
            SELECT 
                lp.id,
                lp.program_name,
                lp.program_reference_name,
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
        """

        # Active programs
        cur.execute(_program_select + """
            WHERE lp.slug != ? AND lp.is_deleted = 0
            ORDER BY lp.created_at DESC
        """, (_MASTER_BRIDGE_PROGRAM_SLUG,))
        programs = cur.fetchall()

        # Deleted programs (admin only)
        deleted_programs = []
        if session.get('role') == 'admin':
            cur.execute(_program_select + """
                WHERE lp.slug != ? AND lp.is_deleted = 1
                ORDER BY lp.updated_at DESC
            """, (_MASTER_BRIDGE_PROGRAM_SLUG,))
            deleted_programs = cur.fetchall()

        return render_template('lms_programs.html', programs=programs, deleted_programs=deleted_programs)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/restore', methods=['POST'])
@admin_required
def restore_program(program_id):
    """Restore a soft-deleted LMS program."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, program_name FROM lms_programs
            WHERE id = ? AND is_deleted = 1
        """, (program_id,))
        program = cur.fetchone()

        if not program:
            flash('Program not found or not deleted.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        now = datetime.now().isoformat(timespec='seconds')
        cur.execute("""
            UPDATE lms_programs SET is_deleted = 0, updated_at = ? WHERE id = ?
        """, (now, program_id))
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='restore',
            module_name='lms_programs',
            record_id=program_id,
            description=f'Restored deleted program: {program["program_name"]}'
        )

        flash(f'Program "{program["program_name"]}" has been restored.', 'success')
        return redirect(url_for('lms_admin.list_programs'))
    except Exception as e:
        flash(f'Error restoring program: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.list_programs'))
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
                    COUNT(DISTINCT mt.id) AS topic_count,
                    COUNT(DISTINCT pc.program_id) AS linked_program_count,
                    GROUP_CONCAT(DISTINCT pc.program_id) AS linked_program_ids
                FROM lms_master_chapters mc
                LEFT JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
                LEFT JOIN lms_program_chapters pc ON pc.master_chapter_id = mc.id
                GROUP BY mc.id
                ORDER BY mc.created_at DESC
            """
        )
        chapters = cur.fetchall()
        cur.execute(
            """
                SELECT id, program_name
                FROM lms_programs
                WHERE is_deleted = 0
                  AND is_active = 1
                  AND slug != ?
                ORDER BY program_name ASC
            """,
            (_MASTER_BRIDGE_PROGRAM_SLUG,)
        )
        programs = cur.fetchall()
        return render_template('master_chapters.html', chapters=chapters, programs=programs)
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
                    (
                        SELECT ltc_lesson.id
                        FROM lms_topic_contents ltc_lesson
                        WHERE ltc_lesson.master_topic_id = mt.id
                          AND ltc_lesson.content_mode IN ('pdf', 'rich_text', 'interactive_image')
                        ORDER BY ltc_lesson.display_order ASC, ltc_lesson.id ASC
                        LIMIT 1
                    ) AS lesson_content_id,
                    MAX(CASE WHEN ltc.content_mode = 'youtube' THEN 1 ELSE 0 END) AS has_video_content,
                    MAX(CASE WHEN ltc.content_mode IN ('pdf', 'rich_text', 'interactive_image') THEN 1 ELSE 0 END) AS has_lesson_content,
                    (
                        SELECT COUNT(*)
                        FROM lms_assignments la
                        WHERE la.master_topic_id = mt.id
                    ) AS assignment_count,
                    COUNT(ltc.id) AS content_count
                FROM lms_master_topics mt
                LEFT JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                WHERE mt.master_chapter_id = ?
                GROUP BY mt.id
                ORDER BY mt.topic_order ASC, mt.id ASC
            """,
            (master_chapter_id,)
        ).fetchall()

        total_topics = len(topics)

        return render_template('master_topics.html', chapter=chapter, topics=topics, total_topics=total_topics)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter/<int:chapter_id>/topics', methods=['GET'])
@login_required
def list_program_chapter_topics(program_id, chapter_id):
    """List shared master topics for a chapter while staying in program context."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        link = cur.execute(
            """
                SELECT
                    pc.id AS link_id,
                    pc.program_id,
                    pc.master_chapter_id,
                    pc.chapter_order,
                    pc.custom_title,
                    pc.is_visible,
                    lp.program_name,
                    mc.title,
                    mc.description,
                    mc.status,
                    mc.created_at,
                    mc.updated_at
                FROM lms_program_chapters pc
                JOIN lms_programs lp ON lp.id = pc.program_id
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE pc.program_id = ?
                  AND pc.master_chapter_id = ?
            """,
            (program_id, chapter_id)
        ).fetchone()

        if not link:
            flash('Program chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

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
                    (
                        SELECT ltc_lesson.id
                        FROM lms_topic_contents ltc_lesson
                        WHERE ltc_lesson.master_topic_id = mt.id
                          AND ltc_lesson.content_mode IN ('pdf', 'rich_text', 'interactive_image')
                        ORDER BY ltc_lesson.display_order ASC, ltc_lesson.id ASC
                        LIMIT 1
                    ) AS lesson_content_id,
                    MAX(CASE WHEN ltc.content_mode = 'youtube' THEN 1 ELSE 0 END) AS has_video_content,
                    MAX(CASE WHEN ltc.content_mode IN ('pdf', 'rich_text', 'interactive_image') THEN 1 ELSE 0 END) AS has_lesson_content,
                    (
                        SELECT COUNT(*)
                        FROM lms_assignments la
                        WHERE la.master_topic_id = mt.id
                    ) AS assignment_count,
                    COUNT(ltc.id) AS content_count
                FROM lms_master_topics mt
                LEFT JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                WHERE mt.master_chapter_id = ?
                GROUP BY mt.id
                ORDER BY mt.topic_order ASC, mt.id ASC
            """,
            (chapter_id,)
        ).fetchall()

        chapter = {
            'id': link['master_chapter_id'],
            'title': link['custom_title'] or link['title'],
            'master_title': link['title'],
            'description': link['description'],
            'status': link['status'],
            'created_at': link['created_at'],
            'updated_at': link['updated_at'],
            'chapter_order': link['chapter_order'],
            'is_visible': link['is_visible'],
        }
        program = {
            'id': link['program_id'],
            'program_name': link['program_name'],
        }

        return render_template(
            'master_topics.html',
            chapter=chapter,
            program=program,
            topics=topics,
            total_topics=len(topics),
            is_program_context=True,
        )
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/master-topic/<int:master_topic_id>/preview', methods=['GET'])
@login_required
def preview_program_master_topic(program_id, master_topic_id):
    """Open a linked master topic in the student portal using read-only demo mode."""
    conn = get_conn()
    try:
        topic = conn.execute(
            """
                SELECT mt.id, mt.title
                FROM lms_master_topics mt
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                JOIN lms_program_chapters pc
                    ON pc.master_chapter_id = mt.master_chapter_id
                   AND pc.program_id = ?
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
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    finally:
        conn.close()

    session['student_id'] = 0
    session['student_name'] = 'Demo Student'
    session['student_code'] = 'DEMO'
    session['student_login_at'] = int(datetime.utcnow().timestamp())
    session['demo_mode'] = True
    log_activity(
        session.get('user_id'),
        session.get('branch_id'),
        'preview',
        'lms_master_topics',
        master_topic_id,
        f"{session.get('role', 'user').title()} previewed master topic: {topic['title']}"
    )
    flash('Demo mode active - previewing this topic as a student.', 'info')
    return redirect(url_for('students.master_topic_view', program_id=program_id, master_topic_id=master_topic_id))


@lms_admin_bp.route('/master/chapter/<int:master_chapter_id>/topics/reorder', methods=['POST'])
@lms_content_manager_required
def reorder_master_topics(master_chapter_id):
    """Reorder master topics and normalize topic_order sequentially."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        chapter = cur.execute(
            """
                SELECT id, title
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
                SELECT id, topic_order
                FROM lms_master_topics
                WHERE master_chapter_id = ?
                ORDER BY topic_order ASC, id ASC
            """,
            (master_chapter_id,)
        ).fetchall()

        if not topics:
            flash('No topics found to reorder.', 'warning')
            return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

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
                return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

        if not isinstance(requested_entries, list) or len(requested_entries) != total_topics:
            flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
            return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

        valid_topic_ids = {row['id'] for row in topics}
        payload_topic_ids = []
        payload_orders = []

        for entry in requested_entries:
            if not isinstance(entry, dict):
                flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
                return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

            topic_id = _strict_positive_int(entry.get('id'))
            requested_order = _strict_positive_int(entry.get('order'))

            if topic_id is None or requested_order is None:
                flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
                return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

            payload_topic_ids.append(topic_id)
            payload_orders.append(requested_order)

        if set(payload_topic_ids) != valid_topic_ids or len(payload_topic_ids) != len(set(payload_topic_ids)):
            flash('Invalid topic selection for this chapter.', 'danger')
            return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

        valid_orders = set(range(1, total_topics + 1))
        if set(payload_orders) != valid_orders or len(payload_orders) != len(set(payload_orders)):
            flash('Each topic must have a unique order number from 1 to total topics.', 'danger')
            return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))

        ranked = []
        for idx, entry in enumerate(requested_entries):
            ranked.append((int(entry['order']), idx, int(entry['id'])))

        ordered_topic_ids = [topic_id for _, _, topic_id in sorted(ranked, key=lambda x: (x[0], x[1]))]
        _renumber_master_topics(cur, master_chapter_id, ordered_topic_ids)

        conn.commit()
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='update',
            module_name='lms_master_topics',
            record_id=master_chapter_id,
            description=f'Reordered master topics in chapter {chapter["title"]}'
        )

        flash('Master topic order updated successfully.', 'success')
        return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=master_chapter_id))
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
        assignment_count = cur.execute(
            """
                SELECT COUNT(*) AS count
                FROM lms_assignments
                WHERE master_topic_id = ?
            """,
            (master_topic_id,)
        ).fetchone()['count']
        preview_program = cur.execute(
            """
                SELECT lp.id, lp.program_name
                FROM lms_program_chapters pc
                JOIN lms_programs lp ON lp.id = pc.program_id
                WHERE pc.master_chapter_id = ?
                  AND pc.is_visible = 1
                  AND lp.is_active = 1
                  AND lp.is_deleted = 0
                  AND lp.slug != ?
                ORDER BY lp.program_name, lp.id
                LIMIT 1
            """,
            (topic['master_chapter_id'], _MASTER_BRIDGE_PROGRAM_SLUG)
        ).fetchone()
        # Topic-to-topic navigation within the same master chapter.
        prev_topic = cur.execute(
            """
                SELECT id, title
                FROM lms_master_topics
                WHERE master_chapter_id = ?
                  AND (
                    topic_order < ?
                    OR (topic_order = ? AND id < ?)
                  )
                ORDER BY topic_order DESC, id DESC
                LIMIT 1
            """,
            (
                topic['master_chapter_id'],
                topic['topic_order'],
                topic['topic_order'],
                topic['id'],
            )
        ).fetchone()

        next_topic = cur.execute(
            """
                SELECT id, title
                FROM lms_master_topics
                WHERE master_chapter_id = ?
                  AND (
                    topic_order > ?
                    OR (topic_order = ? AND id > ?)
                  )
                ORDER BY topic_order ASC, id ASC
                LIMIT 1
            """,
            (
                topic['master_chapter_id'],
                topic['topic_order'],
                topic['topic_order'],
                topic['id'],
            )
        ).fetchone()

        data = {
            'chapter': {
                'id': topic['master_chapter_id'],
                'title': topic['chapter_title'],
            },
            'topic': topic,
            'video_content': video_content,
            'lesson_content': lesson_content,
            'assignment_count': assignment_count,
            'preview_program': preview_program,
            'prev_topic': prev_topic,
            'next_topic': next_topic,
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
            elif content_mode == 'pdf':
                file_field = 'pdf_file'
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

            current_ids = [
                row['id'] for row in cur.execute(
                    """
                        SELECT id
                        FROM lms_master_topics
                        WHERE master_chapter_id = ?
                        ORDER BY topic_order ASC, id ASC
                    """,
                    (master_chapter_id,)
                ).fetchall()
            ]
            if topic_id in current_ids:
                current_ids.remove(topic_id)
            insert_index = max(0, min(topic_order - 1, len(current_ids)))
            current_ids.insert(insert_index, topic_id)
            _renumber_master_topics(cur, master_chapter_id, current_ids)

            conn.commit()

            log_activity(
                user_id=session['user_id'],
                branch_id=session.get('branch_id'),
                action_type='create',
                module_name='lms_master_topics',
                record_id=topic_id,
                description=f'Created master topic: {title} in chapter {chapter["title"]}'
            )

            flash('Master topic created. Add content to complete the topic.', 'success')
            return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=topic_id))

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

            current_ids = [
                row['id'] for row in cur.execute(
                    """
                        SELECT id
                        FROM lms_master_topics
                        WHERE master_chapter_id = ?
                        ORDER BY topic_order ASC, id ASC
                    """,
                    (topic['master_chapter_id'],)
                ).fetchall()
            ]
            if master_topic_id in current_ids:
                current_ids.remove(master_topic_id)
            insert_index = max(0, min(topic_order - 1, len(current_ids)))
            current_ids.insert(insert_index, master_topic_id)
            _renumber_master_topics(cur, topic['master_chapter_id'], current_ids)

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


@lms_admin_bp.route('/master/topic/<int:master_topic_id>/clone', methods=['POST'])
@admin_required
def master_topic_clone(master_topic_id):
    """Clone a master topic and all its contents within the same chapter."""
    from modules.lms_admin.branch_helpers import _clone_master_topic
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # 1. Fetch original master topic details
        cur.execute("SELECT * FROM lms_master_topics WHERE id = ?", (master_topic_id,))
        src_topic = cur.fetchone()
        if not src_topic:
            flash('Master topic not found.', 'danger')
            return redirect(request.referrer or url_for('lms_admin.list_programs'))

        master_chapter_id = src_topic['master_chapter_id']

        # 2. Get all existing topic IDs in order
        existing_rows = cur.execute(
            "SELECT id FROM lms_master_topics WHERE master_chapter_id = ? ORDER BY topic_order ASC, id ASC",
            (master_chapter_id,)
        ).fetchall()
        existing_ids = [r['id'] for r in existing_rows]

        # 3. Call helper to clone topic details, content, attachments, assignments
        new_master_topic_id = _clone_master_topic(cur, master_topic_id, master_chapter_id)
        if not new_master_topic_id:
            flash('Error cloning topic.', 'danger')
            return redirect(request.referrer or url_for('lms_admin.list_programs'))

        # Insert new topic ID immediately after the cloned one
        if master_topic_id in existing_ids:
            idx = existing_ids.index(master_topic_id)
            existing_ids.insert(idx + 1, new_master_topic_id)
        else:
            existing_ids.append(new_master_topic_id)

        # Run renumber
        _renumber_master_topics(cur, master_chapter_id, existing_ids)
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='create',
            module_name='lms_master_topics',
            record_id=new_master_topic_id,
            description=f"Cloned master topic from '{src_topic['title']}' to new topic ID {new_master_topic_id}"
        )
        flash(f"Topic '{src_topic['title']}' cloned successfully.", 'success')
        return redirect(request.referrer or url_for('lms_admin.list_master_topic_contents', master_topic_id=new_master_topic_id))
    except Exception as e:
        flash(f'Error cloning topic: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('lms_admin.list_programs'))
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
            program_reference_name = request.form.get('program_reference_name', '').strip()
            course_id = request.form.get('course_id', '')
            slug = request.form.get('slug', '').strip()
            description = request.form.get('description', '').strip()
            thumbnail_path = request.form.get('thumbnail_path', '').strip()
            is_published = request.form.get('is_published', 0)
            
            # Validate program name
            if not program_name:
                flash('Program name is required.', 'danger')
                return redirect(url_for('lms_admin.program_new'))
            if not program_reference_name:
                program_reference_name = program_name
            
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
                    program_reference_name,
                    slug,
                    description,
                    thumbnail_path,
                    is_published,
                    is_active,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                course_id,
                program_name,
                program_reference_name,
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
            program_reference_name = request.form.get('program_reference_name', '').strip()
            course_id = request.form.get('course_id', '')
            slug = request.form.get('slug', '').strip()
            description = request.form.get('description', '').strip()
            thumbnail_path = request.form.get('thumbnail_path', '').strip()
            is_published = request.form.get('is_published', 0)
            
            # Validate program name
            if not program_name:
                flash('Program name is required.', 'danger')
                return redirect(url_for('lms_admin.program_edit', program_id=program_id))
            if not program_reference_name:
                program_reference_name = program_name
            
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
                    program_reference_name = ?,
                    slug = ?,
                    description = ?,
                    thumbnail_path = ?,
                    is_published = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                course_id,
                program_name,
                program_reference_name,
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


@lms_admin_bp.route('/program/<int:program_id>/clone', methods=['POST'])
@admin_required
def program_clone(program_id):
    """Clone an existing LMS program and duplicate its chapter links"""
    import uuid
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # 1. Fetch source program
        cur.execute("SELECT * FROM lms_programs WHERE id = ?", (program_id,))
        src_program = cur.fetchone()
        if not src_program:
            flash('Source program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
            
        # Generate cloned name and slug
        cloned_name = f"{src_program['program_name']} (Copy)"
        cloned_reference_name = src_program['program_reference_name'] or src_program['program_name']
        cloned_slug = f"{src_program['slug']}-copy"
        
        # Check slug uniqueness and append random parts if necessary
        cur.execute("SELECT 1 FROM lms_programs WHERE slug = ?", (cloned_slug,))
        if cur.fetchone():
            cloned_slug = f"{cloned_slug}-{uuid.uuid4().hex[:6]}"
            
        now = datetime.now().isoformat(timespec='seconds')
        
        # 2. Insert new program
        cur.execute("""
            INSERT INTO lms_programs (
                course_id, program_name, program_reference_name, slug, description, thumbnail_path, 
                is_published, is_active, is_deleted, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            src_program['course_id'],
            cloned_name,
            cloned_reference_name,
            cloned_slug,
            src_program['description'],
            src_program['thumbnail_path'],
            0, # default to unpublished
            src_program['is_active'],
            0, # is_deleted = 0
            session['user_id'],
            now,
            now
        ))
        
        new_program_id = cur.lastrowid
        
        # 3. Duplicate and automatically branch links in lms_program_chapters
        cur.execute("""
            SELECT * FROM lms_program_chapters WHERE program_id = ?
        """, (program_id,))
        chapter_links = cur.fetchall()
        
        from modules.lms_admin.branch_helpers import _clone_master_chapter
        for link in chapter_links:
            # Automatically clone/branch the master chapter so the cloned program starts fully decoupled
            new_master_chapter_id = _clone_master_chapter(cur, link['master_chapter_id'])
            cur.execute("""
                INSERT INTO lms_program_chapters (
                    program_id, master_chapter_id, chapter_order, custom_title, is_visible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                new_program_id,
                new_master_chapter_id,
                link['chapter_order'],
                link['custom_title'],
                link['is_visible'],
                now
            ))
            
        conn.commit()
        
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='create',
            module_name='lms_programs',
            record_id=new_program_id,
            description=f"Cloned LMS program from '{src_program['program_name']}' to '{cloned_name}'"
        )
        
        flash(f"Program cloned successfully as '{cloned_name}'.", 'success')
        return redirect(url_for('lms_admin.list_programs'))
        
    except Exception as e:
        flash(f"Error cloning program: {str(e)}", 'danger')
        return redirect(url_for('lms_admin.list_programs'))
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
                lp.program_reference_name,
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
            WHERE lp.id = ? AND lp.is_deleted = 0
        """, (program_id,))
        program = cur.fetchone()
        
        if not program:
            flash('Program not found.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))
        
        # Legacy chapters remain for migration/audit only. Current program content
        # is driven by linked master chapters.
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
        legacy_chapters = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) as count FROM lms_program_chapters WHERE program_id = ?",
            (program_id,)
        )
        linked_master_chapters = cur.fetchone()['count']
        cur.execute(
            """
                SELECT
                    pc.id AS link_id,
                    pc.chapter_order,
                    pc.custom_title,
                    pc.is_visible,
                    pc.master_chapter_id,
                    mc.title AS master_title,
                    COUNT(mt.id) AS topic_count
                FROM lms_program_chapters pc
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                LEFT JOIN lms_master_topics mt
                    ON mt.master_chapter_id = mc.id
                   AND mt.status = 'active'
                WHERE pc.program_id = ?
                GROUP BY pc.id
                ORDER BY pc.chapter_order ASC, pc.id ASC
            """,
            (program_id,)
        )
        linked_master_chapter_items = cur.fetchall()
        total_chapters = linked_master_chapters or 0
        
        # Get total topics count
        cur.execute("""
            SELECT COUNT(*) as count
            FROM lms_master_topics mt
            JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
            WHERE pc.program_id = ?
              AND mt.status = 'active'
        """, (program_id,))
        total_topics = cur.fetchone()['count']

        cur.execute("""
            SELECT COUNT(DISTINCT s.id) as count
            FROM students s
            JOIN lms_programs lp ON lp.id = ?
            WHERE s.status = 'active'
              AND lp.is_active = 1
              AND lp.is_deleted = 0
              AND EXISTS (
                  SELECT 1 FROM lms_student_program_access spa
                  WHERE spa.student_id = s.id AND spa.program_id = lp.id
                    AND spa.is_active = 1
                    AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
              )
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
            'chapters': [],
            'legacy_chapter_count': len(legacy_chapters),
            'linked_master_chapter_items': linked_master_chapter_items,
            'total_chapters': total_chapters,
            'linked_master_chapters': linked_master_chapters or 0,
            'total_topics': total_topics,
            'total_students': total_students,
            'total_tests': total_tests,
            'resources': resources,
            'resource_count': len(resources),
            'recent_activity': recent_activity
        }

        # Legacy topics are no longer displayed in the canonical program view.
        topics_by_chapter = {}
        summary['topics_by_chapter'] = topics_by_chapter

        # Content coverage: count topics that have each content type
        if total_topics > 0:
            cur.execute("""
                SELECT
                    (SELECT COUNT(DISTINCT mt.id)
                     FROM lms_master_topics mt
                     JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                     JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                     WHERE pc.program_id = ?
                       AND pc.is_visible = 1
                       AND mt.status = 'active'
                       AND ltc.content_mode = 'youtube') AS topics_with_video,
                    (SELECT COUNT(DISTINCT mt.id)
                     FROM lms_master_topics mt
                     JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                     JOIN lms_topic_contents ltc ON ltc.master_topic_id = mt.id
                     WHERE pc.program_id = ?
                       AND pc.is_visible = 1
                       AND mt.status = 'active'
                       AND ltc.content_mode IN ('pdf', 'rich_text', 'interactive_image')) AS topics_with_pdf,
                    (SELECT COUNT(DISTINCT mt.id)
                     FROM lms_master_topics mt
                     JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                     JOIN lms_assignments a ON a.master_topic_id = mt.id
                     WHERE pc.program_id = ?
                       AND pc.is_visible = 1
                       AND mt.status = 'active') AS topics_with_assignments
            """, (program_id, program_id, program_id))
            coverage = cur.fetchone()
            summary['topics_with_video'] = coverage['topics_with_video'] or 0
            summary['topics_with_pdf'] = coverage['topics_with_pdf'] or 0
            summary['topics_with_assignments'] = coverage['topics_with_assignments'] or 0
        else:
            summary['topics_with_video'] = 0
            summary['topics_with_pdf'] = 0
            summary['topics_with_assignments'] = 0

        return render_template('lms_program_view.html', summary=summary)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/delete', methods=['POST'])
@admin_required
def delete_program(program_id):
    """Soft-delete an LMS program (sets is_deleted = 1)."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, program_name, slug
            FROM lms_programs
            WHERE id = ? AND is_deleted = 0
        """, (program_id,))
        program = cur.fetchone()

        if not program:
            flash('Program not found or already deleted.', 'danger')
            return redirect(url_for('lms_admin.list_programs'))

        now = datetime.now().isoformat(timespec='seconds')
        cur.execute("""
            UPDATE lms_programs
            SET is_deleted = 1, updated_at = ?
            WHERE id = ?
        """, (now, program_id))
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='delete',
            module_name='lms_programs',
            record_id=program_id,
            description=f'Soft-deleted program: {program["program_name"]}'
        )

        flash(f'Program "{program["program_name"]}" has been deleted.', 'success')
        return redirect(url_for('lms_admin.list_programs'))
    except Exception as e:
        flash(f'Error deleting program: {str(e)}', 'danger')
        return redirect(url_for('lms_admin.program_view', program_id=program_id))
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
                COUNT(DISTINCT b.master_topic_id) as topics_mapped_master
            FROM lms_chapters lc
            LEFT JOIN lms_topics lt ON lc.id = lt.chapter_id
            LEFT JOIN lms_topic_contents ltc ON ltc.topic_id = lt.id
            LEFT JOIN lms_master_topic_bridge b ON b.legacy_topic_id = lt.id
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
                    COUNT(DISTINCT CASE WHEN ltc.id IS NOT NULL THEN mt.id END) AS topics_with_content,
                    (SELECT COUNT(*) FROM lms_program_chapters pc2 WHERE pc2.master_chapter_id = pc.master_chapter_id) AS link_count
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

        unmigrated_legacy_chapters = [
            chapter for chapter in chapters
            if (chapter['topic_count'] or 0) > 0
            and (chapter['topics_mapped_master'] or 0) == 0
        ]
        
        data = {
            'program': program,
            'chapters': chapters,
            'linked_master_chapters': linked_master_chapters,
            'available_master_chapters': available_master_chapters,
            'legacy_chapter_count': len(chapters),
            'unmigrated_legacy_chapter_count': len(unmigrated_legacy_chapters),
            'linked_master_chapter_count': len(linked_master_chapters),
            'total_chapters': len(linked_master_chapters),
        }
        
        return render_template('lms_chapters.html', data=data)
    finally:
        conn.close()


@lms_admin_bp.route('/program/<int:program_id>/chapter/<int:chapter_id>/migrate-to-master-pilot', methods=['POST'])
@admin_required
def migrate_legacy_chapter_pilot(program_id, chapter_id):
    """Phase 5 pilot: migrate one legacy chapter to master tables for one program."""
    flash('Single-chapter pilot migration has moved to Legacy Migration.', 'info')
    return redirect(url_for('lms_admin.phase6_rollout_view'))

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
    """Legacy migration dashboard: discover unmigrated legacy chapters by program."""
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
    """Controlled migration for selected legacy chapters of one program."""
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
                f"Legacy Migration moved {len(migrated)} chapter(s) in program {program['program_name']}; "
                f"skipped {len(skipped)}; backup={os.path.basename(backup_path)}"
            )
        )

        flash(
            f"Legacy Migration complete for {program['program_name']}: migrated {len(migrated)} chapter(s), "
            f"skipped {len(skipped)}. Backup: {os.path.basename(backup_path)}",
            'success'
        )
        return redirect(url_for('lms_admin.phase6_rollout_view'))
    except Exception as e:
        conn.rollback()
        flash(f'Legacy Migration failed: {str(e)}', 'danger')
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


@lms_admin_bp.route('/program/<int:program_id>/chapter-link/<int:link_id>/branch', methods=['POST'])
@admin_required
def branch_program_chapter(program_id, link_id):
    """Branch a shared master chapter to make it program-specific by cloning it and all its topics."""
    from modules.lms_admin.branch_helpers import _clone_master_chapter
    conn = get_conn()
    try:
        cur = conn.cursor()
        link_row = cur.execute(
            """
                SELECT pc.*, mc.title AS master_title
                FROM lms_program_chapters pc
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                WHERE pc.id = ? AND pc.program_id = ?
            """,
            (link_id, program_id)
        ).fetchone()

        if not link_row:
            flash('Linked chapter not found.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        old_master_chapter_id = link_row['master_chapter_id']

        # Call branching helper to duplicate the chapter
        new_master_chapter_id = _clone_master_chapter(cur, old_master_chapter_id)
        if not new_master_chapter_id:
            flash('Error branching chapter.', 'danger')
            return redirect(url_for('lms_admin.list_chapters', program_id=program_id))

        # Update link to point to the branched master chapter
        cur.execute(
            """
                UPDATE lms_program_chapters
                SET master_chapter_id = ?
                WHERE id = ?
            """,
            (new_master_chapter_id, link_id)
        )
        conn.commit()

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='edit',
            module_name='lms_program_chapters',
            record_id=link_id,
            description=f'Branched master chapter {link_row["master_title"]} for program id {program_id}'
        )
        flash('Chapter branched successfully to a private copy.', 'success')
        return redirect(url_for('lms_admin.list_chapters', program_id=program_id))
    except Exception as e:
        flash(f'Error branching chapter: {str(e)}', 'danger')
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
    return _redirect_legacy_cleanup(program_id)

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
        return _redirect_legacy_chapter_to_master(cur, chapter_id, endpoint='edit')
        
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
        return _redirect_legacy_chapter_to_master(cur, chapter_id)
        
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
        return _redirect_legacy_chapter_to_master(cur, chapter_id)
        
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

        # Find which topics in this chapter are mapped to master topics
        topic_ids = [t['id'] for t in topics]
        master_mapped_ids = set()
        if topic_ids:
            placeholders = ','.join('?' * len(topic_ids))
            rows = cur.execute(
                f"SELECT legacy_topic_id FROM lms_master_topic_bridge WHERE legacy_topic_id IN ({placeholders})",
                topic_ids
            ).fetchall()
            master_mapped_ids = {r['legacy_topic_id'] for r in rows}

        data = {
            'program': {
                'id': chapter['program_id'],
                'program_name': chapter['program_name']
            },
            'chapter': chapter,
            'topics': topics,
            'total_topics': total_topics,
            'master_mapped_ids': master_mapped_ids,
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
        return _redirect_legacy_chapter_to_master(cur, chapter_id)

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
        return _redirect_legacy_chapter_to_master(cur, chapter_id, endpoint='new_topic')
        
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
        return _redirect_legacy_topic_to_master(cur, topic_id, endpoint='edit')
        
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
        return _redirect_legacy_topic_to_master(cur, topic_id)
        
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

        # If this legacy topic is mapped to a master topic, redirect there
        bridge = cur.execute(
            "SELECT master_topic_id FROM lms_master_topic_bridge WHERE legacy_topic_id = ?",
            (topic_id,)
        ).fetchone()
        if bridge:
            return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=bridge['master_topic_id']))

        return _redirect_legacy_cleanup(topic['program_id'])

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
            'lesson_content': lesson_content
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

        return _redirect_legacy_topic_to_master(cur, topic_id)
        
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

        # If this legacy topic is mapped to a master topic, redirect content upload there
        bridge = cur.execute(
            "SELECT master_topic_id FROM lms_master_topic_bridge WHERE legacy_topic_id = ?",
            (topic_id,)
        ).fetchone()
        if bridge:
            flash('This topic is linked to the Master Library. Content is managed there.', 'info')
            redirect_url = url_for('lms_admin.master_content_new', master_topic_id=bridge['master_topic_id'])
            preset = request.args.get('type', '')
            if preset:
                redirect_url += f'?type={preset}'
            return redirect(redirect_url)

        return _redirect_legacy_cleanup(topic['program_id'])

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
                ltc.master_topic_id,
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

        if not content['master_topic_id']:
            master_topic_id = _master_topic_id_for_legacy_topic(cur, content['topic_id'])
            if master_topic_id:
                flash('This legacy content is now managed in the Master Library.', 'info')
                return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=master_topic_id))
            return _redirect_legacy_cleanup(content['program_id'])

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

    unique_name = datetime.now().strftime('%Y%m%d_%H%M%S_') + filename
    dest_path = f"course_images/inline/{unique_name}"
    try:
        storage_service = get_storage_service()
        storage_service.upload_file(file_obj, dest_path, content_type=file_obj.content_type)
    except Exception as e:
        logger.error(f"Failed to upload inline image to storage: {e}", exc_info=True)
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
    dest_path = f"course_images/inline/{safe_name}"
    
    try:
        storage_service = get_storage_service()
        if storage_service.file_exists(dest_path):
            return redirect(storage_service.generate_public_url(dest_path))
    except Exception as e:
        logger.error(f"Failed to serve inline image from storage: {e}", exc_info=True)
        
    # Fallback to local files if it exists, for backward compatibility
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'lms', 'images', 'inline'))
    if os.path.exists(os.path.join(base_dir, safe_name)):
        ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                    'gif': 'image/gif', 'webp': 'image/webp'}
        mimetype = mime_map.get(ext, 'image/jpeg')
        resp = send_from_directory(base_dir, safe_name, mimetype=mimetype)
        resp.headers['Cache-Control'] = 'no-store, no-cache'
        return resp
        
    return 'Not Found', 404


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
        if not is_master_topic:
            master_topic_id = _master_topic_id_for_legacy_topic(cur, content['topic_id'])
            if master_topic_id:
                flash('This legacy content is now managed in the Master Library.', 'info')
                return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=master_topic_id))
            return _redirect_legacy_cleanup(_legacy_topic_program_id(cur, content['topic_id']))

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
                    return redirect(url_for('lms_admin.list_master_topics', master_chapter_id=chapter['id']))
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

        if not content['master_topic_id']:
            master_topic_id = _master_topic_id_for_legacy_topic(cur, content['topic_id'])
            if master_topic_id:
                flash('This legacy content is now managed in the Master Library.', 'info')
                return redirect(url_for('lms_admin.list_master_topic_contents', master_topic_id=master_topic_id))
            return _redirect_legacy_cleanup(_legacy_topic_program_id(cur, content['topic_id']))
        
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

        return _redirect_legacy_topic_to_master(cur, topic_id)
        
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

        return _redirect_legacy_topic_to_master(cur, topic_id)
        
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

        return _redirect_legacy_topic_to_master(cur, attachment['topic_id'])
        
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
        return _redirect_legacy_topic_to_master(cur, topic_id)
        
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


# ===========================
# PHASE 3: STUDENT PROGRESS MONITORING
# ===========================

@lms_admin_bp.route('/progress-dashboard', methods=['GET'])
@login_required
def progress_dashboard():
    """Enhanced student progress monitoring dashboard with filters."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # ── Filter param extraction ──────────────────────────────────────
        f_branch_id  = request.args.get('branch_id',  '').strip()
        f_batch_id   = request.args.get('batch_id',   '').strip()
        f_program_id = request.args.get('program_id', '').strip()
        f_staff_id   = request.args.get('staff_id',   '').strip()
        f_q          = request.args.get('q',           '').strip()

        branch_id  = int(f_branch_id)  if f_branch_id.isdigit()  else None
        batch_id   = int(f_batch_id)   if f_batch_id.isdigit()   else None
        program_id = int(f_program_id) if f_program_id.isdigit() else None
        staff_id   = int(f_staff_id)   if f_staff_id.isdigit()   else None
        q          = f_q or None

        # ── Dropdown data for filter bar ────────────────────────────────
        branches = cur.execute(
            "SELECT id, branch_name FROM branches WHERE is_active = 1 ORDER BY branch_name"
        ).fetchall()

        if branch_id:
            filter_batches = cur.execute(
                "SELECT id, batch_name FROM batches WHERE branch_id = ? AND status = 'active' ORDER BY batch_name",
                (branch_id,)
            ).fetchall()
        else:
            filter_batches = cur.execute(
                "SELECT id, batch_name FROM batches WHERE status = 'active' ORDER BY batch_name"
            ).fetchall()

        programs = cur.execute(
            "SELECT id, program_name FROM lms_programs WHERE is_active = 1 AND is_deleted = 0 ORDER BY program_name"
        ).fetchall()

        staff_users = cur.execute(
            """SELECT DISTINCT u.id, u.full_name
               FROM users u
               JOIN batches b ON b.trainer_id = u.id
               JOIN student_batches sb ON sb.batch_id = b.id AND sb.status = 'active'
               JOIN students s ON s.id = sb.student_id AND s.status = 'active'
               WHERE u.is_active = 1
               ORDER BY u.full_name"""
        ).fetchall()

        # ── WHERE clause builder ────────────────────────────────────────
        # Mirror the student portal's 4-path enrollment check so every
        # student who can see a program also appears in the admin view.
        _enroll_check = """(
            EXISTS (
                SELECT 1 FROM lms_student_program_access spa
                WHERE spa.student_id = s.id AND spa.program_id = lp.id
                  AND spa.is_active = 1
                  AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
            )
            OR EXISTS (
                SELECT 1 FROM lms_batch_program_access bpa
                JOIN student_batches sb ON sb.batch_id = bpa.batch_id
                WHERE sb.student_id = s.id AND bpa.program_id = lp.id
                  AND bpa.is_active = 1 AND sb.status = 'active'
                  AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
            )
            OR EXISTS (
                SELECT 1 FROM invoices inv
                JOIN invoice_items ii ON ii.invoice_id = inv.id
                WHERE inv.student_id = s.id AND ii.course_id = lp.course_id
                  AND lp.course_id IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM invoices inv
                JOIN invoice_items ii ON ii.invoice_id = inv.id
                JOIN lms_course_program_map cpm ON cpm.course_id = ii.course_id
                  AND cpm.program_id = lp.id
                WHERE inv.student_id = s.id
            )
        )"""

        where_clauses = [
            "s.status = 'active'",
            "lp.is_active = 1",
            "lp.is_deleted = 0",
            _enroll_check,
        ]
        params = []

        if program_id:
            where_clauses.append("lp.id = ?")
            params.append(program_id)

        if batch_id:
            # Student must be in this specific batch
            where_clauses.append("""EXISTS (
                SELECT 1 FROM student_batches sb_f
                WHERE sb_f.student_id = s.id AND sb_f.batch_id = ? AND sb_f.status = 'active'
            )""")
            params.append(batch_id)

        if branch_id:
            # Student's active batch must belong to this branch, OR student's own branch
            where_clauses.append("""(
                EXISTS (
                    SELECT 1 FROM student_batches sb_br
                    JOIN batches bat_br ON bat_br.id = sb_br.batch_id
                    WHERE sb_br.student_id = s.id AND sb_br.status = 'active'
                      AND bat_br.branch_id = ?
                )
                OR s.branch_id = ?
            )""")
            params.extend([branch_id, branch_id])

        if staff_id:
            # Student's active batch must have this trainer
            where_clauses.append("""EXISTS (
                SELECT 1 FROM student_batches sb_st
                JOIN batches bat_st ON bat_st.id = sb_st.batch_id
                WHERE sb_st.student_id = s.id AND sb_st.status = 'active'
                  AND bat_st.trainer_id = ?
            )""")
            params.append(staff_id)

        if q:
            where_clauses.append(
                "(s.full_name LIKE ? OR s.student_code LIKE ? OR s.phone LIKE ?)"
            )
            params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])

        where_sql = " AND ".join(where_clauses)

        # ── Master-linked existence check (reused twice in SELECT) ───────
        _master_check = """EXISTS (
            SELECT 1 FROM lms_program_chapters pcx
            JOIN lms_master_chapters mcx ON mcx.id = pcx.master_chapter_id
            JOIN lms_master_topics   mtx ON mtx.master_chapter_id = mcx.id
            WHERE pcx.program_id = lp.id AND pcx.is_visible = 1
              AND mcx.status = 'active' AND mtx.status = 'active'
        )"""

        sql = f"""
            SELECT
                s.id               AS student_id,
                s.student_code,
                s.full_name,
                lp.id              AS program_id,
                lp.program_name,
                COALESCE(b.batch_name,  '') AS batch_name,
                COALESCE(br.branch_name, br2.branch_name, '') AS branch_name,
                COALESCE(u.full_name,   '') AS trainer_name,
                -- total topics: master-linked OR legacy (mirrors student portal)
                CASE WHEN {_master_check} THEN (
                    SELECT COUNT(*)
                    FROM lms_master_topics mt
                    JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                    JOIN lms_master_chapters  mc ON mc.id = pc.master_chapter_id
                    WHERE pc.program_id = lp.id AND pc.is_visible = 1
                      AND mc.status = 'active'  AND mt.status = 'active'
                ) ELSE (
                    SELECT COUNT(*)
                    FROM lms_topics lt
                    JOIN lms_chapters lc ON lt.chapter_id = lc.id
                    WHERE lc.program_id = lp.id AND lt.is_active = 1
                ) END AS total_topics,
                -- completed topics: master-linked OR legacy
                CASE WHEN {_master_check} THEN (
                    SELECT COUNT(*)
                    FROM lms_master_topic_progress mtp
                    JOIN lms_master_topics mt ON mt.id = mtp.master_topic_id
                    JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
                    JOIN lms_master_chapters  mc ON mc.id = pc.master_chapter_id
                    WHERE mtp.student_id = s.id AND mtp.program_id = lp.id AND mtp.is_completed = 1
                      AND pc.program_id = lp.id AND pc.is_visible = 1
                      AND mc.status = 'active'  AND mt.status = 'active'
                ) ELSE (
                    SELECT COUNT(*)
                    FROM lms_topic_progress tp
                    JOIN lms_topics lt ON tp.topic_id = lt.id
                    JOIN lms_chapters lc ON lt.chapter_id = lc.id
                    WHERE tp.student_id = s.id AND lc.program_id = lp.id AND tp.is_completed = 1
                ) END AS completed_topics,
                -- last activity across both progress stores
                (
                    SELECT MAX(last_act) FROM (
                        SELECT MAX(tp.completed_at) AS last_act
                        FROM lms_topic_progress tp
                        JOIN lms_topics lt ON tp.topic_id = lt.id
                        JOIN lms_chapters lc ON lt.chapter_id = lc.id
                        WHERE tp.student_id = s.id AND lc.program_id = lp.id
                        UNION ALL
                        SELECT MAX(mtp.completed_at) AS last_act
                        FROM lms_master_topic_progress mtp
                        WHERE mtp.student_id = s.id AND mtp.program_id = lp.id
                    )
                ) AS last_activity
            FROM students s
            JOIN lms_programs lp ON lp.is_active = 1 AND lp.is_deleted = 0
            -- Display batch: prefer spa.batch_id, fallback to any active student batch
            LEFT JOIN batches b ON b.id = COALESCE(
                (SELECT spa2.batch_id FROM lms_student_program_access spa2
                 WHERE spa2.student_id = s.id AND spa2.program_id = lp.id
                   AND spa2.is_active = 1 AND spa2.batch_id IS NOT NULL LIMIT 1),
                (SELECT MIN(sb3.batch_id) FROM student_batches sb3
                 WHERE sb3.student_id = s.id AND sb3.status = 'active')
            )
            LEFT JOIN branches br  ON br.id  = b.branch_id
            LEFT JOIN branches br2 ON br2.id = s.branch_id
            LEFT JOIN users    u   ON u.id   = b.trainer_id
            WHERE {where_sql}
            ORDER BY s.full_name ASC, lp.program_name ASC
        """

        rows = cur.execute(sql, params).fetchall()

        # ── Per-row enrichment ───────────────────────────────────────────
        def _fmt_date(val):
            if not val:
                return '—'
            try:
                from datetime import datetime as _dt
                return _dt.fromisoformat(str(val).replace('T', ' ').split('.')[0]).strftime('%d %b %Y')
            except Exception:
                return str(val)[:10]

        student_rows = []
        for row in rows:
            total = row['total_topics'] or 0
            done  = row['completed_topics'] or 0
            pct   = round(done / total * 100, 1) if total > 0 else 0.0
            if pct == 0:
                status, status_color = 'Not Started', 'danger'
            elif pct >= 100:
                status, status_color = 'Completed', 'success'
            else:
                status, status_color = 'In Progress', 'warning'
            bar_color = 'danger' if pct <= 25 else ('warning' if pct <= 60 else 'success')
            student_rows.append({
                'student_id':      row['student_id'],
                'student_code':    row['student_code'],
                'full_name':       row['full_name'],
                'program_id':      row['program_id'],
                'branch_name':     row['branch_name'],
                'batch_name':      row['batch_name'],
                'program_name':    row['program_name'],
                'trainer_name':    row['trainer_name'],
                'total_topics':    total,
                'completed_topics': done,
                'pct':             pct,
                'status':          status,
                'status_color':    status_color,
                'bar_color':       bar_color,
                'last_activity':   _fmt_date(row['last_activity']),
            })

        # ── KPI cards ───────────────────────────────────────────────────
        active_students   = len({r['student_id'] for r in student_rows})
        total_completed   = sum(r['completed_topics'] for r in student_rows)
        total_topics_sum  = sum(r['total_topics'] for r in student_rows)
        overall_pct       = round(total_completed / total_topics_sum * 100, 1) if total_topics_sum > 0 else 0.0
        not_started_count = sum(1 for r in student_rows if r['pct'] == 0)
        in_progress_count = sum(1 for r in student_rows if 0 < r['pct'] < 100)
        completed_count   = sum(1 for r in student_rows if r['pct'] >= 100)

        # ── Branch summary ───────────────────────────────────────────────
        branch_map = {}
        for r in student_rows:
            bn = r['branch_name']
            if bn not in branch_map:
                branch_map[bn] = {'branch_name': bn, 'students': set(), 'total': 0, 'done': 0,
                                  'not_started': 0, 'in_progress': 0, 'completed': 0}
            branch_map[bn]['students'].add(r['student_id'])
            branch_map[bn]['total'] += r['total_topics']
            branch_map[bn]['done']  += r['completed_topics']
            if   r['pct'] == 0:   branch_map[bn]['not_started']  += 1
            elif r['pct'] >= 100: branch_map[bn]['completed']     += 1
            else:                 branch_map[bn]['in_progress']   += 1

        branch_summary = []
        for bn, bd in sorted(branch_map.items()):
            avg = round(bd['done'] / bd['total'] * 100, 1) if bd['total'] > 0 else 0.0
            branch_summary.append({
                'branch_name':    bn,
                'total_students': len(bd['students']),
                'avg_pct':        avg,
                'not_started':    bd['not_started'],
                'in_progress':    bd['in_progress'],
                'completed':      bd['completed'],
            })

        # ── Batch summary ────────────────────────────────────────────────
        batch_map = {}
        for r in student_rows:
            bn = r['batch_name']
            if bn not in batch_map:
                batch_map[bn] = {
                    'batch_name':   bn,
                    'branch_name':  r['branch_name'],
                    'trainer_name': r['trainer_name'],
                    'programs': set(), 'students': set(),
                    'total': 0, 'done': 0, 'low_count': 0,
                }
            batch_map[bn]['students'].add(r['student_id'])
            batch_map[bn]['programs'].add(r['program_name'])
            batch_map[bn]['total'] += r['total_topics']
            batch_map[bn]['done']  += r['completed_topics']
            if r['pct'] < 25:
                batch_map[bn]['low_count'] += 1

        batch_summary = []
        for bn, bd in sorted(batch_map.items()):
            avg = round(bd['done'] / bd['total'] * 100, 1) if bd['total'] > 0 else 0.0
            batch_summary.append({
                'batch_name':    bn,
                'branch_name':   bd['branch_name'],
                'trainer_name':  bd['trainer_name'],
                'programs':      ', '.join(sorted(bd['programs'])),
                'student_count': len(bd['students']),
                'avg_pct':       avg,
                'low_count':     bd['low_count'],
            })

        # ── Staff summary (unassigned students kept separate) ──────────────
        # trainer_name is '' when no trainer/batch is assigned
        staff_map = {}
        for r in student_rows:
            tn = r['trainer_name']  # empty string = no trainer assigned
            if tn not in staff_map:
                staff_map[tn] = {
                    'batches': set(), 'students': set(),
                    'total': 0, 'done': 0, 'below25': 0, 'above75': 0,
                }
            staff_map[tn]['students'].add(r['student_id'])
            staff_map[tn]['batches'].add(r['batch_name'])
            staff_map[tn]['total'] += r['total_topics']
            staff_map[tn]['done']  += r['completed_topics']
            if r['pct'] < 25:  staff_map[tn]['below25'] += 1
            if r['pct'] > 75:  staff_map[tn]['above75'] += 1

        staff_summary = []
        unassigned_summary = None
        # Sort named trainers first; unassigned (empty key) goes to unassigned_summary
        for tn, td in sorted(staff_map.items(), key=lambda x: (not x[0], x[0])):
            avg = round(td['done'] / td['total'] * 100, 1) if td['total'] > 0 else 0.0
            entry = {
                'trainer_name':  tn,
                'batch_count':   len(td['batches']),
                'student_count': len(td['students']),
                'avg_pct':       avg,
                'below25':       td['below25'],
                'above75':       td['above75'],
            }
            if not tn:
                unassigned_summary = entry
            else:
                staff_summary.append(entry)

        filters = {
            'branch_id':  f_branch_id,
            'batch_id':   f_batch_id,
            'program_id': f_program_id,
            'staff_id':   f_staff_id,
            'q':          f_q,
            'is_filtered': any([branch_id, batch_id, program_id, staff_id, q]),
        }

        return render_template(
            'lms_progress_dashboard.html',
            filters=filters,
            branches=branches,
            filter_batches=filter_batches,
            programs=programs,
            staff_users=staff_users,
            student_rows=student_rows,
            active_students=active_students,
            overall_pct=overall_pct,
            total_completed=total_completed,
            not_started_count=not_started_count,
            in_progress_count=in_progress_count,
            completed_count=completed_count,
            total_topics_sum=total_topics_sum,
            branch_summary=branch_summary,
            batch_summary=batch_summary,
            staff_summary=staff_summary,
            unassigned_summary=unassigned_summary,
        )
    finally:
        conn.close()


@lms_admin_bp.route('/student/<int:student_id>/progress', methods=['GET'])
@login_required
def view_student_progress(student_id):
    """Detailed progress page for a single student"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        requested_program_id = _strict_positive_int(request.args.get('program_id'))
        
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
        
        enroll_check = """(
            EXISTS (
                SELECT 1 FROM lms_student_program_access spa
                WHERE spa.student_id = ? AND spa.program_id = lp.id
                  AND spa.is_active = 1
                  AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
            )
            OR EXISTS (
                SELECT 1 FROM lms_batch_program_access bpa
                JOIN student_batches sb ON sb.batch_id = bpa.batch_id
                WHERE sb.student_id = ? AND bpa.program_id = lp.id
                  AND bpa.is_active = 1 AND sb.status = 'active'
                  AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
            )
            OR EXISTS (
                SELECT 1 FROM invoices inv
                JOIN invoice_items ii ON ii.invoice_id = inv.id
                WHERE inv.student_id = ? AND ii.course_id = lp.course_id
                  AND lp.course_id IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM invoices inv
                JOIN invoice_items ii ON ii.invoice_id = inv.id
                JOIN lms_course_program_map cpm ON cpm.course_id = ii.course_id
                  AND cpm.program_id = lp.id
                WHERE inv.student_id = ?
            )
        )"""

        program_where = [
            "lp.is_active = 1",
            "lp.is_deleted = 0",
            enroll_check,
        ]
        program_params = [student_id, student_id, student_id, student_id]
        if requested_program_id:
            program_where.append("lp.id = ?")
            program_params.append(requested_program_id)

        cur.execute(f"""
            SELECT
                NULL as assignment_id,
                lp.id as program_id,
                COALESCE((
                    SELECT spa.access_start_date
                    FROM lms_student_program_access spa
                    WHERE spa.student_id = ? AND spa.program_id = lp.id
                      AND spa.is_active = 1
                    ORDER BY spa.access_start_date DESC
                    LIMIT 1
                ), '') as access_start_date,
                COALESCE((
                    SELECT spa.access_end_date
                    FROM lms_student_program_access spa
                    WHERE spa.student_id = ? AND spa.program_id = lp.id
                      AND spa.is_active = 1
                    ORDER BY spa.access_start_date DESC
                    LIMIT 1
                ), '') as access_end_date,
                1 as is_active,
                lp.program_name,
                lp.slug as program_code,
                lp.description
            FROM lms_programs lp
            WHERE {" AND ".join(program_where)}
            ORDER BY lp.program_name
        """, [student_id, student_id] + program_params)
        programs = cur.fetchall()
        
        # Build hierarchical data for each program
        programs_with_details = []
        
        for prog in programs:
            program_id = prog['program_id']

            cur.execute("""
                SELECT COUNT(*) as c
                FROM lms_program_chapters pc
                JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
                WHERE pc.program_id = ? AND pc.is_visible = 1
                  AND mc.status = 'active' AND mt.status = 'active'
            """, (program_id,))
            has_master_content = (cur.fetchone()['c'] or 0) > 0
            
            chapters_with_topics = []
            if has_master_content:
                cur.execute("""
                    SELECT
                        pc.id,
                        pc.master_chapter_id,
                        COALESCE(NULLIF(pc.custom_title, ''), mc.title) as chapter_title,
                        pc.chapter_order,
                        mc.description,
                        COUNT(mt.id) as total_topics,
                        COALESCE(SUM(CASE WHEN mtp.is_completed = 1 THEN 1 ELSE 0 END), 0) as completed_topics
                    FROM lms_program_chapters pc
                    JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                    LEFT JOIN lms_master_topics mt
                      ON mt.master_chapter_id = mc.id AND mt.status = 'active'
                    LEFT JOIN lms_master_topic_progress mtp
                      ON mtp.master_topic_id = mt.id
                     AND mtp.student_id = ?
                     AND mtp.program_id = pc.program_id
                    WHERE pc.program_id = ? AND pc.is_visible = 1
                      AND mc.status = 'active'
                    GROUP BY pc.id, pc.master_chapter_id, mc.title, pc.custom_title,
                             pc.chapter_order, mc.description
                    ORDER BY pc.chapter_order
                """, (student_id, program_id))
                chapters = cur.fetchall()
                
                for index, chap in enumerate(chapters, start=1):
                    cur.execute("""
                        SELECT
                            mt.id,
                            mt.title as topic_title,
                            mt.topic_order,
                            1 as is_required,
                            COALESCE(CASE WHEN mtp.is_completed = 1 THEN 100 ELSE 0 END, 0) as completion_percentage,
                            COALESCE(mtp.completed_at, 'Not started') as last_accessed,
                            0 as time_spent_minutes
                        FROM lms_master_topics mt
                        LEFT JOIN lms_master_topic_progress mtp
                          ON mtp.master_topic_id = mt.id
                         AND mtp.student_id = ?
                         AND mtp.program_id = ?
                        WHERE mt.master_chapter_id = ? AND mt.status = 'active'
                        ORDER BY mt.topic_order
                    """, (student_id, program_id, chap['master_chapter_id']))
                    topics = [
                        {**dict(topic), 'topic_number': topic['topic_order']}
                        for topic in cur.fetchall()
                    ]

                    chapters_with_topics.append({
                        'id': chap['id'],
                        'chapter_number': chap['chapter_order'] or index,
                        'chapter_title': chap['chapter_title'],
                        'chapter_order': chap['chapter_order'],
                        'description': chap['description'],
                        'total_topics': chap['total_topics'],
                        'completed_topics': chap['completed_topics'],
                        'topics': topics
                    })
            else:
                cur.execute("""
                    SELECT
                        lc.id,
                        lc.chapter_title,
                        lc.chapter_order,
                        lc.description,
                        (SELECT COUNT(*) FROM lms_topics WHERE chapter_id = lc.id AND is_active = 1) as total_topics,
                        (SELECT COUNT(*) FROM lms_topic_progress
                         WHERE student_id = ? AND topic_id IN
                         (SELECT id FROM lms_topics WHERE chapter_id = lc.id AND is_active = 1)
                         AND is_completed = 1) as completed_topics
                    FROM lms_chapters lc
                    WHERE lc.program_id = ? AND lc.is_active = 1
                    ORDER BY lc.chapter_order
                """, (student_id, program_id))
                chapters = cur.fetchall()

                for index, chap in enumerate(chapters, start=1):
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
                        LEFT JOIN lms_topic_progress stp
                          ON lt.id = stp.topic_id AND stp.student_id = ?
                        WHERE lt.chapter_id = ? AND lt.is_active = 1
                        ORDER BY lt.topic_order
                    """, (student_id, chap['id']))
                    topics = [
                        {**dict(topic), 'topic_number': topic['topic_order']}
                        for topic in cur.fetchall()
                    ]

                    chapters_with_topics.append({
                        'id': chap['id'],
                        'chapter_number': chap['chapter_order'] or index,
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
                'program_title': prog['program_name'],
                'program_code': prog['program_code'],
                'description': prog['description'],
                'access_start_date': prog['access_start_date'],
                'access_end_date': prog['access_end_date'],
                'is_active': prog['is_active'],
                'total_chapters': len(chapters_with_topics),
                'total_topics': total_topics,
                'total_completed': total_completed,
                'completion_percentage': round(program_completion, 1),
                'chapters': chapters_with_topics
            })
        
        # Get student's test results if any
        cur.execute("""
            SELECT 
                str.test_id,
                lmt.test_title as test_name,
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

        assignment_filters = ["s.student_id = ?", "s.is_latest = 1"]
        assignment_params = [student_id]
        if requested_program_id:
            assignment_filters.append("""
                EXISTS (
                    SELECT 1
                    FROM lms_program_chapters pc
                    JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
                    WHERE pc.program_id = ?
                      AND pc.master_chapter_id = mt.master_chapter_id
                      AND pc.is_visible = 1
                      AND mc.status = 'active'
                )
            """)
            assignment_params.append(requested_program_id)

        cur.execute(f"""
            SELECT
                s.id,
                s.assignment_id,
                a.title as assignment_title,
                mt.title as topic_title,
                s.original_filename,
                s.feedback,
                s.rejection_reason,
                COALESCE(s.review_status, 'submitted') as review_status,
                s.submitted_at,
                s.reviewed_at,
                u.full_name as reviewed_by_name
            FROM lms_assignment_submissions s
            JOIN lms_assignments a ON a.id = s.assignment_id
            JOIN lms_master_topics mt ON mt.id = a.master_topic_id
            LEFT JOIN users u ON u.id = s.reviewed_by
            WHERE {" AND ".join(assignment_filters)}
            ORDER BY datetime(COALESCE(s.reviewed_at, s.submitted_at)) DESC, s.id DESC
        """, assignment_params)
        assignment_submissions = cur.fetchall()

        assignment_stats = {
            'total': len(assignment_submissions),
            'accepted': sum(1 for row in assignment_submissions if row['review_status'] == 'accepted'),
            'rejected': sum(1 for row in assignment_submissions if row['review_status'] == 'rejected'),
            'pending': sum(1 for row in assignment_submissions if row['review_status'] == 'submitted'),
        }
        
        # Get overall statistics
        total_topics = sum(p['total_topics'] for p in programs_with_details)
        total_completed = sum(p['total_completed'] for p in programs_with_details)
        overall_completion = (total_completed / total_topics * 100) if total_topics > 0 else 0
        
        # Get most recent activity
        cur.execute("""
            SELECT topic_title, completion_percentage, last_accessed
            FROM (
                SELECT
                    mt.title as topic_title,
                    CASE WHEN mtp.is_completed = 1 THEN 100 ELSE 0 END as completion_percentage,
                    mtp.completed_at as last_accessed
                FROM lms_master_topic_progress mtp
                JOIN lms_master_topics mt ON mt.id = mtp.master_topic_id
                WHERE mtp.student_id = ?
                  AND (? IS NULL OR mtp.program_id = ?)
                UNION ALL
                SELECT
                    lt.topic_title,
                    CASE WHEN stp.is_completed = 1 THEN 100 ELSE 0 END as completion_percentage,
                    stp.completed_at as last_accessed
                FROM lms_topic_progress stp
                JOIN lms_topics lt ON stp.topic_id = lt.id
                JOIN lms_chapters lc ON lc.id = lt.chapter_id
                WHERE stp.student_id = ?
                  AND (? IS NULL OR lc.program_id = ?)
            )
            WHERE last_accessed IS NOT NULL
            ORDER BY last_accessed DESC
            LIMIT 5
        """, (
            student_id, requested_program_id, requested_program_id,
            student_id, requested_program_id, requested_program_id,
        ))
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
            'assignment_submissions': assignment_submissions,
            'assignment_stats': assignment_stats,
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
                lp.program_name,
                lp.program_reference_name
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
                'program_reference_name': r['program_reference_name'],
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
            SELECT id, program_name, program_reference_name FROM lms_programs WHERE is_active = 1
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


# ---------------------------------------------------------------------------
# LMS Assignments — Admin / Staff
# ---------------------------------------------------------------------------

_ASSIGNMENT_ALLOWED_EXTS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'jpg', 'jpeg', 'png'}
_ASSIGNMENT_MAX_BYTES     = 50 * 1024 * 1024   # 50 MB
_ASSIGNMENT_DESCRIPTION_MAX_BYTES = 500 * 1024  # 500 KB of UTF-8/HTML


def _validate_assignment_description(description):
    """Validate rich-text assignment instructions using the stored UTF-8 byte size."""
    size = len((description or '').encode('utf-8'))
    if size > _ASSIGNMENT_DESCRIPTION_MAX_BYTES:
        return False, (
            f'Description is too large ({size / 1024:.1f} KB). '
            'Maximum allowed size is 500 KB.'
        )
    return True, None


_GRADING_MODES = {'accept_reject', 'numeric', 'rubric', 'numeric_rubric'}
_COMPLETION_RULES = {
    'accepted_submission', 'score_meets_passing_score',
    'all_required_assignments_accepted', 'any_required_assignment_accepted',
    'manual_topic_completion', 'does_not_affect_topic_completion',
}


def _parse_assignment_grading_settings(conn):
    """Validate optional Phase 9 assignment settings from the current form."""
    grading_mode = (request.form.get('grading_mode') or 'accept_reject').strip()
    completion_rule = (request.form.get('completion_rule') or 'accepted_submission').strip()
    if grading_mode not in _GRADING_MODES:
        return None, 'Invalid grading mode.'
    if completion_rule not in _COMPLETION_RULES:
        return None, 'Invalid completion rule.'

    due_raw = (request.form.get('due_at') or '').strip()
    due_at = None
    if due_raw:
        try:
            due_at = datetime.strptime(due_raw, '%Y-%m-%dT%H:%M').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None, 'Due date and time is invalid.'

    def optional_decimal(field, label):
        raw = (request.form.get(field) or '').strip()
        if not raw:
            return None, None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            return None, f'{label} must be a number.'
        if value < 0:
            return None, f'{label} cannot be negative.'
        return value, None

    max_score, error = optional_decimal('max_score', 'Maximum score')
    if error: return None, error
    passing_score, error = optional_decimal('passing_score', 'Passing score')
    if error: return None, error
    if grading_mode in {'numeric', 'numeric_rubric'} and (max_score is None or max_score <= 0):
        return None, 'A positive maximum score is required for numeric grading.'

    rubric_id = request.form.get('rubric_id', type=int)
    if grading_mode in {'rubric', 'numeric_rubric'}:
        rubric = conn.execute(
            'SELECT id FROM lms_rubrics WHERE id = ? AND is_active = 1', (rubric_id,)
        ).fetchone() if rubric_id else None
        if not rubric:
            return None, 'An active rubric is required for rubric grading.'
        rubric_total = Decimal(str(conn.execute(
            'SELECT COALESCE(SUM(max_score), 0) AS total FROM lms_rubric_criteria WHERE rubric_id = ?',
            (rubric_id,),
        ).fetchone()['total']))
        if rubric_total <= 0:
            return None, 'The selected rubric must contain scored criteria.'
        if max_score is None:
            max_score = rubric_total
        elif max_score != rubric_total:
            return None, f'Maximum score must equal the rubric total ({rubric_total}).'
    else:
        rubric_id = None

    if passing_score is not None and max_score is None:
        return None, 'Set a maximum score before setting a passing score.'
    if passing_score is not None and passing_score > max_score:
        return None, 'Passing score cannot exceed the maximum score.'
    if completion_rule == 'score_meets_passing_score' and passing_score is None:
        return None, 'A passing score is required for score-based completion.'

    max_attempts_raw = (request.form.get('max_attempts') or '').strip()
    max_attempts = None
    if max_attempts_raw:
        if not max_attempts_raw.isdigit() or not 1 <= int(max_attempts_raw) <= 100:
            return None, 'Maximum attempts must be between 1 and 100.'
        max_attempts = int(max_attempts_raw)

    has_phase9_fields = 'grading_mode' in request.form
    return {
        'due_at': due_at, 'max_score': max_score, 'passing_score': passing_score,
        'grading_mode': grading_mode, 'rubric_id': rubric_id,
        'completion_rule': completion_rule,
        'allow_late_submission': (1 if not has_phase9_fields else
                                  (1 if request.form.get('allow_late_submission') == '1' else 0)),
        'max_attempts': max_attempts,
        'is_required': (1 if not has_phase9_fields else
                        (1 if request.form.get('is_required') == '1' else 0)),
    }, None


def _recalculate_assignment_topic_completion(conn, student_id, master_topic_id):
    """Apply assignment completion rules consistently after every decision."""
    rows = conn.execute(
        """SELECT a.id, a.completion_rule, a.passing_score, a.is_required,
                  COALESCE(s.review_status, 'not_submitted') AS review_status, s.score
           FROM lms_assignments a
           LEFT JOIN lms_assignment_submissions s
             ON s.assignment_id = a.id AND s.student_id = ? AND s.is_latest = 1
           WHERE a.master_topic_id = ?""",
        (student_id, master_topic_id),
    ).fetchall()
    if not rows or any(row['completion_rule'] == 'manual_topic_completion' for row in rows):
        return

    applicable = [row for row in rows if row['completion_rule'] != 'does_not_affect_topic_completion']
    if not applicable:
        completed = False
    else:
        def satisfied(row):
            if row['completion_rule'] == 'score_meets_passing_score':
                return (row['review_status'] == 'accepted' and row['score'] is not None
                        and Decimal(str(row['score'])) >= Decimal(str(row['passing_score'])))
            return row['review_status'] == 'accepted'
        required = [row for row in applicable if int(row['is_required'] or 0) == 1]
        if any(row['completion_rule'] == 'all_required_assignments_accepted' for row in applicable):
            completed = bool(required) and all(satisfied(row) for row in required)
        else:
            candidates = required if any(row['completion_rule'] == 'any_required_assignment_accepted' for row in applicable) else applicable
            completed = any(satisfied(row) for row in candidates)

    logger.info(
        "Assignment completion recalculated student=%s topic=%s completed=%s states=%s",
        student_id, master_topic_id, completed,
        [(row['id'], row['completion_rule'], row['review_status'], row['score']) for row in rows],
    )

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    programs = conn.execute(
        """SELECT DISTINCT pc.program_id FROM lms_program_chapters pc
           JOIN lms_master_topics mt ON mt.master_chapter_id = pc.master_chapter_id
           JOIN lms_programs lp ON lp.id = pc.program_id
           WHERE mt.id = ? AND pc.is_visible = 1 AND lp.is_active = 1""",
        (master_topic_id,),
    ).fetchall()
    for program in programs:
        updated = conn.execute(
            """UPDATE lms_master_topic_progress
               SET is_completed = ?, completed_at = ?, updated_at = ?
               WHERE student_id = ? AND program_id = ? AND master_topic_id = ?""",
            (1 if completed else 0, now if completed else None, now,
             student_id, program['program_id'], master_topic_id),
        )
        if updated.rowcount == 0:
            conn.execute(
                """INSERT INTO lms_master_topic_progress
                       (student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (student_id, program['program_id'], master_topic_id, 1 if completed else 0,
                 now if completed else None, now, now),
            )


def _save_assignment_file(file_obj):
    """Save admin-uploaded assignment to instance/uploads/assignments/.
    Returns (ok, unique_filename_or_error, original_name)."""
    orig_name = file_obj.filename or ''
    filename  = secure_filename(orig_name)
    if not filename:
        return False, 'Invalid filename.', ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in _ASSIGNMENT_ALLOWED_EXTS:
        return False, f'File type .{ext} not allowed. Use PDF, Word, Excel, PowerPoint, or image.', ''
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > _ASSIGNMENT_MAX_BYTES:
        return False, f'File too large ({size / 1048576:.1f} MB). Max 50 MB.', ''
    unique_name = datetime.now().strftime('%Y%m%d_%H%M%S_') + filename
    dest_path = f"documents/{unique_name}"
    
    try:
        storage_service = get_storage_service()
        storage_service.upload_file(file_obj, dest_path, content_type=file_obj.content_type)
        return True, dest_path, orig_name
    except Exception as e:
        logger.error(f"Failed to upload assignment file to storage: {e}", exc_info=True)
        return False, f"Failed to upload assignment file: {str(e)}", ""


@lms_admin_bp.route('/assignments')
@lms_content_manager_required
def assignments_alias():
    """Mobile bottom-nav friendly alias for the LMS assignment overview."""
    return redirect(url_for('lms_admin.all_assignments'))


@lms_admin_bp.route('/master/assignments')
@lms_content_manager_required
def all_assignments():
    """Overview of every assignment across all master topics with trainer/batch filters."""
    conn = get_conn()
    try:
        actor = _current_lms_actor(conn)
        if not actor:
            abort(403)
        role = actor['role']
        is_admin = role == 'admin'
        current_user_id = actor['id']
        admin_branch_limited = is_admin and int(actor['can_view_all_branches'] or 0) != 1

        requested_trainer_id = request.args.get('trainer_id', type=int)
        requested_batch_id = request.args.get('batch_id', type=int)
        requested_program_id = request.args.get('program_id', type=int)

        # Role enforcement: staff/trainer can only view their own data.
        selected_trainer_id = requested_trainer_id if is_admin else current_user_id
        selected_batch_id = requested_batch_id
        selected_program_id = requested_program_id

        # Trainer list for dropdown.
        if is_admin:
            trainers = conn.execute(
                """
                SELECT u.id, u.full_name
                FROM users u
                WHERE u.role = 'staff' AND u.is_active = 1
                  AND (? = 0 OR u.branch_id = ?)
                ORDER BY u.full_name
                """,
                (1 if admin_branch_limited else 0, actor['branch_id'])
            ).fetchall()
        else:
            trainers = conn.execute(
                """
                SELECT u.id, u.full_name
                FROM users u
                WHERE u.id = ? AND u.role = 'staff' AND u.is_active = 1
                """,
                (current_user_id,)
            ).fetchall()

        if selected_trainer_id and selected_trainer_id not in {row['id'] for row in trainers}:
            selected_trainer_id = None

        programs = conn.execute(
            """
            SELECT lp.id, lp.program_name, c.course_name
            FROM lms_programs lp
            LEFT JOIN courses c ON c.id = lp.course_id
            WHERE lp.is_active = 1
              AND lp.is_deleted = 0
              AND EXISTS (
                  SELECT 1
                  FROM lms_program_chapters pc
                  WHERE pc.program_id = lp.id
                    AND pc.is_visible = 1
              )
            ORDER BY lp.program_name
            """
        ).fetchall()

        if selected_program_id:
            valid_program = conn.execute(
                """
                SELECT 1
                FROM lms_programs lp
                WHERE lp.id = ?
                  AND lp.is_active = 1
                  AND lp.is_deleted = 0
                  AND EXISTS (
                      SELECT 1
                      FROM lms_program_chapters pc
                      WHERE pc.program_id = lp.id
                        AND pc.is_visible = 1
                  )
                """,
                (selected_program_id,)
            ).fetchone()
            if not valid_program:
                selected_program_id = None

        # Active batch dropdown data, narrowed by trainer and selected program.
        # For assignment review, program scope is based on submitted assignments
        # tied to that program's linked master chapters, not batch-program access.
        batch_where = ["LOWER(COALESCE(b.status, '')) = 'active'"]
        batch_params = []
        if admin_branch_limited:
            batch_where.append("b.branch_id = ?")
            batch_params.append(actor['branch_id'])
        if selected_program_id:
            batch_where.append("""
                EXISTS (
                    SELECT 1
                    FROM student_batches sbp
                    JOIN lms_assignment_submissions subp ON subp.student_id = sbp.student_id
                    JOIN lms_assignments ap ON ap.id = subp.assignment_id
                    JOIN lms_master_topics mtp ON mtp.id = ap.master_topic_id
                    JOIN lms_program_chapters pcp
                      ON pcp.master_chapter_id = mtp.master_chapter_id
                     AND pcp.program_id = ?
                     AND pcp.is_visible = 1
                    WHERE sbp.batch_id = b.id
                      AND sbp.status = 'active'
                )
            """)
            batch_params.append(selected_program_id)
        if selected_trainer_id:
            batch_where.append("b.trainer_id = ?")
            batch_params.append(selected_trainer_id)

        active_batches = conn.execute(
            f"""
            SELECT DISTINCT b.id, b.batch_name
            FROM batches b
            WHERE {' AND '.join(batch_where)}
            ORDER BY b.batch_name
            """,
            tuple(batch_params)
        ).fetchall()

        # Validate batch scope. If invalid for current trainer scope, ignore safely.
        if selected_batch_id:
            valid_batch_where = ["b.id = ?", "LOWER(COALESCE(b.status, '')) = 'active'"]
            valid_batch_params = [selected_batch_id]
            if admin_branch_limited:
                valid_batch_where.append("b.branch_id = ?")
                valid_batch_params.append(actor['branch_id'])
            if selected_program_id:
                valid_batch_where.append("""
                    EXISTS (
                        SELECT 1
                        FROM student_batches sbp
                        JOIN lms_assignment_submissions subp ON subp.student_id = sbp.student_id
                        JOIN lms_assignments ap ON ap.id = subp.assignment_id
                        JOIN lms_master_topics mtp ON mtp.id = ap.master_topic_id
                        JOIN lms_program_chapters pcp
                          ON pcp.master_chapter_id = mtp.master_chapter_id
                         AND pcp.program_id = ?
                         AND pcp.is_visible = 1
                        WHERE sbp.batch_id = b.id
                          AND sbp.status = 'active'
                    )
                """)
                valid_batch_params.append(selected_program_id)
            if selected_trainer_id:
                valid_batch_where.append("b.trainer_id = ?")
                valid_batch_params.append(selected_trainer_id)

            valid_batch = conn.execute(
                f"""
                SELECT 1
                FROM batches b
                WHERE {' AND '.join(valid_batch_where)}
                """,
                tuple(valid_batch_params)
            ).fetchone()
            if not valid_batch:
                selected_batch_id = None
            elif admin_branch_limited:
                branch_batch = conn.execute(
                    "SELECT 1 FROM batches WHERE id = ? AND branch_id = ?",
                    (selected_batch_id, actor['branch_id'])
                ).fetchone()
                if not branch_batch:
                    selected_batch_id = None

        has_scope_filter = bool(selected_trainer_id or selected_batch_id or admin_branch_limited)
        program_join = ""
        program_params = []
        if selected_program_id:
            program_join = """
                JOIN lms_program_chapters pc_filter
                  ON pc_filter.master_chapter_id = mt.master_chapter_id
                 AND pc_filter.program_id = ?
                 AND pc_filter.is_visible = 1
            """
            program_params.append(selected_program_id)

        cte_sql = ""
        base_params = []
        if has_scope_filter:
            scope_where = [
                "sb.status = 'active'",
                "LOWER(COALESCE(b.status, '')) = 'active'",
            ]
            scope_params = []
            if admin_branch_limited:
                scope_where.append("b.branch_id = ?")
                scope_params.append(actor['branch_id'])
            if selected_trainer_id:
                scope_where.append("b.trainer_id = ?")
                scope_params.append(selected_trainer_id)
            if selected_batch_id:
                scope_where.append("sb.batch_id = ?")
                scope_params.append(selected_batch_id)

            scope_sql = " AND ".join(scope_where)
            cte_sql = f"""
                WITH scoped_submissions AS (
                    SELECT DISTINCT s.id, s.assignment_id,
                           COALESCE(s.review_status, 'submitted') AS review_status
                    FROM lms_assignment_submissions s
                    JOIN student_batches sb ON sb.student_id = s.student_id
                    JOIN batches b ON b.id = sb.batch_id
                    WHERE s.is_latest = 1
                      AND {scope_sql}
                ),
                assignment_counts AS (
                    SELECT
                        ss.assignment_id,
                        COUNT(*) AS submission_count,
                        SUM(CASE WHEN ss.review_status IN ('accepted', 'rejected') THEN 1 ELSE 0 END) AS reviewed_count,
                        SUM(CASE WHEN ss.review_status = 'submitted' THEN 1 ELSE 0 END) AS pending_count
                    FROM scoped_submissions ss
                    GROUP BY ss.assignment_id
                )
            """
            base_sql = f"""
                SELECT
                    a.id,
                    a.title,
                    a.description,
                    a.original_filename,
                    a.master_topic_id,
                    a.created_at,
                    mt.title AS topic_title,
                    mc.title AS chapter_title,
                    strftime('%d %b %Y', a.created_at) AS created_date,
                    ac.submission_count,
                    ac.reviewed_count,
                    ac.pending_count
                FROM lms_assignments a
                JOIN lms_master_topics mt ON mt.id = a.master_topic_id
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                {program_join}
                JOIN assignment_counts ac ON ac.assignment_id = a.id
            """
            base_params = scope_params + program_params
        else:
            base_sql = f"""
                SELECT
                    a.id,
                    a.title,
                    a.description,
                    a.original_filename,
                    a.master_topic_id,
                    a.created_at,
                    mt.title   AS topic_title,
                    mc.title   AS chapter_title,
                    strftime('%d %b %Y', a.created_at) AS created_date,
                    (SELECT COUNT(*)
                     FROM lms_assignment_submissions s
                     WHERE s.assignment_id = a.id
                       AND s.is_latest = 1) AS submission_count,
                    (SELECT COUNT(*)
                     FROM lms_assignment_submissions s
                     WHERE s.assignment_id = a.id
                       AND s.is_latest = 1
                       AND COALESCE(s.review_status, 'submitted') IN ('accepted', 'rejected')) AS reviewed_count,
                    (SELECT COUNT(*)
                     FROM lms_assignment_submissions s
                     WHERE s.assignment_id = a.id
                       AND s.is_latest = 1
                       AND COALESCE(s.review_status, 'submitted') = 'submitted') AS pending_count
                FROM lms_assignments a
                JOIN lms_master_topics   mt ON mt.id = a.master_topic_id
                JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
                {program_join}
            """
            base_params = program_params

        review_filter = (request.args.get('review_filter') or 'all').strip().lower()
        if review_filter not in {'all', 'submissions', 'pending', 'reviewed'}:
            review_filter = 'all'

        search_query = (request.args.get('q') or '').strip()[:100]
        date_from = (request.args.get('date_from') or '').strip()
        date_to = (request.args.get('date_to') or '').strip()
        for value_name, value in (('date_from', date_from), ('date_to', date_to)):
            if value:
                try:
                    datetime.strptime(value, '%Y-%m-%d')
                except ValueError:
                    if value_name == 'date_from':
                        date_from = ''
                    else:
                        date_to = ''

        page = max(request.args.get('page', 1, type=int) or 1, 1)
        per_page = request.args.get('per_page', 25, type=int) or 25
        if per_page not in {25, 50, 100}:
            per_page = 25
        sort_key = (request.args.get('sort') or 'context').strip().lower()
        sort_direction = (request.args.get('direction') or 'asc').strip().lower()
        if sort_direction not in {'asc', 'desc'}:
            sort_direction = 'asc'
        sort_columns = {
            'context': 'q.chapter_title, q.topic_title, q.id',
            'title': 'q.title',
            'created': 'q.created_at',
            'submissions': 'q.submission_count',
            'pending': 'q.pending_count',
            'reviewed': 'q.reviewed_count',
        }
        if sort_key not in sort_columns:
            sort_key = 'context'

        common_where = ['1 = 1']
        common_params = []
        if search_query:
            like = f"%{search_query}%"
            common_where.append('(q.title LIKE ? OR q.chapter_title LIKE ? OR q.topic_title LIKE ?)')
            common_params.extend([like, like, like])
        if date_from:
            common_where.append('DATE(q.created_at) >= ?')
            common_params.append(date_from)
        if date_to:
            common_where.append('DATE(q.created_at) <= ?')
            common_params.append(date_to)

        common_where_sql = ' AND '.join(common_where)
        summary = conn.execute(
            f"""{cte_sql}
                SELECT COUNT(*) AS assignments,
                       COALESCE(SUM(q.submission_count), 0) AS submissions,
                       COALESCE(SUM(q.reviewed_count), 0) AS reviewed,
                       COALESCE(SUM(q.pending_count), 0) AS pending
                FROM ({base_sql}) q
                WHERE {common_where_sql}
            """,
            tuple(base_params + common_params),
        ).fetchone()
        assignment_summary = {
            'assignments': int(summary['assignments'] or 0),
            'submissions': int(summary['submissions'] or 0),
            'reviewed': int(summary['reviewed'] or 0),
            'pending': int(summary['pending'] or 0),
        }

        result_where = list(common_where)
        result_params = list(common_params)
        if review_filter == 'submissions':
            result_where.append('q.submission_count > 0')
        elif review_filter == 'pending':
            result_where.append('q.pending_count > 0')
        elif review_filter == 'reviewed':
            result_where.append('q.reviewed_count > 0')
        result_where_sql = ' AND '.join(result_where)
        filtered_total = conn.execute(
            f"""{cte_sql}
                SELECT COUNT(*) AS n FROM ({base_sql}) q
                WHERE {result_where_sql}
            """,
            tuple(base_params + result_params),
        ).fetchone()['n']
        total_pages = max((int(filtered_total) + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        direction_sql = 'DESC' if sort_direction == 'desc' else 'ASC'
        if sort_key == 'context':
            order_sql = (
                f"q.chapter_title {direction_sql}, q.topic_title {direction_sql}, q.id {direction_sql}"
            )
        else:
            order_sql = f"{sort_columns[sort_key]} {direction_sql}, q.id DESC"
        assignments = conn.execute(
            f"""{cte_sql}
                SELECT q.* FROM ({base_sql}) q
                WHERE {result_where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
            """,
            tuple(base_params + result_params + [per_page, offset]),
        ).fetchall()

        pagination = {
            'page': page,
            'per_page': per_page,
            'total': int(filtered_total),
            'total_pages': total_pages,
            'start': offset + 1 if filtered_total else 0,
            'end': min(offset + per_page, int(filtered_total)),
        }

        return render_template(
            'lms_admin/lms_all_assignments.html',
            assignments=assignments,
            assignment_summary=assignment_summary,
            review_filter=review_filter,
            search_query=search_query,
            date_from=date_from,
            date_to=date_to,
            sort_key=sort_key,
            sort_direction=sort_direction,
            pagination=pagination,
            trainers=trainers,
            active_batches=active_batches,
            programs=programs,
            selected_trainer_id=selected_trainer_id,
            selected_batch_id=selected_batch_id,
            selected_program_id=selected_program_id,
            is_admin=is_admin,
        )
    finally:
        conn.close()


@lms_admin_bp.route('/master/reviews')
@lms_content_manager_required
def review_queue():
    """Centralized, authorized queue of latest assignment submissions."""
    conn = get_conn()
    try:
        actor = _current_lms_actor(conn)
        if not actor:
            abort(403)
        is_admin = actor['role'] == 'admin'
        admin_branch_limited = is_admin and int(actor['can_view_all_branches'] or 0) != 1

        requested_trainer_id = request.args.get('trainer_id', type=int)
        selected_trainer_id = requested_trainer_id if is_admin else actor['id']
        selected_batch_id = request.args.get('batch_id', type=int)
        selected_program_id = request.args.get('program_id', type=int)

        if is_admin:
            trainers = conn.execute(
                """SELECT id, full_name FROM users
                   WHERE role = 'staff' AND is_active = 1
                     AND (? = 0 OR branch_id = ?)
                   ORDER BY full_name""",
                (1 if admin_branch_limited else 0, actor['branch_id']),
            ).fetchall()
            if selected_trainer_id and selected_trainer_id not in {row['id'] for row in trainers}:
                selected_trainer_id = None
        else:
            trainers = conn.execute(
                "SELECT id, full_name FROM users WHERE id = ? AND is_active = 1",
                (actor['id'],),
            ).fetchall()

        batch_where = ["LOWER(COALESCE(status, '')) = 'active'"]
        batch_params = []
        if selected_trainer_id:
            batch_where.append('trainer_id = ?')
            batch_params.append(selected_trainer_id)
        if admin_branch_limited:
            batch_where.append('branch_id = ?')
            batch_params.append(actor['branch_id'])
        active_batches = conn.execute(
            f"SELECT id, batch_name FROM batches WHERE {' AND '.join(batch_where)} ORDER BY batch_name",
            tuple(batch_params),
        ).fetchall()
        if selected_batch_id and selected_batch_id not in {row['id'] for row in active_batches}:
            selected_batch_id = None

        programs = conn.execute(
            """SELECT lp.id, lp.program_name, c.course_name
               FROM lms_programs lp
               LEFT JOIN courses c ON c.id = lp.course_id
               WHERE lp.is_active = 1 AND lp.is_deleted = 0
               ORDER BY lp.program_name"""
        ).fetchall()
        if selected_program_id and selected_program_id not in {row['id'] for row in programs}:
            selected_program_id = None

        scope_where = ['s.is_latest = 1']
        scope_params = []
        if selected_trainer_id:
            scope_where.append("""EXISTS (
                SELECT 1 FROM student_batches sb_scope
                JOIN batches b_scope ON b_scope.id = sb_scope.batch_id
                WHERE sb_scope.student_id = s.student_id
                  AND sb_scope.status = 'active'
                  AND LOWER(COALESCE(b_scope.status, '')) = 'active'
                  AND b_scope.trainer_id = ?
            )""")
            scope_params.append(selected_trainer_id)
        if selected_batch_id:
            scope_where.append("""EXISTS (
                SELECT 1 FROM student_batches sb_scope
                JOIN batches b_scope ON b_scope.id = sb_scope.batch_id
                WHERE sb_scope.student_id = s.student_id
                  AND sb_scope.status = 'active'
                  AND LOWER(COALESCE(b_scope.status, '')) = 'active'
                  AND b_scope.id = ?
            )""")
            scope_params.append(selected_batch_id)
        if admin_branch_limited:
            scope_where.append("""(
                st.branch_id = ? OR EXISTS (
                    SELECT 1 FROM student_batches sb_scope
                    JOIN batches b_scope ON b_scope.id = sb_scope.batch_id
                    WHERE sb_scope.student_id = s.student_id
                      AND sb_scope.status = 'active'
                      AND LOWER(COALESCE(b_scope.status, '')) = 'active'
                      AND b_scope.branch_id = ?
                )
            )""")
            scope_params.extend([actor['branch_id'], actor['branch_id']])
        if selected_program_id:
            scope_where.append("""EXISTS (
                SELECT 1 FROM lms_program_chapters pc_scope
                WHERE pc_scope.master_chapter_id = mt.master_chapter_id
                  AND pc_scope.program_id = ? AND pc_scope.is_visible = 1
            )""")
            scope_params.append(selected_program_id)

        base_sql = f"""
            SELECT s.id, s.assignment_id, s.student_id, s.original_filename,
                   s.feedback, s.rejection_reason, s.review_status, s.submitted_at,
                   DATE_FORMAT(
                       DATE_ADD(s.submitted_at, INTERVAL 330 MINUTE),
                       '%d-%b-%Y %h:%i %p IST'
                   ) AS submitted_date,
                   a.title AS assignment_title, mt.title AS topic_title,
                   mc.title AS chapter_title, st.full_name AS student_name,
                   st.student_code,
                   (SELECT GROUP_CONCAT(DISTINCT b_names.batch_name ORDER BY b_names.batch_name SEPARATOR ', ')
                    FROM student_batches sb_names
                    JOIN batches b_names ON b_names.id = sb_names.batch_id
                    WHERE sb_names.student_id = s.student_id AND sb_names.status = 'active') AS batch_names,
                   (SELECT GROUP_CONCAT(DISTINCT u_names.full_name ORDER BY u_names.full_name SEPARATOR ', ')
                    FROM student_batches sb_names
                    JOIN batches b_names ON b_names.id = sb_names.batch_id
                    JOIN users u_names ON u_names.id = b_names.trainer_id
                    WHERE sb_names.student_id = s.student_id AND sb_names.status = 'active') AS trainer_names,
                   (SELECT GROUP_CONCAT(DISTINCT lp_names.program_name ORDER BY lp_names.program_name SEPARATOR ', ')
                    FROM lms_program_chapters pc_names
                    JOIN lms_programs lp_names ON lp_names.id = pc_names.program_id
                    WHERE pc_names.master_chapter_id = mt.master_chapter_id
                      AND pc_names.is_visible = 1 AND lp_names.is_active = 1) AS program_names
            FROM lms_assignment_submissions s
            JOIN lms_assignments a ON a.id = s.assignment_id
            JOIN lms_master_topics mt ON mt.id = a.master_topic_id
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
            JOIN students st ON st.id = s.student_id
            WHERE {' AND '.join(scope_where)}
        """

        status_filter = (request.args.get('status_filter') or 'submitted').strip().lower()
        if status_filter not in {'all', 'submitted', 'reviewed', 'accepted', 'rejected'}:
            status_filter = 'submitted'
        search_query = (request.args.get('q') or '').strip()[:100]
        date_from = (request.args.get('date_from') or '').strip()
        date_to = (request.args.get('date_to') or '').strip()
        for value_name, value in (('date_from', date_from), ('date_to', date_to)):
            if value:
                try:
                    datetime.strptime(value, '%Y-%m-%d')
                except ValueError:
                    if value_name == 'date_from': date_from = ''
                    else: date_to = ''
        page = max(request.args.get('page', 1, type=int) or 1, 1)
        per_page = request.args.get('per_page', 25, type=int) or 25
        if per_page not in {25, 50, 100}: per_page = 25
        sort_key = (request.args.get('sort') or 'submitted').strip().lower()
        sort_direction = (request.args.get('direction') or ('asc' if status_filter == 'submitted' else 'desc')).strip().lower()
        if sort_direction not in {'asc', 'desc'}: sort_direction = 'asc' if status_filter == 'submitted' else 'desc'
        sort_columns = {'submitted': 'q.submitted_at', 'student': 'q.student_name', 'assignment': 'q.assignment_title', 'status': 'q.review_status'}
        if sort_key not in sort_columns: sort_key = 'submitted'

        common_where = ['1 = 1']
        common_params = []
        if search_query:
            like = f"%{search_query}%"
            common_where.append('(q.student_name LIKE ? OR q.student_code LIKE ? OR q.assignment_title LIKE ? OR q.original_filename LIKE ?)')
            common_params.extend([like, like, like, like])
        if date_from:
            common_where.append('DATE(q.submitted_at) >= ?'); common_params.append(date_from)
        if date_to:
            common_where.append('DATE(q.submitted_at) <= ?'); common_params.append(date_to)
        common_where_sql = ' AND '.join(common_where)
        summary = conn.execute(
            f"""SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN COALESCE(q.review_status, 'submitted') = 'submitted' THEN 1 ELSE 0 END), 0) AS pending,
                       COALESCE(SUM(CASE WHEN q.review_status = 'accepted' THEN 1 ELSE 0 END), 0) AS accepted,
                       COALESCE(SUM(CASE WHEN q.review_status = 'rejected' THEN 1 ELSE 0 END), 0) AS rejected
                FROM ({base_sql}) q WHERE {common_where_sql}""",
            tuple(scope_params + common_params),
        ).fetchone()
        queue_summary = {key: int(summary[key] or 0) for key in ('total', 'pending', 'accepted', 'rejected')}
        workload = {}
        for key, column_name in (
            ('trainers', 'trainer_names'), ('batches', 'batch_names'), ('programs', 'program_names')
        ):
            workload[key] = conn.execute(
                f"""SELECT COALESCE(NULLIF(q.{column_name}, ''), 'Unassigned') AS label,
                           COUNT(*) AS pending_count
                    FROM ({base_sql}) q
                    WHERE {common_where_sql}
                      AND COALESCE(q.review_status, 'submitted') = 'submitted'
                    GROUP BY q.{column_name}
                    ORDER BY pending_count DESC, label
                    LIMIT 8""",
                tuple(scope_params + common_params),
            ).fetchall()

        result_where = list(common_where)
        result_params = list(common_params)
        if status_filter == 'reviewed': result_where.append("q.review_status IN ('accepted', 'rejected')")
        elif status_filter != 'all':
            result_where.append("COALESCE(q.review_status, 'submitted') = ?"); result_params.append(status_filter)
        result_where_sql = ' AND '.join(result_where)
        filtered_total = int(conn.execute(
            f"SELECT COUNT(*) AS n FROM ({base_sql}) q WHERE {result_where_sql}",
            tuple(scope_params + result_params),
        ).fetchone()['n'])
        total_pages = max((filtered_total + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        direction_sql = 'DESC' if sort_direction == 'desc' else 'ASC'
        submissions = conn.execute(
            f"""SELECT q.* FROM ({base_sql}) q WHERE {result_where_sql}
                ORDER BY {sort_columns[sort_key]} {direction_sql}, q.id {direction_sql}
                LIMIT ? OFFSET ?""",
            tuple(scope_params + result_params + [per_page, offset]),
        ).fetchall()
        pagination = {'page': page, 'per_page': per_page, 'total': filtered_total, 'total_pages': total_pages,
                      'start': offset + 1 if filtered_total else 0, 'end': min(offset + per_page, filtered_total)}

        return render_template(
            'lms_admin/lms_review_queue.html', submissions=submissions,
            queue_summary=queue_summary, trainers=trainers, active_batches=active_batches,
            programs=programs, selected_trainer_id=selected_trainer_id,
            selected_batch_id=selected_batch_id, selected_program_id=selected_program_id,
            status_filter=status_filter, search_query=search_query,
            date_from=date_from, date_to=date_to, sort_key=sort_key,
            sort_direction=sort_direction, pagination=pagination, is_admin=is_admin,
            workload=workload,
        )
    finally:
        conn.close()


def _review_queue_return_args(source):
    """Read and validate queue context from query args or prefixed form fields."""
    prefix = 'return_' if source is request.form else ''
    args = {}
    for key in ('trainer_id', 'batch_id', 'program_id'):
        value = (source.get(f'{prefix}{key}') or '').strip()
        if value.isdigit():
            args[key] = int(value)
    status_filter = (source.get(f'{prefix}status_filter') or '').strip().lower()
    if status_filter in {'all', 'submitted', 'reviewed', 'accepted', 'rejected'}:
        args['status_filter'] = status_filter
    query = (source.get(f'{prefix}q') or '').strip()[:100]
    if query:
        args['q'] = query
    for key in ('date_from', 'date_to'):
        value = (source.get(f'{prefix}{key}') or '').strip()
        try:
            if value:
                datetime.strptime(value, '%Y-%m-%d')
                args[key] = value
        except ValueError:
            pass
    sort = (source.get(f'{prefix}sort') or '').strip().lower()
    direction = (source.get(f'{prefix}direction') or '').strip().lower()
    per_page = (source.get(f'{prefix}per_page') or '').strip()
    page = (source.get(f'{prefix}page') or '').strip()
    if sort in {'submitted', 'student', 'assignment', 'status'}:
        args['sort'] = sort
    if direction in {'asc', 'desc'}:
        args['direction'] = direction
    if per_page in {'25', '50', '100'}:
        args['per_page'] = int(per_page)
    if page.isdigit() and int(page) > 1:
        args['page'] = int(page)
    return args


@lms_admin_bp.route('/master/reviews/<int:submission_id>')
@lms_content_manager_required
def review_submission_detail(submission_id):
    """Preview and decide a submission without leaving the authorized queue."""
    conn = get_conn()
    try:
        actor = _current_lms_actor(conn)
        if not actor:
            abort(403)
        _require_submission_access(conn, submission_id)
        sub = conn.execute(
            """
            SELECT s.id, s.assignment_id, s.student_id, s.file_path,
                   s.original_filename, s.feedback, s.rejection_reason,
                   s.is_latest, COALESCE(s.review_status, 'submitted') AS review_status,
                   s.score, s.is_late, s.graded_at, s.internal_reviewer_notes,
                   s.reviewed_by, reviewer.full_name AS reviewed_by_name,
                   s.submitted_at, s.reviewed_at,
                   a.title AS assignment_title, a.description AS assignment_description,
                   a.due_at, a.max_score, a.passing_score, a.grading_mode,
                   a.rubric_id, a.completion_rule, a.allow_late_submission,
                   a.max_attempts, a.is_required,
                   mt.title AS topic_title, mc.title AS chapter_title,
                   st.full_name AS student_name, st.student_code
            FROM lms_assignment_submissions s
            JOIN lms_assignments a ON a.id = s.assignment_id
            JOIN lms_master_topics mt ON mt.id = a.master_topic_id
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
            JOIN students st ON st.id = s.student_id
            LEFT JOIN users reviewer ON reviewer.id = s.reviewed_by
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()
        if not sub:
            abort(404)

        attempts = conn.execute(
            """
            SELECT s.id, s.original_filename, s.feedback, s.rejection_reason,
                   s.is_latest, COALESCE(s.review_status, 'submitted') AS review_status,
                   s.score, s.is_late, s.graded_at,
                   s.reviewed_by, reviewer.full_name AS reviewed_by_name,
                   s.submitted_at, s.reviewed_at,
                   ROW_NUMBER() OVER (ORDER BY s.submitted_at, s.id) AS attempt_number
            FROM lms_assignment_submissions s
            LEFT JOIN users reviewer ON reviewer.id = s.reviewed_by
            WHERE s.assignment_id = ? AND s.student_id = ?
            ORDER BY s.submitted_at DESC, s.id DESC
            """,
            (sub['assignment_id'], sub['student_id']),
        ).fetchall()
        rubric_criteria = []
        if sub['rubric_id']:
            rubric_criteria = conn.execute(
                """SELECT rc.id, rc.criterion_name, rc.description, rc.max_score,
                          rs.score, rs.comment
                   FROM lms_rubric_criteria rc
                   LEFT JOIN lms_submission_rubric_scores rs
                     ON rs.criterion_id = rc.id AND rs.submission_id = ?
                   WHERE rc.rubric_id = ? ORDER BY rc.display_order, rc.id""",
                (submission_id, sub['rubric_id']),
            ).fetchall()

        queue_args = _review_queue_return_args(request.args)
        is_admin = actor['role'] == 'admin'
        selected_trainer_id = queue_args.get('trainer_id') if is_admin else actor['id']
        admin_branch_limited = is_admin and int(actor['can_view_all_branches'] or 0) != 1

        scope_where = ["s.is_latest = 1", "COALESCE(s.review_status, 'submitted') = 'submitted'"]
        scope_params = []
        if selected_trainer_id:
            scope_where.append("""EXISTS (SELECT 1 FROM student_batches sb JOIN batches b ON b.id = sb.batch_id
                WHERE sb.student_id = s.student_id AND sb.status = 'active'
                  AND LOWER(COALESCE(b.status, '')) = 'active' AND b.trainer_id = ?)""")
            scope_params.append(selected_trainer_id)
        if queue_args.get('batch_id'):
            scope_where.append("""EXISTS (SELECT 1 FROM student_batches sb JOIN batches b ON b.id = sb.batch_id
                WHERE sb.student_id = s.student_id AND sb.status = 'active'
                  AND LOWER(COALESCE(b.status, '')) = 'active' AND b.id = ?)""")
            scope_params.append(queue_args['batch_id'])
        if admin_branch_limited:
            scope_where.append("""(st.branch_id = ? OR EXISTS (SELECT 1 FROM student_batches sb
                JOIN batches b ON b.id = sb.batch_id WHERE sb.student_id = s.student_id
                  AND sb.status = 'active' AND LOWER(COALESCE(b.status, '')) = 'active' AND b.branch_id = ?))""")
            scope_params.extend([actor['branch_id'], actor['branch_id']])
        if queue_args.get('program_id'):
            scope_where.append("""EXISTS (SELECT 1 FROM lms_program_chapters pc
                WHERE pc.master_chapter_id = mt.master_chapter_id
                  AND pc.program_id = ? AND pc.is_visible = 1)""")
            scope_params.append(queue_args['program_id'])
        if queue_args.get('q'):
            like = f"%{queue_args['q']}%"
            scope_where.append('(st.full_name LIKE ? OR st.student_code LIKE ? OR a.title LIKE ? OR s.original_filename LIKE ?)')
            scope_params.extend([like, like, like, like])
        if queue_args.get('date_from'):
            scope_where.append('DATE(s.submitted_at) >= ?')
            scope_params.append(queue_args['date_from'])
        if queue_args.get('date_to'):
            scope_where.append('DATE(s.submitted_at) <= ?')
            scope_params.append(queue_args['date_to'])

        sort_key = queue_args.get('sort', 'submitted')
        direction = queue_args.get('direction', 'asc')
        sort_columns = {'submitted': 's.submitted_at', 'student': 'st.full_name',
                        'assignment': 'a.title', 'status': 's.review_status'}
        direction_sql = 'DESC' if direction == 'desc' else 'ASC'
        pending_rows = conn.execute(
            f"""SELECT s.id FROM lms_assignment_submissions s
                JOIN lms_assignments a ON a.id = s.assignment_id
                JOIN lms_master_topics mt ON mt.id = a.master_topic_id
                JOIN students st ON st.id = s.student_id
                WHERE {' AND '.join(scope_where)}
                ORDER BY {sort_columns[sort_key]} {direction_sql}, s.id {direction_sql}""",
            tuple(scope_params),
        ).fetchall()
        pending_ids = [int(row['id']) for row in pending_rows]
        previous_id = next_id = None
        if submission_id in pending_ids:
            position = pending_ids.index(submission_id)
            if position > 0:
                previous_id = pending_ids[position - 1]
            if position + 1 < len(pending_ids):
                next_id = pending_ids[position + 1]

        orig = sub['original_filename'] or sub['file_path'] or 'submission'
        ext = orig.rsplit('.', 1)[-1].lower() if '.' in orig else ''
        image_exts = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        office_exts = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
        is_localhost = request.host.startswith(('localhost', '127.', '0.0.0.0'))
        preview_type = preview_url = None
        if ext == 'pdf':
            preview_type = 'pdf'
            preview_url = url_for('lms_admin.admin_download_submission', submission_id=submission_id, inline=1)
        elif ext in image_exts:
            preview_type = 'image'
            preview_url = url_for('lms_admin.admin_download_submission', submission_id=submission_id, inline=1)
        elif ext in office_exts:
            preview_type = 'office'
            if not is_localhost:
                token = _make_submission_preview_token(submission_id)
                public_url = url_for('lms_admin.preview_submission_public_file', token=token, _external=True)
                preview_url = 'https://view.officeapps.live.com/op/embed.aspx?src=' + quote(public_url, safe='')

        return render_template(
            'lms_admin/lms_assignment_review_detail.html', sub=sub,
            queue_args=queue_args, previous_id=previous_id, next_id=next_id,
            pending_position=(pending_ids.index(submission_id) + 1 if submission_id in pending_ids else None),
            pending_total=len(pending_ids), preview_type=preview_type,
            preview_url=preview_url, download_url=url_for('lms_admin.admin_download_submission', submission_id=submission_id),
            is_localhost=is_localhost, office_exts=office_exts, orig_filename=orig,
            attempts=attempts,
            rubric_criteria=rubric_criteria,
        )
    finally:
        conn.close()


@lms_admin_bp.route('/master/topic/<int:master_topic_id>/assignments', methods=['GET', 'POST'])
@lms_content_manager_required
def manage_assignments(master_topic_id):
    conn = get_conn()
    try:
        topic = conn.execute("""
            SELECT mt.id, mt.title, mc.id AS chapter_id, mc.title AS chapter_title
            FROM   lms_master_topics mt
            JOIN   lms_master_chapters mc ON mc.id = mt.master_chapter_id
            WHERE  mt.id = ?
        """, (master_topic_id,)).fetchone()
        if not topic:
            flash('Topic not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        if request.method == 'POST':
            title       = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            file_obj    = request.files.get('assignment_file')

            if not title:
                flash('Title is required.', 'danger')
                return redirect(url_for('lms_admin.manage_assignments', master_topic_id=master_topic_id))

            description_ok, description_error = _validate_assignment_description(description)
            if not description_ok:
                flash(description_error, 'danger')
                return redirect(url_for('lms_admin.manage_assignments', master_topic_id=master_topic_id))

            grading, grading_error = _parse_assignment_grading_settings(conn)
            if grading_error:
                flash(grading_error, 'danger')
                return redirect(url_for('lms_admin.manage_assignments', master_topic_id=master_topic_id))

            file_path = None
            orig_name = None
            if file_obj and file_obj.filename:
                ok, path_or_err, orig = _save_assignment_file(file_obj)
                if not ok:
                    flash(f'File error: {path_or_err}', 'danger')
                    return redirect(url_for('lms_admin.manage_assignments', master_topic_id=master_topic_id))
                file_path = path_or_err
                orig_name = orig

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("""
                INSERT INTO lms_assignments
                    (master_topic_id, title, description, file_path, original_filename, uploaded_by, created_at, updated_at,
                     due_at, max_score, passing_score, grading_mode, rubric_id, completion_rule,
                     allow_late_submission, max_attempts, is_required)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (master_topic_id, title, description or None,
                  file_path, orig_name, session.get('user_id'), now, now,
                  grading['due_at'], grading['max_score'], grading['passing_score'],
                  grading['grading_mode'], grading['rubric_id'], grading['completion_rule'],
                  grading['allow_late_submission'], grading['max_attempts'], grading['is_required']))
            conn.commit()
            log_activity(
                user_id=session['user_id'], branch_id=session.get('branch_id'),
                action_type='create', module_name='lms_assignments', record_id=None,
                description=f"Created assignment '{title}' for master topic {master_topic_id}"
            )
            flash('Assignment created.', 'success')
            return redirect(url_for('lms_admin.manage_assignments', master_topic_id=master_topic_id))

        assignments = conn.execute("""
            SELECT a.id, a.title, a.description, a.original_filename, a.file_path,
                   strftime('%d %b %Y', a.created_at) AS created_date,
                   (SELECT COUNT(*) FROM lms_assignment_submissions s
                    WHERE s.assignment_id = a.id AND s.is_latest = 1) AS submission_count,
                   (SELECT COUNT(*) FROM lms_assignment_submissions s
                    WHERE s.assignment_id = a.id AND s.is_latest = 1
                      AND COALESCE(s.review_status, 'submitted') IN ('accepted', 'rejected')) AS reviewed_count,
                   (SELECT COUNT(*) FROM lms_assignment_submissions s
                    WHERE s.assignment_id = a.id AND s.is_latest = 1
                      AND COALESCE(s.review_status, 'submitted') = 'submitted') AS pending_count
            FROM   lms_assignments a
            WHERE  a.master_topic_id = ?
            ORDER  BY a.created_at
        """, (master_topic_id,)).fetchall()

        rubrics = conn.execute(
            "SELECT id, name FROM lms_rubrics WHERE is_active = 1 ORDER BY name"
        ).fetchall()

        return render_template('lms_admin/lms_assignments.html',
                               topic=topic, assignments=assignments, rubrics=rubrics)
    finally:
        conn.close()


@lms_admin_bp.route('/master/assignments/<int:assignment_id>/edit', methods=['GET', 'POST'])
@lms_content_manager_required
def edit_assignment(assignment_id):
    conn = get_conn()
    try:
        assignment = conn.execute("""
            SELECT a.id, a.master_topic_id, a.title, a.description,
                   a.file_path, a.original_filename,
                   a.due_at, a.max_score, a.passing_score, a.grading_mode,
                   a.rubric_id, a.completion_rule, a.allow_late_submission,
                   a.max_attempts, a.is_required,
                   mt.title AS topic_title,
                   mc.id AS chapter_id, mc.title AS chapter_title
            FROM   lms_assignments a
            JOIN   lms_master_topics mt ON mt.id = a.master_topic_id
            JOIN   lms_master_chapters mc ON mc.id = mt.master_chapter_id
            WHERE  a.id = ?
        """, (assignment_id,)).fetchone()
        if not assignment:
            flash('Assignment not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            file_obj = request.files.get('assignment_file')

            if not title:
                flash('Title is required.', 'danger')
                return redirect(url_for('lms_admin.edit_assignment', assignment_id=assignment_id))

            description_ok, description_error = _validate_assignment_description(description)
            if not description_ok:
                flash(description_error, 'danger')
                return redirect(url_for('lms_admin.edit_assignment', assignment_id=assignment_id))

            grading, grading_error = _parse_assignment_grading_settings(conn)
            if grading_error:
                flash(grading_error, 'danger')
                return redirect(url_for('lms_admin.edit_assignment', assignment_id=assignment_id))

            file_path = assignment['file_path']
            orig_name = assignment['original_filename']
            if file_obj and file_obj.filename:
                ok, path_or_err, orig = _save_assignment_file(file_obj)
                if not ok:
                    flash(f'File error: {path_or_err}', 'danger')
                    return redirect(url_for('lms_admin.edit_assignment', assignment_id=assignment_id))
                file_path = path_or_err
                orig_name = orig

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("""
                UPDATE lms_assignments
                SET    title = ?,
                       description = ?,
                       file_path = ?,
                       original_filename = ?,
                       uploaded_by = ?,
                       updated_at = ?,
                       due_at = ?, max_score = ?, passing_score = ?, grading_mode = ?,
                       rubric_id = ?, completion_rule = ?, allow_late_submission = ?,
                       max_attempts = ?, is_required = ?
                WHERE  id = ?
            """, (
                title,
                description or None,
                file_path,
                orig_name,
                session.get('user_id'),
                now,
                grading['due_at'], grading['max_score'], grading['passing_score'],
                grading['grading_mode'], grading['rubric_id'], grading['completion_rule'],
                grading['allow_late_submission'], grading['max_attempts'], grading['is_required'],
                assignment_id,
            ))
            conn.commit()
            log_activity(
                user_id=session['user_id'], branch_id=session.get('branch_id'),
                action_type='update', module_name='lms_assignments', record_id=assignment_id,
                description=f"Updated assignment '{title}'"
            )
            flash('Assignment updated.', 'success')
            return redirect(url_for('lms_admin.manage_assignments', master_topic_id=assignment['master_topic_id']))

        rubrics = conn.execute(
            "SELECT id, name FROM lms_rubrics WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        return render_template('lms_admin/lms_assignment_edit.html', assignment=assignment, rubrics=rubrics)
    finally:
        conn.close()


@lms_admin_bp.route('/master/assignments/<int:assignment_id>/delete', methods=['POST'])
@lms_content_manager_required
def delete_assignment(assignment_id):
    conn = get_conn()
    try:
        a = conn.execute(
            "SELECT master_topic_id, title FROM lms_assignments WHERE id = ?",
            (assignment_id,)
        ).fetchone()
        if not a:
            flash('Assignment not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))
        conn.execute("DELETE FROM lms_assignments WHERE id = ?", (assignment_id,))
        conn.commit()
        log_activity(
            user_id=session['user_id'], branch_id=session.get('branch_id'),
            action_type='delete', module_name='lms_assignments', record_id=assignment_id,
            description=f"Deleted assignment '{a['title']}'"
        )
        flash('Assignment deleted.', 'success')
        return redirect(url_for('lms_admin.manage_assignments', master_topic_id=a['master_topic_id']))
    finally:
        conn.close()


@lms_admin_bp.route('/master/assignments/<int:assignment_id>/submissions')
@lms_content_manager_required
def view_submissions(assignment_id):
    conn = get_conn()
    try:
        a = conn.execute("""
            SELECT a.id, a.title, a.master_topic_id, mt.title AS topic_title
            FROM   lms_assignments a
            JOIN   lms_master_topics mt ON mt.id = a.master_topic_id
            WHERE  a.id = ?
        """, (assignment_id,)).fetchone()
        if not a:
            flash('Assignment not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))

        actor = _current_lms_actor(conn)
        if not actor:
            abort(403)
        role = actor['role']
        is_admin = role == 'admin'
        current_user_id = actor['id']
        admin_branch_limited = is_admin and int(actor['can_view_all_branches'] or 0) != 1

        requested_trainer_id = request.args.get('trainer_id', type=int)
        selected_trainer_id = requested_trainer_id if is_admin else current_user_id
        selected_batch_id = request.args.get('batch_id', type=int)

        if selected_trainer_id:
            active_batches = conn.execute(
                """
                SELECT id, batch_name
                FROM batches
                WHERE trainer_id = ?
                  AND LOWER(COALESCE(status, '')) = 'active'
                  AND (? = 0 OR branch_id = ?)
                ORDER BY batch_name
                """,
                (selected_trainer_id, 1 if admin_branch_limited else 0, actor['branch_id'])
            ).fetchall()
        else:
            active_batches = conn.execute(
                """
                SELECT id, batch_name
                FROM batches
                WHERE LOWER(COALESCE(status, '')) = 'active'
                  AND (? = 0 OR branch_id = ?)
                ORDER BY batch_name
                """,
                (1 if admin_branch_limited else 0, actor['branch_id'])
            ).fetchall()

        if selected_batch_id:
            if selected_trainer_id:
                valid_batch = conn.execute(
                    """
                    SELECT 1 FROM batches
                    WHERE id = ? AND trainer_id = ?
                      AND LOWER(COALESCE(status, '')) = 'active'
                    """,
                    (selected_batch_id, selected_trainer_id)
                ).fetchone()
            else:
                valid_batch = conn.execute(
                    """
                    SELECT 1 FROM batches
                    WHERE id = ?
                      AND LOWER(COALESCE(status, '')) = 'active'
                    """,
                    (selected_batch_id,)
                ).fetchone()
            if not valid_batch:
                selected_batch_id = None

        if selected_trainer_id or selected_batch_id or admin_branch_limited:
            where_clauses = [
                "s.assignment_id = ?",
                "s.is_latest = 1",
                "sb.status = 'active'",
                "LOWER(COALESCE(b.status, '')) = 'active'",
            ]
            params = [assignment_id]
            if selected_trainer_id:
                where_clauses.append("b.trainer_id = ?")
                params.append(selected_trainer_id)
            if selected_batch_id:
                where_clauses.append("sb.batch_id = ?")
                params.append(selected_batch_id)
            if admin_branch_limited:
                where_clauses.append("(st.branch_id = ? OR b.branch_id = ?)")
                params.extend([actor['branch_id'], actor['branch_id']])

            submissions_base_sql = f"""
                SELECT DISTINCT
                       s.id, s.student_id, s.original_filename, s.feedback,
                       s.status, s.review_status, s.rejection_reason,
                       s.submitted_at,
                       strftime('%d %b %Y %H:%M', s.submitted_at) AS submitted_date,
                       strftime('%d %b %Y %H:%M', s.reviewed_at)  AS reviewed_date,
                       st.full_name AS student_name, st.student_code
                FROM   lms_assignment_submissions s
                JOIN   students st ON st.id = s.student_id
                JOIN   student_batches sb ON sb.student_id = s.student_id
                JOIN   batches b ON b.id = sb.batch_id
                WHERE  {' AND '.join(where_clauses)}
            """
            submissions_base_params = params
        else:
            submissions_base_sql = """
                SELECT s.id, s.student_id, s.original_filename, s.feedback,
                       s.status, s.review_status, s.rejection_reason,
                       s.submitted_at,
                       strftime('%d %b %Y %H:%M', s.submitted_at) AS submitted_date,
                       strftime('%d %b %Y %H:%M', s.reviewed_at)  AS reviewed_date,
                       st.full_name AS student_name, st.student_code
                FROM   lms_assignment_submissions s
                JOIN   students st ON st.id = s.student_id
                WHERE  s.assignment_id = ? AND s.is_latest = 1
            """
            submissions_base_params = [assignment_id]

        status_filter = (request.args.get('status_filter') or 'all').strip().lower()
        if status_filter not in {'all', 'submitted', 'reviewed', 'accepted', 'rejected'}:
            status_filter = 'all'
        search_query = (request.args.get('q') or '').strip()[:100]
        date_from = (request.args.get('date_from') or '').strip()
        date_to = (request.args.get('date_to') or '').strip()
        for value_name, value in (('date_from', date_from), ('date_to', date_to)):
            if value:
                try:
                    datetime.strptime(value, '%Y-%m-%d')
                except ValueError:
                    if value_name == 'date_from':
                        date_from = ''
                    else:
                        date_to = ''
        page = max(request.args.get('page', 1, type=int) or 1, 1)
        per_page = request.args.get('per_page', 25, type=int) or 25
        if per_page not in {25, 50, 100}:
            per_page = 25
        sort_key = (request.args.get('sort') or 'submitted').strip().lower()
        sort_direction = (request.args.get('direction') or 'desc').strip().lower()
        if sort_direction not in {'asc', 'desc'}:
            sort_direction = 'desc'
        submission_sort_columns = {
            'submitted': 'q.submitted_at',
            'student': 'q.student_name',
            'status': 'q.review_status',
        }
        if sort_key not in submission_sort_columns:
            sort_key = 'submitted'

        common_where = ['1 = 1']
        common_params = []
        if search_query:
            like = f"%{search_query}%"
            common_where.append('(q.student_name LIKE ? OR q.student_code LIKE ? OR q.original_filename LIKE ?)')
            common_params.extend([like, like, like])
        if date_from:
            common_where.append('DATE(q.submitted_at) >= ?')
            common_params.append(date_from)
        if date_to:
            common_where.append('DATE(q.submitted_at) <= ?')
            common_params.append(date_to)
        common_where_sql = ' AND '.join(common_where)

        summary = conn.execute(
            f"""SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN COALESCE(q.review_status, 'submitted') = 'submitted' THEN 1 ELSE 0 END), 0) AS pending,
                       COALESCE(SUM(CASE WHEN q.review_status = 'accepted' THEN 1 ELSE 0 END), 0) AS accepted,
                       COALESCE(SUM(CASE WHEN q.review_status = 'rejected' THEN 1 ELSE 0 END), 0) AS rejected
                FROM ({submissions_base_sql}) q
                WHERE {common_where_sql}
            """,
            tuple(submissions_base_params + common_params),
        ).fetchone()
        submission_summary = {key: int(summary[key] or 0) for key in ('total', 'pending', 'accepted', 'rejected')}

        result_where = list(common_where)
        result_params = list(common_params)
        if status_filter == 'reviewed':
            result_where.append("q.review_status IN ('accepted', 'rejected')")
        elif status_filter != 'all':
            result_where.append("COALESCE(q.review_status, 'submitted') = ?")
            result_params.append(status_filter)
        result_where_sql = ' AND '.join(result_where)
        filtered_total = conn.execute(
            f"SELECT COUNT(*) AS n FROM ({submissions_base_sql}) q WHERE {result_where_sql}",
            tuple(submissions_base_params + result_params),
        ).fetchone()['n']
        total_pages = max((int(filtered_total) + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        direction_sql = 'DESC' if sort_direction == 'desc' else 'ASC'
        submissions = conn.execute(
            f"""SELECT q.* FROM ({submissions_base_sql}) q
                WHERE {result_where_sql}
                ORDER BY {submission_sort_columns[sort_key]} {direction_sql}, q.id DESC
                LIMIT ? OFFSET ?
            """,
            tuple(submissions_base_params + result_params + [per_page, offset]),
        ).fetchall()
        pagination = {
            'page': page, 'per_page': per_page, 'total': int(filtered_total),
            'total_pages': total_pages,
            'start': offset + 1 if filtered_total else 0,
            'end': min(offset + per_page, int(filtered_total)),
        }

        return render_template('lms_admin/lms_assignment_submissions.html',
                               assignment=a, submissions=submissions,
                               active_batches=active_batches,
                               selected_batch_id=selected_batch_id,
                               status_filter=status_filter,
                               submission_summary=submission_summary,
                               search_query=search_query,
                               date_from=date_from, date_to=date_to,
                               sort_key=sort_key, sort_direction=sort_direction,
                               pagination=pagination)
    finally:
        conn.close()


def _parse_submission_grade(conn, submission, require_grade):
    """Validate a numeric/rubric grade entirely on the server."""
    mode = submission['grading_mode'] or 'accept_reject'
    max_score = Decimal(str(submission['max_score'])) if submission['max_score'] is not None else None
    score_raw = (request.form.get('score') or '').strip()
    score = None
    if score_raw:
        try:
            score = Decimal(score_raw)
        except InvalidOperation:
            return None, None, 'Score must be a number.'
        if score < 0 or (max_score is not None and score > max_score):
            return None, None, f'Score must be between 0 and {max_score}.'

    rubric_scores = []
    if mode in {'rubric', 'numeric_rubric'}:
        criteria = conn.execute(
            "SELECT id, criterion_name, max_score FROM lms_rubric_criteria WHERE rubric_id = ? ORDER BY display_order, id",
            (submission['rubric_id'],),
        ).fetchall()
        if require_grade and not criteria:
            return None, None, 'The configured rubric has no criteria.'
        rubric_total = Decimal('0')
        for criterion in criteria:
            raw = (request.form.get(f"criterion_{criterion['id']}") or '').strip()
            if not raw:
                if require_grade:
                    return None, None, f"Score is required for rubric criterion: {criterion['criterion_name']}."
                continue
            try:
                value = Decimal(raw)
            except InvalidOperation:
                return None, None, f"Invalid score for rubric criterion: {criterion['criterion_name']}."
            criterion_max = Decimal(str(criterion['max_score']))
            if value < 0 or value > criterion_max:
                return None, None, f"{criterion['criterion_name']} must be between 0 and {criterion_max}."
            rubric_total += value
            rubric_scores.append((criterion['id'], value,
                                  (request.form.get(f"criterion_comment_{criterion['id']}") or '').strip()[:2000]))
        if require_grade:
            if mode == 'rubric':
                score = rubric_total
            elif score is None:
                return None, None, 'Overall score is required for numeric plus rubric grading.'
            elif score != rubric_total:
                return None, None, 'Overall score must equal the total rubric score.'

    if require_grade and mode == 'numeric' and score is None:
        return None, None, 'Score is required for numeric grading.'
    if require_grade and submission['completion_rule'] == 'score_meets_passing_score':
        passing = Decimal(str(submission['passing_score']))
        if score is None or score < passing:
            return None, None, f'An accepted submission must meet the passing score of {passing}. Reject it to allow resubmission.'
    return score, rubric_scores, None


def _save_submission_rubric_scores(conn, submission_id, rubric_scores, now):
    for criterion_id, score, comment in rubric_scores:
        conn.execute(
            """INSERT INTO lms_submission_rubric_scores
                   (submission_id, criterion_id, score, comment, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(submission_id, criterion_id)
               DO UPDATE SET score = ?, comment = ?, updated_at = ?""",
            (submission_id, criterion_id, score, comment or None, now, now,
             score, comment or None, now),
        )


@lms_admin_bp.route('/master/submissions/<int:submission_id>/review', methods=['POST'])
@lms_content_manager_required
def review_submission(submission_id):
    """Legacy route — kept for backward compat, redirects to accept."""
    return accept_submission(submission_id)


@lms_admin_bp.route('/master/submissions/<int:submission_id>/accept', methods=['POST'])
@lms_content_manager_required
def accept_submission(submission_id):
    def _submission_review_redirect(assignment_id, completed=False):
        args = {}
        trainer_id = (request.form.get('return_trainer_id') or '').strip()
        batch_id = (request.form.get('return_batch_id') or '').strip()
        program_id = (request.form.get('return_program_id') or '').strip()
        status_filter = (request.form.get('return_status_filter') or '').strip()
        if trainer_id.isdigit():
            args['trainer_id'] = trainer_id
        if batch_id.isdigit():
            args['batch_id'] = batch_id
        if program_id.isdigit():
            args['program_id'] = program_id
        if status_filter in {'submitted', 'reviewed', 'accepted', 'rejected'}:
            args['status_filter'] = status_filter
        q = (request.form.get('return_q') or '').strip()[:100]
        if q:
            args['q'] = q
        for key in ('date_from', 'date_to'):
            value = (request.form.get(f'return_{key}') or '').strip()
            try:
                if value:
                    datetime.strptime(value, '%Y-%m-%d')
                    args[key] = value
            except ValueError:
                pass
        sort = (request.form.get('return_sort') or '').strip()
        direction = (request.form.get('return_direction') or '').strip()
        per_page = (request.form.get('return_per_page') or '').strip()
        page = (request.form.get('return_page') or '').strip()
        if sort in {'submitted', 'student', 'assignment', 'status'}:
            args['sort'] = sort
        if direction in {'asc', 'desc'}:
            args['direction'] = direction
        if per_page in {'25', '50', '100'}:
            args['per_page'] = per_page
        if page.isdigit() and int(page) > 1:
            args['page'] = page
        if request.form.get('return_queue') == '1':
            next_id = (request.form.get('return_next_id') or '').strip()
            if completed and next_id.isdigit():
                return redirect(url_for('lms_admin.review_submission_detail', submission_id=int(next_id), **args))
            if completed:
                return redirect(url_for('lms_admin.review_queue', **args))
            return redirect(url_for('lms_admin.review_submission_detail', submission_id=submission_id, **args))
        return redirect(url_for('lms_admin.view_submissions', assignment_id=assignment_id, **args))

    conn = get_conn()
    try:
        _require_submission_access(conn, submission_id)
        sub = conn.execute(
            """
            SELECT s.assignment_id,
                   s.student_id,
                   a.master_topic_id,
                   a.grading_mode, a.max_score, a.passing_score,
                   a.rubric_id, a.completion_rule,
                   is_latest,
                   COALESCE(review_status, 'submitted') AS review_status
            FROM lms_assignment_submissions s
            JOIN lms_assignments a ON a.id = s.assignment_id
            WHERE s.id = ?
            """,
            (submission_id,)
        ).fetchone()
        if not sub:
            flash('Submission not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))
        if int(sub['is_latest'] or 0) != 1 or sub['review_status'] != 'submitted':
            flash('Only the latest pending submission can be accepted/rejected.', 'warning')
            return _submission_review_redirect(sub['assignment_id'])
        feedback = request.form.get('feedback', '').strip()
        internal_notes = request.form.get('internal_reviewer_notes', '').strip()[:5000]
        score, rubric_scores, grade_error = _parse_submission_grade(conn, sub, require_grade=True)
        if grade_error:
            flash(grade_error, 'danger')
            return _submission_review_redirect(sub['assignment_id'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute("""
            UPDATE lms_assignment_submissions
            SET    feedback      = ?,
                   status        = 'reviewed',
                   review_status = 'accepted',
                   score          = ?,
                   graded_at      = ?,
                   internal_reviewer_notes = ?,
                   reviewed_by   = ?,
                   reviewed_at   = ?,
                   updated_at    = ?
            WHERE  id = ?
              AND  is_latest = 1
              AND  COALESCE(review_status, 'submitted') = 'submitted'
        """, (feedback or None, score, now if score is not None else None,
              internal_notes or None, session.get('user_id'), now, now, submission_id))
        if cur.rowcount == 0:
            flash('Submission can no longer be reviewed (already processed or replaced).', 'warning')
            return _submission_review_redirect(sub['assignment_id'])

        _save_submission_rubric_scores(conn, submission_id, rubric_scores, now)
        _recalculate_assignment_topic_completion(conn, sub['student_id'], sub['master_topic_id'])

        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='accept',
            module_name='lms_assignment_submissions',
            record_id=submission_id,
            description=f"Accepted assignment submission {submission_id}",
            conn=conn,
        )
        conn.commit()
        flash('Assignment accepted and feedback saved.', 'success')
        return _submission_review_redirect(sub['assignment_id'], completed=True)
    finally:
        conn.close()


@lms_admin_bp.route('/master/submissions/<int:submission_id>/reject', methods=['POST'])
@lms_content_manager_required
def reject_submission(submission_id):
    def _submission_review_redirect(assignment_id, completed=False):
        args = {}
        trainer_id = (request.form.get('return_trainer_id') or '').strip()
        batch_id = (request.form.get('return_batch_id') or '').strip()
        program_id = (request.form.get('return_program_id') or '').strip()
        status_filter = (request.form.get('return_status_filter') or '').strip()
        if trainer_id.isdigit():
            args['trainer_id'] = trainer_id
        if batch_id.isdigit():
            args['batch_id'] = batch_id
        if program_id.isdigit():
            args['program_id'] = program_id
        if status_filter in {'submitted', 'reviewed', 'accepted', 'rejected'}:
            args['status_filter'] = status_filter
        q = (request.form.get('return_q') or '').strip()[:100]
        if q:
            args['q'] = q
        for key in ('date_from', 'date_to'):
            value = (request.form.get(f'return_{key}') or '').strip()
            try:
                if value:
                    datetime.strptime(value, '%Y-%m-%d')
                    args[key] = value
            except ValueError:
                pass
        sort = (request.form.get('return_sort') or '').strip()
        direction = (request.form.get('return_direction') or '').strip()
        per_page = (request.form.get('return_per_page') or '').strip()
        page = (request.form.get('return_page') or '').strip()
        if sort in {'submitted', 'student', 'assignment', 'status'}:
            args['sort'] = sort
        if direction in {'asc', 'desc'}:
            args['direction'] = direction
        if per_page in {'25', '50', '100'}:
            args['per_page'] = per_page
        if page.isdigit() and int(page) > 1:
            args['page'] = page
        if request.form.get('return_queue') == '1':
            next_id = (request.form.get('return_next_id') or '').strip()
            if completed and next_id.isdigit():
                return redirect(url_for('lms_admin.review_submission_detail', submission_id=int(next_id), **args))
            if completed:
                return redirect(url_for('lms_admin.review_queue', **args))
            return redirect(url_for('lms_admin.review_submission_detail', submission_id=submission_id, **args))
        return redirect(url_for('lms_admin.view_submissions', assignment_id=assignment_id, **args))

    conn = get_conn()
    try:
        _require_submission_access(conn, submission_id)
        sub = conn.execute(
            """
            SELECT s.assignment_id, s.student_id, a.master_topic_id,
                   a.grading_mode, a.max_score, a.passing_score,
                   a.rubric_id, a.completion_rule,
                   s.is_latest,
                   COALESCE(s.review_status, 'submitted') AS review_status
            FROM lms_assignment_submissions s
            JOIN lms_assignments a ON a.id = s.assignment_id
            WHERE s.id = ?
            """,
            (submission_id,)
        ).fetchone()
        if not sub:
            flash('Submission not found.', 'danger')
            return redirect(url_for('lms_admin.list_master_chapters'))
        if int(sub['is_latest'] or 0) != 1 or sub['review_status'] != 'submitted':
            flash('Only the latest pending submission can be accepted/rejected.', 'warning')
            return _submission_review_redirect(sub['assignment_id'])
        rejection_reason = request.form.get('rejection_reason', '').strip()
        feedback = request.form.get('feedback', '').strip()
        internal_notes = request.form.get('internal_reviewer_notes', '').strip()[:5000]
        if not rejection_reason:
            flash('Please provide a rejection reason.', 'danger')
            return _submission_review_redirect(sub['assignment_id'])
        score, rubric_scores, grade_error = _parse_submission_grade(conn, sub, require_grade=False)
        if grade_error:
            flash(grade_error, 'danger')
            return _submission_review_redirect(sub['assignment_id'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute("""
            UPDATE lms_assignment_submissions
            SET    feedback         = ?,
                   rejection_reason = ?,
                   status           = 'reviewed',
                   review_status    = 'rejected',
                   score            = ?,
                   graded_at        = ?,
                   internal_reviewer_notes = ?,
                   reviewed_by      = ?,
                   reviewed_at      = ?,
                   updated_at       = ?
            WHERE  id = ?
              AND  is_latest = 1
              AND  COALESCE(review_status, 'submitted') = 'submitted'
        """, (feedback or None, rejection_reason, score,
              now if score is not None else None, internal_notes or None,
              session.get('user_id'), now, now, submission_id))
        if cur.rowcount == 0:
            flash('Submission can no longer be reviewed (already processed or replaced).', 'warning')
            return _submission_review_redirect(sub['assignment_id'])
        _save_submission_rubric_scores(conn, submission_id, rubric_scores, now)
        _recalculate_assignment_topic_completion(conn, sub['student_id'], sub['master_topic_id'])
        log_activity(
            user_id=session['user_id'],
            branch_id=session.get('branch_id'),
            action_type='reject',
            module_name='lms_assignment_submissions',
            record_id=submission_id,
            description=f"Rejected assignment submission {submission_id}",
            conn=conn,
        )
        conn.commit()
        flash('Assignment rejected. Student can now re-upload.', 'warning')
        return _submission_review_redirect(sub['assignment_id'], completed=True)
    finally:
        conn.close()


@lms_admin_bp.route('/submission/<int:submission_id>/preview')
@lms_content_manager_required
def preview_submission(submission_id):
    conn = get_conn()
    try:
        _require_submission_access(conn, submission_id)
        sub = conn.execute("""
            SELECT s.id, s.file_path, s.original_filename, s.review_status,
                   strftime('%d %b %Y %H:%M', s.submitted_at) AS submitted_date,
                   a.title AS assignment_title, a.id AS assignment_id,
                   st.full_name AS student_name, st.student_code
            FROM   lms_assignment_submissions s
            JOIN   lms_assignments a ON a.id = s.assignment_id
            JOIN   students st ON st.id = s.student_id
            WHERE  s.id = ?
        """, (submission_id,)).fetchone()
        if not sub:
            abort(404)
        orig = sub['original_filename'] or sub['file_path']
        ext  = orig.rsplit('.', 1)[-1].lower() if '.' in orig else ''
        download_url = url_for('lms_admin.admin_download_submission',
                               submission_id=submission_id, _external=True)
        # For Office Viewer the URL must be a public HTTPS URL
        is_localhost = request.host.startswith(('localhost', '127.', '0.0.0.0'))
        office_exts = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
        preview_type = None
        preview_url  = None
        if ext == 'pdf':
            preview_type = 'pdf'
            preview_url  = url_for('lms_admin.admin_download_submission',
                                   submission_id=submission_id,
                                   inline=1)
        elif ext in office_exts:
            preview_type = 'office'
            if not is_localhost:
                token = _make_submission_preview_token(submission_id)
                public_url = url_for('lms_admin.preview_submission_public_file',
                                     token=token, _external=True)
                preview_url = 'https://view.officeapps.live.com/op/embed.aspx?src=' + quote(public_url, safe='')
        return render_template('lms_admin/assignment_preview.html',
                               sub=sub, ext=ext, preview_type=preview_type,
                               preview_url=preview_url, download_url=download_url,
                               is_localhost=is_localhost, office_exts=office_exts,
                               orig_filename=orig,
                               queue_args=_review_queue_return_args(request.args))
    finally:
        conn.close()


@lms_admin_bp.route('/submission/public-file')
def preview_submission_public_file():
    """Short-lived signed URL endpoint for Office Online preview fetches."""
    from flask import send_file, abort

    sid = _read_submission_preview_token(request.args.get('token'))
    if not sid:
        abort(403)

    conn = get_conn()
    try:
        sub = conn.execute(
            "SELECT file_path, original_filename FROM lms_assignment_submissions WHERE id = ?",
            (sid,)
        ).fetchone()
    finally:
        conn.close()

    if not sub:
        abort(404)

    file_path = sub['file_path']
    orig_name = sub['original_filename'] or file_path

    try:
        storage_service = get_storage_service()
        for storage_path in _submission_storage_candidates(file_path):
            if storage_service.file_exists(storage_path):
                file_bytes = storage_service.download_file(storage_path)
                return send_file(
                    io.BytesIO(file_bytes),
                    as_attachment=False,
                    download_name=orig_name,
                    mimetype=_submission_mimetype(orig_name),
                )
    except Exception as e:
        logger.error(f"Error in preview_submission_public_file GCS check: {e}")

    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'uploads', 'submissions')
    )
    full_path = os.path.join(base_dir, file_path)
    if not os.path.isfile(full_path):
        clean_path = file_path.replace("documents/", "", 1) if file_path.startswith("documents/") else file_path
        full_path_fallback = os.path.join(base_dir, clean_path)
        if os.path.isfile(full_path_fallback):
            full_path = full_path_fallback
        else:
            abort(404)

    return send_file(
        full_path,
        as_attachment=False,
        download_name=orig_name,
        mimetype=_submission_mimetype(orig_name),
    )


@lms_admin_bp.route('/master/assignments/file/<int:assignment_id>')
@lms_content_manager_required
def admin_download_assignment(assignment_id):
    from flask import send_file, abort, redirect
    conn = get_conn()
    try:
        a = conn.execute(
            "SELECT file_path, original_filename FROM lms_assignments WHERE id = ?",
            (assignment_id,)
        ).fetchone()
        if not a or not a['file_path']:
            abort(404)
        file_path = a['file_path']
        orig_name = a['original_filename'] or file_path
    finally:
        conn.close()

    try:
        storage_service = get_storage_service()
        if storage_service.file_exists(file_path):
            url = storage_service.generate_public_url(file_path)
            if url.startswith("http"):
                return redirect(url)
    except Exception as e:
        logger.error(f"Error in admin_download_assignment GCS check: {e}")

    base_dir  = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'uploads', 'assignments')
    )
    full_path = os.path.join(base_dir, file_path)
    if not os.path.isfile(full_path):
        clean_path = file_path.replace("documents/", "", 1) if file_path.startswith("documents/") else file_path
        full_path_fallback = os.path.join(base_dir, clean_path)
        if os.path.isfile(full_path_fallback):
            full_path = full_path_fallback
        else:
            abort(404)
    return send_file(full_path, as_attachment=True, download_name=orig_name)


@lms_admin_bp.route('/master/submissions/file/<int:submission_id>')
@lms_content_manager_required
def admin_download_submission(submission_id):
    from flask import send_file, abort, redirect
    conn = get_conn()
    try:
        _require_submission_access(conn, submission_id)
        sub = conn.execute(
            "SELECT file_path, original_filename FROM lms_assignment_submissions WHERE id = ?",
            (submission_id,)
        ).fetchone()
        if not sub:
            abort(404)
        file_path = sub['file_path']
        orig_name = sub['original_filename'] or file_path
    finally:
        conn.close()

    inline = request.args.get('inline') == '1'
    mimetype = _submission_mimetype(orig_name)
    try:
        storage_service = get_storage_service()
        for storage_path in _submission_storage_candidates(file_path):
            if storage_service.file_exists(storage_path):
                if inline:
                    file_bytes = storage_service.download_file(storage_path)
                    return send_file(
                        io.BytesIO(file_bytes),
                        as_attachment=False,
                        download_name=orig_name,
                        mimetype=mimetype,
                    )
                url = storage_service.generate_public_url(storage_path)
                if url.startswith("http"):
                    return redirect(url)
    except Exception as e:
        logger.error(f"Error in admin_download_submission GCS check: {e}")

    base_dir  = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'uploads', 'submissions')
    )
    full_path = os.path.join(base_dir, file_path)
    if not os.path.isfile(full_path):
        clean_path = file_path.replace("documents/", "", 1) if file_path.startswith("documents/") else file_path
        full_path_fallback = os.path.join(base_dir, clean_path)
        if os.path.isfile(full_path_fallback):
            full_path = full_path_fallback
        else:
            abort(404)
    # Default stays as attachment for normal downloads. Preview iframe uses ?inline=1.
    return send_file(
        full_path,
        as_attachment=not inline,
        download_name=orig_name,
        mimetype=mimetype,
    )
