import pymysql
import os
import dotenv

dotenv.load_dotenv()
env = os.environ

conn = pymysql.connect(
    user=env.get('MYSQL_USER'),
    password=env.get('MYSQL_PASSWORD'),
    host=env.get('MYSQL_HOST'),
    database=env.get('MYSQL_DB'),
    port=int(env.get('MYSQL_PORT', 3307))
)

try:
    with conn.cursor() as cur:
        # 1. Delete duplicate rows, keeping only the latest one (highest ID)
        print("Cleaning up duplicate notes...")
        deleted = cur.execute("""
            DELETE n1 FROM student_notes n1
            INNER JOIN student_notes n2 
            ON n1.student_id = n2.student_id 
            AND n1.content_id = n2.content_id 
            AND n1.id < n2.id
        """)
        print(f"Deleted {deleted} duplicate rows.")

        # 2. Add unique constraint to student_notes(student_id, content_id)
        print("Adding unique constraint...")
        cur.execute("""
            ALTER TABLE student_notes 
            ADD UNIQUE KEY uq_student_content (student_id, content_id)
        """)
        print("Unique constraint added successfully!")
        
        conn.commit()
finally:
    conn.close()
