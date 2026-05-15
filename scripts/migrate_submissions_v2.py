"""
Migration: Recreate lms_assignment_submissions table to:
  1. Remove the UNIQUE(assignment_id, student_id) constraint so students can have
     multiple submission attempts (each reupload gets a new row).
  2. Add review_status   TEXT DEFAULT 'submitted'  — 'submitted'|'accepted'|'rejected'
  3. Add rejection_reason TEXT
  4. Add is_latest       INTEGER DEFAULT 1  — 1 = current submission, 0 = superseded

Run once:
    python scripts/migrate_submissions_v2.py
"""

import sqlite3
import os

DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'instance', 'database.db')
)


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r['name'] for r in conn.execute(
            "PRAGMA table_info(lms_assignment_submissions)"
        ).fetchall()}

        if 'review_status' in cols and 'is_latest' in cols:
            print("Migration already applied — nothing to do.")
            return

        print("Starting migration ...")

        conn.executescript("""
            BEGIN;

            -- 1. Create replacement table (no UNIQUE constraint)
            CREATE TABLE IF NOT EXISTS lms_assignment_submissions_v2 (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id     INTEGER NOT NULL,
                student_id        INTEGER NOT NULL,
                file_path         TEXT    NOT NULL,
                original_filename TEXT,
                feedback          TEXT,
                status            TEXT    DEFAULT 'submitted',
                review_status     TEXT    DEFAULT 'submitted',
                rejection_reason  TEXT,
                reviewed_by       INTEGER,
                submitted_at      TEXT,
                reviewed_at       TEXT,
                updated_at        TEXT,
                is_latest         INTEGER DEFAULT 1
            );

            -- 2. Copy existing rows; map old 'reviewed' -> 'accepted'
            INSERT INTO lms_assignment_submissions_v2
                (id, assignment_id, student_id, file_path, original_filename, feedback,
                 status, review_status, reviewed_by, submitted_at, reviewed_at, updated_at,
                 is_latest)
            SELECT
                id, assignment_id, student_id, file_path, original_filename, feedback,
                status,
                CASE WHEN status = 'reviewed' THEN 'accepted' ELSE 'submitted' END,
                reviewed_by, submitted_at, reviewed_at, updated_at, 1
            FROM lms_assignment_submissions;

            -- 3. Swap tables
            DROP TABLE lms_assignment_submissions;
            ALTER TABLE lms_assignment_submissions_v2
                RENAME TO lms_assignment_submissions;

            COMMIT;
        """)

        print("Migration complete!")

    except Exception as exc:
        conn.rollback()
        print(f"Migration FAILED: {exc}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
