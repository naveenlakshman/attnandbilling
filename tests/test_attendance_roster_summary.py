import sqlite3
import uuid

import pymysql
import pytest

from db import MySQLConnectionWrapper
from services.attendance_summary import get_attendance_summary
from mysql_fixture import mysql_server

SCHEMA='''
CREATE TABLE branches (id INTEGER PRIMARY KEY,institute_id INTEGER,branch_name VARCHAR(80));
CREATE TABLE students (id INTEGER PRIMARY KEY,institute_id INTEGER);
CREATE TABLE batches (id INTEGER PRIMARY KEY,branch_id INTEGER,trainer_id INTEGER,status VARCHAR(16),start_date VARCHAR(16),end_date VARCHAR(16));
CREATE TABLE student_batches (id INTEGER PRIMARY KEY,student_id INTEGER,batch_id INTEGER,status VARCHAR(16));
CREATE TABLE attendance_records (id INTEGER PRIMARY KEY,student_id INTEGER,batch_id INTEGER,attendance_date VARCHAR(16),status VARCHAR(16));
INSERT INTO branches VALUES (7,7,'Head Office'),(8,8,'Foreign branch'),(9,7,'Hoskote <West>'),(10,7,'Empty Branch');
INSERT INTO students VALUES (1,7),(2,7),(3,7),(4,7),(5,7),(6,7),(7,7),(80,8);
INSERT INTO batches VALUES (10,7,7,'active',NULL,NULL),(11,9,9,'active','2026-01-01','2026-12-31'),(12,7,7,'active','2026-12-01',NULL),(13,7,7,'active',NULL,'2026-10-31'),(14,7,7,'completed',NULL,NULL),(80,8,7,'active',NULL,NULL);
INSERT INTO student_batches VALUES (1,1,10,'active'),(2,2,10,'active'),(3,3,10,'active'),(4,1,11,'active'),(5,4,10,'completed'),(6,5,12,'active'),(7,6,13,'active'),(8,7,14,'active'),(9,80,80,'active'),(10,80,10,'active'),(11,1,10,'active');
INSERT INTO attendance_records VALUES (1,2,10,'2026-11-02','present'),(2,1,10,'2026-11-02','present'),(3,1,11,'2026-11-02','leave'),(4,2,10,'2026-11-02','absent'),(5,4,10,'2026-11-02','present'),(6,3,10,'2026-11-01','present'),(7,5,12,'2026-11-02','present'),(8,6,13,'2026-11-02','present'),(9,7,14,'2026-11-02','present'),(10,80,80,'2026-11-02','present'),(11,80,10,'2026-11-02','present');
'''


def seed(conn):
    for statement in SCHEMA.split(';'):
        if not statement.strip():continue
        if isinstance(conn,MySQLConnectionWrapper) and statement.strip().startswith('CREATE TABLE'):
            with conn._conn.cursor() as cur:cur.execute(statement)
        else:conn.execute(statement)
    conn.commit()


@pytest.fixture
def db():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;seed(conn)
    yield conn
    conn.close()


def check_summary(conn):
    result=get_attendance_summary(conn,7,'2026-11-02')
    assert result==dict(expected=4,marked=3,pending=1,percentage=75.0,outside_roster=1,
                       counts=dict(present=1,late=0,absent=1,leave=1))
    staff=get_attendance_summary(conn,7,'2026-11-02',trainer_id=7)
    assert staff['expected']==3 and staff['marked']==2 and staff['percentage']==66.7 and staff['outside_roster']==1
    other=get_attendance_summary(conn,7,'2026-11-02',trainer_id=9)
    assert other['expected']==other['marked']==1 and other['outside_roster']==0
    breakdown=get_attendance_summary(conn,7,'2026-11-02',include_branches=True)
    assert {key:value for key,value in breakdown.items() if key!='branches'}==result
    branches={row['branch_id']:row for row in breakdown['branches']}
    assert [row['branch_id'] for row in breakdown['branches']]==[10,7,9]
    assert set(branches)=={7,9,10}  # The foreign institute's branch is excluded.
    assert branches[7]['expected']==3 and branches[7]['marked']==2
    assert branches[7]['percentage']==66.7 and branches[7]['pending']==1
    assert branches[7]['outside_roster']==1 and branches[9]['outside_roster']==0
    assert branches[9]['expected']==branches[9]['marked']==1 and branches[9]['percentage']==100.0
    assert branches[9]['counts']['leave']==1
    assert branches[10]['expected']==branches[10]['marked']==branches[10]['pending']==0
    assert branches[10]['percentage'] is None
    for key in ('expected','marked','pending','outside_roster'):
        assert sum(row[key] for row in branches.values())==result[key]
    for status,count in result['counts'].items():
        assert sum(row['counts'][status] for row in branches.values())==count


def test_summary_uses_current_roster_and_latest_mark_per_enrolment(db):
    check_summary(db)


def test_fully_marked_roster_cannot_exceed_denominator_and_keeps_history(db):
    db.execute("INSERT INTO attendance_records VALUES (12,3,10,'2026-11-02','late')")
    before=db.execute('SELECT COUNT(*) FROM attendance_records').fetchone()[0]
    result=get_attendance_summary(db,7,'2026-11-02')
    assert result['marked']==result['expected']==4 and result['percentage']==100.0
    assert result['outside_roster']==1 and result['pending']==0
    assert db.execute('SELECT COUNT(*) FROM attendance_records').fetchone()[0]==before


def test_unmarked_roster_and_no_current_roster(db):
    result=get_attendance_summary(db,7,'2026-11-03',include_branches=True)
    assert result['expected']==4 and result['marked']==0 and result['pending']==4 and result['percentage']==0.0
    assert all(row['marked']==0 and row['pending']==row['expected'] for row in result['branches'])
    assert [row['percentage'] for row in result['branches']]==[None,0.0,0.0]
    empty=get_attendance_summary(db,999,'2026-11-02')
    assert empty['expected']==empty['marked']==empty['outside_roster']==0 and empty['percentage'] is None
    assert get_attendance_summary(db,999,'2026-11-02',include_branches=True)['branches']==[]


def test_mysql_uses_same_roster_rule(mysql_server):
    name='attendance_roster_'+uuid.uuid4().hex
    admin=pymysql.connect(**mysql_server)
    with admin.cursor() as cur:cur.execute('CREATE DATABASE `'+name+'`')
    admin.close()
    conn=MySQLConnectionWrapper(pymysql.connect(**mysql_server,database=name))
    try:seed(conn);check_summary(conn)
    finally:conn.close()
