"""Phase 8 dry-run preview queries (read-only).

Runs only SELECT statements to estimate cleanup scope and risk before any
archive/delete operation.
"""

from __future__ import annotations

from db import get_conn


def main() -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()

        print("[preview_summary]")
        print("master_topics", cur.execute("SELECT COUNT(*) c FROM lms_master_topics").fetchone()["c"])
        print("bridge_rows", cur.execute("SELECT COUNT(*) c FROM lms_master_topic_bridge").fetchone()["c"])
        print("legacy_topics", cur.execute("SELECT COUNT(*) c FROM lms_topics").fetchone()["c"])
        print("legacy_chapters", cur.execute("SELECT COUNT(*) c FROM lms_chapters").fetchone()["c"])

        print("\n[preview_program_migration]")
        rows = cur.execute(
            """
            SELECT p.id, p.program_name,
                   (SELECT COUNT(*) FROM lms_chapters c WHERE c.program_id = p.id) AS legacy_chapters,
                   (SELECT COUNT(DISTINCT t.chapter_id)
                    FROM lms_master_topic_bridge b
                    JOIN lms_topics t ON t.id = b.legacy_topic_id
                    JOIN lms_chapters c2 ON c2.id = t.chapter_id
                    WHERE c2.program_id = p.id) AS migrated_legacy_chapters
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
                f"unmigrated_legacy_chapters={unmigrated}"
            )

        print("\n[preview_candidates]")
        print(
            "legacy_topics_with_bridge",
            cur.execute(
                """
                SELECT COUNT(*) c
                FROM lms_topics t
                WHERE EXISTS (
                    SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
                )
                """
            ).fetchone()["c"],
        )
        print(
            "legacy_topics_without_bridge",
            cur.execute(
                """
                SELECT COUNT(*) c
                FROM lms_topics t
                WHERE NOT EXISTS (
                    SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
                )
                """
            ).fetchone()["c"],
        )
        print(
            "legacy_chapters_all_topics_bridged",
            cur.execute(
                """
                SELECT COUNT(*) c
                FROM lms_chapters c
                WHERE EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM lms_topics t
                    WHERE t.chapter_id = c.id
                      AND NOT EXISTS (
                        SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
                      )
                  )
                """
            ).fetchone()["c"],
        )
        print(
            "legacy_empty_chapters",
            cur.execute(
                """
                SELECT COUNT(*) c
                FROM lms_chapters c
                WHERE NOT EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id)
                """
            ).fetchone()["c"],
        )

        print("\n[preview_guardrails]")
        print(
            "duplicate_program_master_links",
            cur.execute(
                """
                SELECT COUNT(*) c
                FROM (
                    SELECT program_id, master_chapter_id, COUNT(*) n
                    FROM lms_program_chapters
                    GROUP BY program_id, master_chapter_id
                    HAVING n > 1
                ) t
                """
            ).fetchone()["c"],
        )
        print(
            "duplicate_master_progress_keys",
            cur.execute(
                """
                SELECT COUNT(*) c
                FROM (
                    SELECT student_id, program_id, master_topic_id, COUNT(*) n
                    FROM lms_master_topic_progress
                    GROUP BY student_id, program_id, master_topic_id
                    HAVING n > 1
                ) t
                """
            ).fetchone()["c"],
        )

        print("\n[result]")
        print("phase8_preview_ok=True")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
