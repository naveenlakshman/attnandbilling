"""Phase 8 cleanup readiness report (non-destructive).

This script does NOT modify data. It inventories legacy LMS footprint,
master coverage, and potential cleanup candidate counts to support
an approval-based Phase 8 cleanup plan.
"""

from __future__ import annotations

from db import get_conn


def main() -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()

        print("[phase8_readiness]")

        totals = {
            "legacy_programs": cur.execute("SELECT COUNT(*) c FROM lms_programs WHERE slug != '__lms_master_bridge__'").fetchone()["c"],
            "legacy_chapters": cur.execute("SELECT COUNT(*) c FROM lms_chapters").fetchone()["c"],
            "legacy_topics": cur.execute("SELECT COUNT(*) c FROM lms_topics").fetchone()["c"],
            "legacy_topic_contents": cur.execute("SELECT COUNT(*) c FROM lms_topic_contents WHERE topic_id IS NOT NULL").fetchone()["c"],
            "legacy_topic_attachments": cur.execute("SELECT COUNT(*) c FROM lms_topic_attachments WHERE topic_id IS NOT NULL").fetchone()["c"],
            "legacy_progress_rows": cur.execute("SELECT COUNT(*) c FROM lms_topic_progress").fetchone()["c"],
            "master_chapters": cur.execute("SELECT COUNT(*) c FROM lms_master_chapters").fetchone()["c"],
            "master_topics": cur.execute("SELECT COUNT(*) c FROM lms_master_topics").fetchone()["c"],
            "program_links": cur.execute("SELECT COUNT(*) c FROM lms_program_chapters").fetchone()["c"],
            "master_progress_rows": cur.execute("SELECT COUNT(*) c FROM lms_master_topic_progress").fetchone()["c"],
            "bridge_rows": cur.execute("SELECT COUNT(*) c FROM lms_master_topic_bridge").fetchone()["c"],
        }
        for key, value in totals.items():
            print(f"{key}={value}")

        print("\n[program_coverage]")
        rows = cur.execute(
            """
            SELECT p.id, p.program_name,
                   (SELECT COUNT(*) FROM lms_chapters c WHERE c.program_id = p.id) AS legacy_chapters,
                   (SELECT COUNT(DISTINCT t.chapter_id)
                    FROM lms_master_topic_bridge b
                    JOIN lms_topics t ON t.id = b.legacy_topic_id
                    JOIN lms_chapters c2 ON c2.id = t.chapter_id
                    WHERE c2.program_id = p.id) AS migrated_legacy_chapters,
                   (SELECT COUNT(*) FROM lms_program_chapters pc WHERE pc.program_id = p.id) AS linked_master_chapters
            FROM lms_programs p
            WHERE p.slug != '__lms_master_bridge__'
            ORDER BY p.id
            """
        ).fetchall()
        for row in rows:
            unmigrated = row["legacy_chapters"] - row["migrated_legacy_chapters"]
            print(
                f"program_id={row['id']};name={row['program_name']};"
                f"legacy_chapters={row['legacy_chapters']};"
                f"migrated_legacy_chapters={row['migrated_legacy_chapters']};"
                f"unmigrated_legacy_chapters={unmigrated};"
                f"linked_master_chapters={row['linked_master_chapters']}"
            )

        print("\n[cleanup_candidate_signals]")
        no_bridge_topics = cur.execute(
            """
            SELECT COUNT(*) c
            FROM lms_topics t
            WHERE NOT EXISTS (
                SELECT 1
                FROM lms_master_topic_bridge b
                WHERE b.legacy_topic_id = t.id
            )
            """
        ).fetchone()["c"]
        print(f"legacy_topics_without_bridge={no_bridge_topics}")

        empty_chapters = cur.execute(
            """
            SELECT COUNT(*) c
            FROM lms_chapters c
            WHERE NOT EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id)
            """
        ).fetchone()["c"]
        print(f"legacy_empty_chapters={empty_chapters}")

        duplicate_link_keys = cur.execute(
            """
            SELECT COUNT(*) c
            FROM (
                SELECT program_id, master_chapter_id, COUNT(*) n
                FROM lms_program_chapters
                GROUP BY program_id, master_chapter_id
                HAVING n > 1
            ) t
            """
        ).fetchone()["c"]
        print(f"duplicate_program_master_links={duplicate_link_keys}")

        duplicate_master_progress = cur.execute(
            """
            SELECT COUNT(*) c
            FROM (
                SELECT student_id, program_id, master_topic_id, COUNT(*) n
                FROM lms_master_topic_progress
                GROUP BY student_id, program_id, master_topic_id
                HAVING n > 1
            ) t
            """
        ).fetchone()["c"]
        print(f"duplicate_master_progress_keys={duplicate_master_progress}")

        print("\n[result]")
        print("phase8_readiness_report_ok=True")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
