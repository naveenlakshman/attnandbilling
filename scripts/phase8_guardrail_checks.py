"""
Phase 8 Guardrail Checks (G-1 through G-6) — READ-ONLY
All queries must pass before CP1 backup is created and Stage 1 proceeds.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'instance', 'database.db')

BRIDGE_SLUG = '__lms_master_bridge__'

def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute('PRAGMA foreign_keys = ON')

    failures = []

    # ------------------------------------------------------------------
    # G-1: Legacy topics without bridge (must be 0)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT COUNT(*) AS n
        FROM lms_topics t
        WHERE NOT EXISTS (
            SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
        )
    """)
    g1 = cur.fetchone()['n']
    status = 'PASS' if g1 == 0 else 'FAIL'
    print(f'G-1 legacy_topics_without_bridge = {g1}  [{status}]')
    if g1 != 0:
        failures.append(f'G-1: {g1} legacy topics have no bridge entry')

    # ------------------------------------------------------------------
    # G-2: Duplicate program-master chapter links (must be 0)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT COUNT(*) AS n FROM (
            SELECT program_id, master_chapter_id, COUNT(*) AS cnt
            FROM lms_program_chapters
            GROUP BY program_id, master_chapter_id
            HAVING cnt > 1
        ) x
    """)
    g2 = cur.fetchone()['n']
    status = 'PASS' if g2 == 0 else 'FAIL'
    print(f'G-2 duplicate_program_master_links = {g2}  [{status}]')
    if g2 != 0:
        failures.append(f'G-2: {g2} duplicate program-master chapter links')

    # ------------------------------------------------------------------
    # G-3: Duplicate master progress keys (must be 0)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT COUNT(*) AS n FROM (
            SELECT student_id, program_id, master_topic_id, COUNT(*) AS cnt
            FROM lms_master_topic_progress
            GROUP BY student_id, program_id, master_topic_id
            HAVING cnt > 1
        ) x
    """)
    g3 = cur.fetchone()['n']
    status = 'PASS' if g3 == 0 else 'FAIL'
    print(f'G-3 duplicate_master_progress_keys = {g3}  [{status}]')
    if g3 != 0:
        failures.append(f'G-3: {g3} duplicate master progress keys')

    # ------------------------------------------------------------------
    # G-4: Legacy chapters where all topics are bridged (archive candidates)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT c.id, c.chapter_title, c.program_id, COUNT(t.id) AS topic_count
        FROM lms_chapters c
        JOIN lms_topics t ON t.chapter_id = c.id
        WHERE NOT EXISTS (
            SELECT 1 FROM lms_topics t2
            WHERE t2.chapter_id = c.id
              AND NOT EXISTS (
                  SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t2.id
              )
        )
        GROUP BY c.id, c.chapter_title, c.program_id
        ORDER BY c.program_id, c.id
    """)
    g4_rows = cur.fetchall()
    g4_count = len(g4_rows)
    status = 'PASS' if g4_count > 0 else 'WARN'
    print(f'G-4 archive_candidates (fully bridged chapters) = {g4_count}  [{status}]')
    for row in g4_rows:
        print(f'     chapter_id={row["id"]:3d}  program_id={row["program_id"]}  '
              f'topics={row["topic_count"]:3d}  title={row["chapter_title"]}')

    # ------------------------------------------------------------------
    # G-5: Empty legacy chapters (policy exclusions)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT c.id, c.chapter_title, c.program_id
        FROM lms_chapters c
        WHERE NOT EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id)
    """)
    g5_rows = cur.fetchall()
    g5_count = len(g5_rows)
    status = 'INFO'  # not a failure; these are policy exclusions
    print(f'G-5 empty_legacy_chapters (policy excluded) = {g5_count}  [{status}]')
    for row in g5_rows:
        print(f'     chapter_id={row["id"]:3d}  program_id={row["program_id"]}  '
              f'title={row["chapter_title"]}  <- WILL NOT BE ARCHIVED/DELETED')

    # ------------------------------------------------------------------
    # G-6: Bridge program has no real content (must be 0)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT COUNT(*) AS n
        FROM lms_topic_contents tc
        JOIN lms_topics t ON t.id = tc.topic_id
        JOIN lms_chapters c ON c.id = t.chapter_id
        JOIN lms_programs p ON p.id = c.program_id
        WHERE p.slug = ?
          AND tc.master_topic_id IS NULL
    """, (BRIDGE_SLUG,))
    g6 = cur.fetchone()['n']
    status = 'PASS' if g6 == 0 else 'FAIL'
    print(f'G-6 bridge_program_content_rows = {g6}  [{status}]')
    if g6 != 0:
        failures.append(f'G-6: {g6} content rows found under bridge program — investigate before Stage 1')

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    if failures:
        print('phase8_guardrails_ok=False')
        print('FAILURES:')
        for f in failures:
            print(f'  - {f}')
        print('ACTION: Resolve all failures before proceeding to CP1.')
    else:
        print('phase8_guardrails_ok=True')
        print('All guardrails pass. Safe to create CP1 and proceed to Stage 1.')
        print(f'Archive candidates: {g4_count} chapters ({sum(r["topic_count"] for r in g4_rows)} topics)')
        print(f'Policy exclusions:  {g5_count} empty chapters (leave in place)')

    con.close()

if __name__ == '__main__':
    run()
