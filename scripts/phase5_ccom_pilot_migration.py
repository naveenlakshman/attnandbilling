import argparse
from datetime import datetime
import os
import sys
import sqlite3

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import get_conn
from config import DB_PATH


def renumber_program_links(cur, program_id):
    rows = cur.execute(
        """
        SELECT id
        FROM lms_program_chapters
        WHERE program_id = ?
        ORDER BY chapter_order ASC, id ASC
        """,
        (program_id,),
    ).fetchall()
    for idx, row in enumerate(rows, start=1):
        cur.execute("UPDATE lms_program_chapters SET chapter_order = ? WHERE id = ?", (idx, row["id"]))


def create_backup(conn, label='phase5_pilot'):
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


def migrate_chapter(cur, program_id, chapter_id):
    now = datetime.now().isoformat(timespec="seconds")

    chapter = cur.execute(
        """
        SELECT id, program_id, chapter_title, chapter_order, description, is_active
        FROM lms_chapters
        WHERE id = ? AND program_id = ?
        """,
        (chapter_id, program_id),
    ).fetchone()
    if not chapter:
        raise ValueError("Chapter not found for the given program")

    topics = cur.execute(
        """
        SELECT id, topic_title, topic_order, short_description, is_active
        FROM lms_topics
        WHERE chapter_id = ?
        ORDER BY topic_order ASC, id ASC
        """,
        (chapter_id,),
    ).fetchall()
    if not topics:
        raise ValueError("Chapter has no topics")

    existing_bridge = cur.execute(
        """
        SELECT 1
        FROM lms_master_topic_bridge b
        JOIN lms_topics t ON t.id = b.legacy_topic_id
        WHERE t.chapter_id = ?
        LIMIT 1
        """,
        (chapter_id,),
    ).fetchone()
    if existing_bridge:
        raise ValueError("Chapter already appears migrated (bridge rows exist)")

    chapter_status = "active" if chapter["is_active"] else "archived"
    cur.execute(
        """
        INSERT INTO lms_master_chapters (title, description, status, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chapter["chapter_title"], chapter["description"] or "", chapter_status, None, now, now),
    )
    master_chapter_id = cur.lastrowid

    cur.execute(
        """
        INSERT INTO lms_program_chapters (program_id, master_chapter_id, chapter_order, custom_title, is_visible, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (program_id, master_chapter_id, chapter["chapter_order"] or 1, None, now),
    )

    migrated_topics = 0
    for topic in topics:
        topic_status = "active" if topic["is_active"] else "archived"
        cur.execute(
            """
            INSERT INTO lms_master_topics (master_chapter_id, title, short_description, topic_order, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_chapter_id,
                topic["topic_title"],
                topic["short_description"] or "",
                topic["topic_order"] or 1,
                topic_status,
                now,
                now,
            ),
        )
        master_topic_id = cur.lastrowid

        cur.execute(
            """
            UPDATE lms_topic_contents
            SET master_topic_id = ?
            WHERE topic_id = ?
              AND (master_topic_id IS NULL OR master_topic_id = '')
            """,
            (master_topic_id, topic["id"]),
        )
        cur.execute(
            """
            UPDATE lms_topic_attachments
            SET master_topic_id = ?
            WHERE topic_id = ?
              AND (master_topic_id IS NULL OR master_topic_id = '')
            """,
            (master_topic_id, topic["id"]),
        )
        cur.execute(
            """
            INSERT INTO lms_master_topic_bridge (master_topic_id, legacy_topic_id, created_at)
            VALUES (?, ?, ?)
            """,
            (master_topic_id, topic["id"], now),
        )
        migrated_topics += 1

    renumber_program_links(cur, program_id)
    return master_chapter_id, migrated_topics


def main():
    parser = argparse.ArgumentParser(description="Phase 5 pilot migration (legacy chapter -> master)")
    parser.add_argument("--program-id", type=int, required=True)
    parser.add_argument("--chapter-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        cur = conn.cursor()
        program = cur.execute("SELECT id, program_name FROM lms_programs WHERE id = ?", (args.program_id,)).fetchone()
        if not program:
            raise ValueError("Program not found")

        if args.dry_run:
            chapter = cur.execute(
                "SELECT id, chapter_title FROM lms_chapters WHERE id = ? AND program_id = ?",
                (args.chapter_id, args.program_id),
            ).fetchone()
            if not chapter:
                raise ValueError("Chapter not found for this program")
            topic_count = cur.execute(
                "SELECT COUNT(*) AS c FROM lms_topics WHERE chapter_id = ?",
                (args.chapter_id,),
            ).fetchone()["c"]
            print(f"DRY RUN OK: program={program['program_name']} chapter={chapter['chapter_title']} topics={topic_count}")
            return

        backup_path = create_backup(conn)
        master_chapter_id, migrated_topics = migrate_chapter(cur, args.program_id, args.chapter_id)
        conn.commit()
        print(
            f"MIGRATION OK: program_id={args.program_id} chapter_id={args.chapter_id} "
            f"master_chapter_id={master_chapter_id} migrated_topics={migrated_topics} "
            f"backup={os.path.basename(backup_path)}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
