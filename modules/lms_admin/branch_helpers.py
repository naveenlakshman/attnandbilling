import sqlite3
from datetime import datetime
# pyrefly: ignore [missing-import]
from flask import session

def _clone_master_topic(cur, master_topic_id, new_master_chapter_id):
    """
    Duplicate a master topic and all its contents, attachments, and assignments
    for the new master chapter.
    """
    # 1. Fetch original master topic
    cur.execute("SELECT * FROM lms_master_topics WHERE id = ?", (master_topic_id,))
    src_topic = cur.fetchone()
    if not src_topic:
        return None

    now = datetime.now().isoformat(timespec='seconds')

    # 2. Insert new master topic
    cur.execute("""
        INSERT INTO lms_master_topics (
            master_chapter_id, title, short_description, topic_order, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        new_master_chapter_id,
        src_topic['title'],
        src_topic['short_description'],
        src_topic['topic_order'],
        src_topic['status'],
        now,
        now
    ))
    new_master_topic_id = cur.lastrowid

    # 3. Create bridge legacy topic_id for compatibility
    from modules.lms_admin.routes import _ensure_master_bridge_topic
    new_bridge_topic_id = _ensure_master_bridge_topic(cur, new_master_topic_id, src_topic['title'])

    # 4. Copy contents (lms_topic_contents)
    cur.execute("SELECT * FROM lms_topic_contents WHERE master_topic_id = ?", (master_topic_id,))
    contents = cur.fetchall()
    for content in contents:
        cur.execute("""
            INSERT INTO lms_topic_contents (
                topic_id, master_topic_id, content_title, content_mode, content_body,
                external_url, file_path, hotspots_json, display_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_bridge_topic_id,
            new_master_topic_id,
            content['content_title'],
            content['content_mode'],
            content['content_body'],
            content['external_url'],
            content['file_path'],
            content['hotspots_json'],
            content['display_order'],
            now,
            now
        ))

    # 5. Copy attachments (lms_topic_attachments)
    cur.execute("SELECT * FROM lms_topic_attachments WHERE master_topic_id = ?", (master_topic_id,))
    attachments = cur.fetchall()
    for att in attachments:
        cur.execute("""
            INSERT INTO lms_topic_attachments (
                topic_id, master_topic_id, attachment_type, file_name, file_size, file_path,
                description, uploaded_by, is_required, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_bridge_topic_id,
            new_master_topic_id,
            att['attachment_type'],
            att['file_name'],
            att['file_size'],
            att['file_path'],
            att['description'],
            session.get('user_id'),
            att['is_required'],
            now,
            now
        ))

    # 6. Copy assignments (lms_assignments)
    cur.execute("SELECT * FROM lms_assignments WHERE master_topic_id = ?", (master_topic_id,))
    assignments = cur.fetchall()
    for assign in assignments:
        cur.execute("""
            INSERT INTO lms_assignments (
                master_topic_id, title, description, file_path, original_filename,
                uploaded_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_master_topic_id,
            assign['title'],
            assign['description'],
            assign['file_path'],
            assign['original_filename'],
            session.get('user_id'),
            now,
            now
        ))

    return new_master_topic_id


def _clone_master_chapter(cur, master_chapter_id):
    """
    Duplicate a master chapter and all its linked master topics (and their contents/attachments/assignments).
    """
    # 1. Fetch original master chapter
    cur.execute("SELECT * FROM lms_master_chapters WHERE id = ?", (master_chapter_id,))
    src_chapter = cur.fetchone()
    if not src_chapter:
        return None

    now = datetime.now().isoformat(timespec='seconds')

    # 2. Insert new master chapter
    cur.execute("""
        INSERT INTO lms_master_chapters (
            title, description, status, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        src_chapter['title'],
        src_chapter['description'],
        src_chapter['status'],
        session.get('user_id'),
        now,
        now
    ))
    new_master_chapter_id = cur.lastrowid

    # 3. Duplicate all linked master topics
    cur.execute("SELECT id FROM lms_master_topics WHERE master_chapter_id = ?", (master_chapter_id,))
    topics = cur.fetchall()
    for topic in topics:
        _clone_master_topic(cur, topic['id'], new_master_chapter_id)

    return new_master_chapter_id
