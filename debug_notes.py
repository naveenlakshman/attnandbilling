import sys, os
os.chdir(r'C:\Users\hello\attnandbilling')
sys.path.insert(0, r'C:\Users\hello\attnandbilling')
from db import get_conn
conn = get_conn()

print("=== content for master_topic=1 with program join ===")
rows = conn.execute("""
    SELECT tc.id, tc.master_topic_id, mt.master_chapter_id, pc.program_id
    FROM lms_topic_contents tc
    LEFT JOIN lms_master_topics mt ON mt.id = tc.master_topic_id
    LEFT JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
    WHERE tc.master_topic_id = 1
""").fetchall()
for r in rows:
    print(dict(r))

print("\n=== _student_can_access_content simulation for content_id=? ===")
# Get first content id for master_topic=1
sample = conn.execute("SELECT id FROM lms_topic_contents WHERE master_topic_id=1 LIMIT 1").fetchone()
if sample:
    cid = sample['id']
    print("content_id:", cid)
    row = conn.execute("""
        SELECT lp.id AS program_id
        FROM lms_topic_contents tc
        LEFT JOIN lms_master_topics mt ON mt.id = tc.master_topic_id
        LEFT JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
        LEFT JOIN lms_programs lp ON lp.id = pc.program_id
        WHERE tc.id = ?
        LIMIT 1
    """, (cid,)).fetchone()
    print("LIMIT 1 result:", dict(row) if row else None)

print("\n=== programs that have master_topic=1 ===")
rows2 = conn.execute("""
    SELECT DISTINCT pc.program_id
    FROM lms_master_topics mt
    JOIN lms_program_chapters pc ON pc.master_chapter_id = mt.master_chapter_id
    WHERE mt.id = 1
""").fetchall()
for r in rows2:
    print("program_id:", r['program_id'])

conn.close()
print("done")
