"""Publishing-readiness rules for LMS programs.

Keep these checks server-side so every publishing entry point enforces the
same definition of student-ready content.
"""


_UNSET = object()


def get_program_publishing_readiness(conn, program_id, course_id_override=_UNSET):
    """Return the blocking checks and actionable gaps for one program."""
    program = conn.execute(
        "SELECT id, course_id FROM lms_programs WHERE id = ? AND is_deleted = 0",
        (program_id,),
    ).fetchone()
    if not program:
        return None

    course_id = program["course_id"] if course_id_override is _UNSET else course_id_override
    course = None
    if course_id:
        course = conn.execute(
            "SELECT id, course_name FROM courses WHERE id = ? AND is_active = 1",
            (course_id,),
        ).fetchone()

    chapters = conn.execute(
        """
        SELECT pc.id AS link_id,
               pc.master_chapter_id,
               COALESCE(NULLIF(pc.custom_title, ''), mc.title) AS chapter_title,
               COUNT(DISTINCT CASE WHEN mt.status = 'active' THEN mt.id END) AS active_topic_count
        FROM lms_program_chapters pc
        JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
        LEFT JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
        WHERE pc.program_id = ?
          AND pc.is_visible = 1
          AND mc.status = 'active'
        GROUP BY pc.id, pc.master_chapter_id, pc.custom_title, mc.title
        ORDER BY pc.chapter_order ASC, pc.id ASC
        """,
        (program_id,),
    ).fetchall()

    topics = conn.execute(
        """
        SELECT mt.id,
               mt.title,
               COALESCE(NULLIF(pc.custom_title, ''), mc.title) AS chapter_title,
               CASE WHEN EXISTS (
                   SELECT 1
                   FROM lms_topic_contents ltc
                   WHERE ltc.master_topic_id = mt.id
                     AND ltc.content_mode IN ('pdf', 'rich_text', 'interactive_image')
               ) THEN 1 ELSE 0 END AS has_lesson
        FROM lms_program_chapters pc
        JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
        JOIN lms_master_topics mt ON mt.master_chapter_id = mc.id
        WHERE pc.program_id = ?
          AND pc.is_visible = 1
          AND mc.status = 'active'
          AND mt.status = 'active'
        ORDER BY pc.chapter_order ASC, mt.topic_order ASC, mt.id ASC
        """,
        (program_id,),
    ).fetchall()

    empty_chapters = [dict(row) for row in chapters if not row["active_topic_count"]]
    missing_lessons = [dict(row) for row in topics if not row["has_lesson"]]
    lesson_count = len(topics) - len(missing_lessons)
    checks = [
        {
            "key": "course",
            "label": "Active course selected",
            "passed": bool(course),
            "detail": course["course_name"] if course else "Select an active course.",
        },
        {
            "key": "chapters",
            "label": "At least one visible chapter",
            "passed": bool(chapters),
            "detail": f"{len(chapters)} visible chapter(s)" if chapters else "Attach and show a chapter.",
        },
        {
            "key": "topics",
            "label": "Every visible chapter has an active topic",
            "passed": bool(chapters) and not empty_chapters,
            "detail": (
                f"{len(topics)} active topic(s)"
                if chapters and not empty_chapters
                else f"{len(empty_chapters)} chapter(s) have no active topics."
            ),
        },
        {
            "key": "lessons",
            "label": "Every active topic has lesson content",
            "passed": bool(topics) and not missing_lessons,
            "detail": (
                f"{lesson_count} of {len(topics)} topics ready"
                if not missing_lessons
                else f"{len(missing_lessons)} topic(s) need lesson content."
            ),
        },
    ]

    return {
        "is_ready": all(check["passed"] for check in checks),
        "checks": checks,
        "visible_chapter_count": len(chapters),
        "active_topic_count": len(topics),
        "lesson_topic_count": lesson_count,
        "empty_chapters": empty_chapters,
        "missing_lessons": missing_lessons,
        "preview_topic_id": topics[0]["id"] if topics else None,
    }
