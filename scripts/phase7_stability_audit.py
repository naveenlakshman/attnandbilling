"""Phase 7 stability audit utility.

Runs non-destructive checks for reusable LMS rollout health:
- key route registration
- critical template compile
- data integrity snapshots
- duplicate key anomalies
- program migration coverage
"""

from __future__ import annotations

from datetime import datetime

from app import app
from db import get_conn


def route_checks() -> list[tuple[str, bool]]:
    names = {rule.endpoint for rule in app.url_map.iter_rules()}
    required = [
        "students.program_view",
        "students.topic_view",
        "students.master_topic_view",
        "students.mark_complete",
        "students.mark_master_complete",
        "lms_admin.phase6_rollout_view",
    ]
    return [(name, name in names) for name in required]


def template_checks() -> list[tuple[str, bool, str]]:
    env = app.jinja_env
    templates = [
        "students/topic.html",
        "lms_admin/phase6_rollout.html",
        "lms_admin/lms_chapters.html",
    ]
    results: list[tuple[str, bool, str]] = []
    for template_name in templates:
        try:
            env.get_template(template_name)
            results.append((template_name, True, "ok"))
        except Exception as exc:  # pragma: no cover
            results.append((template_name, False, str(exc)))
    return results


def data_checks() -> dict[str, int]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        values: dict[str, int] = {}
        values["master_chapters"] = cur.execute(
            "SELECT COUNT(*) AS c FROM lms_master_chapters"
        ).fetchone()["c"]
        values["master_topics"] = cur.execute(
            "SELECT COUNT(*) AS c FROM lms_master_topics"
        ).fetchone()["c"]
        values["program_links"] = cur.execute(
            "SELECT COUNT(*) AS c FROM lms_program_chapters"
        ).fetchone()["c"]
        values["bridge_rows"] = cur.execute(
            "SELECT COUNT(*) AS c FROM lms_master_topic_bridge"
        ).fetchone()["c"]
        values["master_progress_rows"] = cur.execute(
            "SELECT COUNT(*) AS c FROM lms_master_topic_progress"
        ).fetchone()["c"]
        values["duplicate_program_master_links"] = cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM (
                SELECT program_id, master_chapter_id, COUNT(*) AS n
                FROM lms_program_chapters
                GROUP BY program_id, master_chapter_id
                HAVING n > 1
            ) t
            """
        ).fetchone()["c"]
        values["duplicate_master_progress_keys"] = cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM (
                SELECT student_id, program_id, master_topic_id, COUNT(*) AS n
                FROM lms_master_topic_progress
                GROUP BY student_id, program_id, master_topic_id
                HAVING n > 1
            ) t
            """
        ).fetchone()["c"]
        return values
    finally:
        conn.close()


def coverage_checks() -> list[dict[str, int | str]]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT p.id, p.program_name,
                   (SELECT COUNT(*) FROM lms_chapters c WHERE c.program_id = p.id) AS legacy_total,
                   (SELECT COUNT(DISTINCT t.chapter_id)
                    FROM lms_master_topic_bridge b
                    JOIN lms_topics t ON t.id = b.legacy_topic_id
                    JOIN lms_chapters c2 ON c2.id = t.chapter_id
                    WHERE c2.program_id = p.id) AS migrated_legacy,
                   (SELECT COUNT(*) FROM lms_program_chapters pc WHERE pc.program_id = p.id) AS linked_master
            FROM lms_programs p
            WHERE p.is_active = 1 AND p.slug != '__lms_master_bridge__'
            ORDER BY p.id
            """
        ).fetchall()
        return [
            {
                "program_id": row["id"],
                "program_name": row["program_name"],
                "legacy_total": row["legacy_total"],
                "migrated_legacy": row["migrated_legacy"],
                "linked_master": row["linked_master"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def main() -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    print(f"phase7_audit_timestamp={stamp}")
    print(f"routes_count={len(app.url_map._rules)}")

    print("\n[route_checks]")
    for name, ok in route_checks():
        print(f"{name}={ok}")

    print("\n[template_checks]")
    for template_name, ok, detail in template_checks():
        print(f"{template_name}={ok}; detail={detail}")

    print("\n[data_checks]")
    for key, value in data_checks().items():
        print(f"{key}={value}")

    print("\n[coverage_checks]")
    for row in coverage_checks():
        print(
            "program_id={program_id};name={program_name};legacy={legacy_total};"
            "migrated_legacy={migrated_legacy};linked_master={linked_master}".format(**row)
        )


if __name__ == "__main__":
    main()
