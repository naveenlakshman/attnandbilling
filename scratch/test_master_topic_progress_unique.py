"""Regression test for duplicate master-topic progress and its MySQL migration."""

import os

import pymysql
from pymysql.constants import CLIENT

import test_assignment_phase0_mysql as baseline
from db import get_conn
from modules.students.routes import _master_curriculum_sidebar


INDEX_NAME = 'uq_lms_master_topic_progress_student_program_topic'


def mysql_connection():
    return pymysql.connect(
        host=os.environ.get('MYSQL_HOST', 'local-db'),
        port=int(os.environ.get('MYSQL_PORT', '3306')),
        user=os.environ.get('MYSQL_USER', 'attn_app'),
        password=os.environ['MYSQL_PASSWORD'],
        database=os.environ.get('MYSQL_DB', 'attn_billing_testing'),
        cursorclass=pymysql.cursors.DictCursor,
        client_flag=CLIENT.MULTI_STATEMENTS,
        autocommit=False,
    )


def run(fixtures):
    student_id = fixtures['students']['student_a']
    program_id = fixtures['program']
    topic_id = fixtures['topic']

    direct = mysql_connection()
    with direct.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='lms_master_topic_progress' AND INDEX_NAME=%s",
            (INDEX_NAME,),
        )
        if cur.fetchone()['n']:
            cur.execute(f'DROP INDEX {INDEX_NAME} ON lms_master_topic_progress')
        cur.execute(
            """INSERT INTO lms_master_topic_progress
               (student_id, program_id, master_topic_id, is_completed, completed_at, created_at, updated_at)
               VALUES
               (%s,%s,%s,0,NULL,'2026-07-20 10:00:00','2026-07-20 10:00:00'),
               (%s,%s,%s,1,'2026-07-21 11:00:00','2026-07-21 11:00:00','2026-07-21 11:00:00'),
               (%s,%s,%s,1,'2026-07-22 12:00:00','2026-07-22 12:00:00','2026-07-22 12:00:00')""",
            (student_id, program_id, topic_id) * 3,
        )
    direct.commit()

    conn = get_conn()
    _, sidebar_topics, _ = _master_curriculum_sidebar(conn, program_id, student_id)
    conn.close()
    assert [row['id'] for row in sidebar_topics].count(topic_id) == 1
    assert next(row for row in sidebar_topics if row['id'] == topic_id)['is_completed'] == 1

    migration = open(
        '/app/migrations/20260722_lms_master_topic_progress_unique.sql', encoding='utf-8'
    ).read()
    with direct.cursor() as cur:
        cur.execute(migration)
        while cur.nextset():
            pass
    direct.commit()

    with direct.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n, MAX(is_completed) AS is_completed,
                      MIN(created_at) AS created_at, MAX(completed_at) AS completed_at
               FROM lms_master_topic_progress
               WHERE student_id=%s AND program_id=%s AND master_topic_id=%s""",
            (student_id, program_id, topic_id),
        )
        merged = cur.fetchone()
        assert merged['n'] == 1 and merged['is_completed'] == 1
        assert str(merged['created_at']).startswith('2026-07-20 10:00:00')
        assert str(merged['completed_at']).startswith('2026-07-22 12:00:00')

        try:
            cur.execute(
                """INSERT INTO lms_master_topic_progress
                   (student_id, program_id, master_topic_id, is_completed, created_at, updated_at)
                   VALUES (%s,%s,%s,1,NOW(),NOW())""",
                (student_id, program_id, topic_id),
            )
            raise AssertionError('unique progress index did not reject a duplicate')
        except pymysql.IntegrityError:
            direct.rollback()
    direct.close()
    print('master_topic_sidebar_duplicate_safe=OK')
    print('master_topic_progress_dedup_migration=OK')
    print('master_topic_progress_unique_index=OK')


if __name__ == '__main__':
    try:
        seeded = baseline.create_fixtures()
        run(seeded)
    finally:
        baseline.cleanup()
    print('master_topic_progress_cleanup=OK')
