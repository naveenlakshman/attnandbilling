"""Immutable LMS content revisions and approval helpers."""

import json
from datetime import datetime


SNAPSHOT_FIELDS = (
    'topic_id', 'master_topic_id', 'content_mode', 'content_title',
    'external_url', 'file_path', 'content_body', 'hotspots_json', 'display_order',
)


def content_snapshot(content, overrides=None):
    data = {field: content[field] for field in SNAPSHOT_FIELDS}
    if overrides:
        data.update(overrides)
    return data


def ensure_baseline_revision(conn, content, actor_id=None):
    existing = conn.execute(
        'SELECT id FROM lms_content_revisions WHERE content_id = ? LIMIT 1',
        (content['id'],),
    ).fetchone()
    if existing:
        return existing['id']
    return record_revision(
        conn, content, 'baseline', 'Baseline captured before editorial governance.',
        actor_id, 'approved'
    )


def record_revision(conn, content, action_type, change_note, actor_id,
                    approval_status='approved', overrides=None):
    latest = conn.execute(
        'SELECT COALESCE(MAX(revision_no), 0) AS revision_no '
        'FROM lms_content_revisions WHERE content_id = ?',
        (content['id'],),
    ).fetchone()['revision_no']
    snapshot = content_snapshot(content, overrides)
    cursor = conn.execute(
        """
        INSERT INTO lms_content_revisions (
            content_id, master_topic_id, revision_no, action_type,
            approval_status, snapshot_json, change_note, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content['id'], snapshot.get('master_topic_id'), latest + 1,
            action_type, approval_status,
            json.dumps(snapshot, ensure_ascii=False),
            (change_note or '').strip()[:500] or None,
            actor_id, datetime.now().isoformat(timespec='seconds'),
        ),
    )
    return cursor.lastrowid


def decode_revision(revision):
    return json.loads(revision['snapshot_json'])


def apply_revision_snapshot(conn, content_id, snapshot):
    conn.execute(
        """
        UPDATE lms_topic_contents
        SET content_mode = ?, content_title = ?, external_url = ?, file_path = ?,
            content_body = ?, hotspots_json = ?, display_order = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            snapshot.get('content_mode'), snapshot.get('content_title'),
            snapshot.get('external_url') or '', snapshot.get('file_path') or '',
            snapshot.get('content_body') or '', snapshot.get('hotspots_json') or '',
            snapshot.get('display_order') or 1,
            datetime.now().isoformat(timespec='seconds'), content_id,
        ),
    )


def get_content_editorial_summary(conn, content_id):
    """Return author, latest approved editor, and pending-review count."""
    first = conn.execute(
        """
        SELECT r.created_at, u.full_name
        FROM lms_content_revisions r
        LEFT JOIN users u ON u.id = r.created_by
        WHERE r.content_id = ? AND r.action_type IN ('create', 'baseline')
        ORDER BY r.revision_no ASC LIMIT 1
        """,
        (content_id,),
    ).fetchone()
    latest = conn.execute(
        """
        SELECT r.created_at, u.full_name
        FROM lms_content_revisions r
        LEFT JOIN users u ON u.id = r.created_by
        WHERE r.content_id = ? AND r.approval_status = 'approved'
        ORDER BY r.revision_no DESC LIMIT 1
        """,
        (content_id,),
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) AS count FROM lms_content_revisions "
        "WHERE content_id = ? AND approval_status = 'pending'",
        (content_id,),
    ).fetchone()['count']
    return {
        'author_name': first['full_name'] if first and first['full_name'] else 'System / legacy',
        'created_at': first['created_at'] if first else None,
        'editor_name': latest['full_name'] if latest and latest['full_name'] else 'System / legacy',
        'updated_at': latest['created_at'] if latest else None,
        'pending_count': pending,
    }
