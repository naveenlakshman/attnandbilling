import sqlite3
import uuid
from pathlib import Path

import pymysql
import pytest
from flask import Blueprint, Flask, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from db import MySQLConnectionWrapper
from modules.attendance import routes
from services.batch_syllabus_progress import batch_syllabus_progress
from mysql_fixture import mysql_server


SCHEMA = '''
CREATE TABLE branches (id INTEGER PRIMARY KEY,institute_id INTEGER,branch_name VARCHAR(80),is_active INTEGER,no_of_computers INTEGER,opening_time VARCHAR(8),closing_time VARCHAR(8));
CREATE TABLE courses (id INTEGER PRIMARY KEY,institute_id INTEGER,course_name VARCHAR(80));
CREATE TABLE batches (id INTEGER PRIMARY KEY,branch_id INTEGER,course_id INTEGER,batch_name VARCHAR(80),start_time VARCHAR(8),end_time VARCHAR(8),start_date VARCHAR(16),end_date VARCHAR(16),status VARCHAR(16));
CREATE TABLE student_batches (id INTEGER PRIMARY KEY,batch_id INTEGER,status VARCHAR(16),uses_own_laptop INTEGER);
CREATE TABLE lms_programs (id INTEGER PRIMARY KEY,institute_id INTEGER,course_id INTEGER,is_active INTEGER,is_deleted INTEGER);
CREATE TABLE lms_course_program_map (course_id INTEGER,program_id INTEGER);
CREATE TABLE lms_batch_program_access (batch_id INTEGER,program_id INTEGER,is_active INTEGER);
CREATE TABLE lms_program_chapters (program_id INTEGER,master_chapter_id INTEGER,is_visible INTEGER);
CREATE TABLE lms_master_chapters (id INTEGER PRIMARY KEY,status VARCHAR(16));
CREATE TABLE lms_master_topics (id INTEGER PRIMARY KEY,master_chapter_id INTEGER,status VARCHAR(16));
CREATE TABLE lms_chapters (id INTEGER PRIMARY KEY,program_id INTEGER,is_active INTEGER);
CREATE TABLE lms_topics (id INTEGER PRIMARY KEY,chapter_id INTEGER,is_active INTEGER);
CREATE TABLE lms_batch_topic_progress (batch_id INTEGER,program_id INTEGER,master_topic_id INTEGER,topic_id INTEGER);
INSERT INTO branches VALUES (7,7,'Own branch',1,20,NULL,NULL),(8,7,'Other own branch',1,10,NULL,NULL),(16,16,'Foreign branch',1,10,NULL,NULL),(17,7,'Inactive branch',0,10,NULL,NULL);
INSERT INTO courses VALUES (71,7,'Own course'),(72,7,'Legacy course'),(16,16,'Foreign course');
INSERT INTO batches VALUES (7,7,71,'Running batch','09:00','11:00','2000-01-01',NULL,'active'),(8,7,71,'Future batch','09:00','11:00','2999-01-01',NULL,'active'),(9,7,NULL,'Unmapped batch','10:00','12:00',NULL,NULL,'active'),(10,7,72,'Legacy batch','11:00','13:00','2000-01-01',NULL,'active'),(11,8,72,'Other own branch batch','09:00','11:00',NULL,NULL,'active'),(12,7,16,'Invalid course batch','09:00','11:00',NULL,NULL,'active'),(16,16,16,'Foreign batch','09:00','11:00',NULL,NULL,'active');
INSERT INTO student_batches VALUES (1,7,'active',0),(2,7,'active',1),(3,8,'active',0),(4,10,'active',0);
INSERT INTO lms_programs VALUES (71,7,71,1,0),(72,7,NULL,1,0),(73,7,NULL,1,0),(74,7,72,1,0),(75,7,71,0,0),(76,7,71,1,1),(16,16,71,1,0);
INSERT INTO lms_course_program_map VALUES (71,72),(71,72),(71,16);
INSERT INTO lms_batch_program_access VALUES (7,73,1),(7,73,1),(8,73,0),(7,16,1);
INSERT INTO lms_master_chapters VALUES (1,'active'),(2,'active'),(3,'inactive');
INSERT INTO lms_master_topics VALUES (1,1,'active'),(2,1,'active'),(3,1,'active'),(4,1,'inactive'),(5,2,'active'),(6,3,'active');
INSERT INTO lms_program_chapters VALUES (71,1,1),(71,1,1),(71,2,0),(71,3,1),(73,1,1),(74,3,1),(16,1,1),(75,1,1),(76,1,1);
INSERT INTO lms_chapters VALUES (71,71,1),(72,72,1),(73,72,0),(74,74,1);
INSERT INTO lms_topics VALUES (1,72,1),(2,72,1),(3,72,0),(4,73,1),(9,71,1),(10,74,1),(11,74,1);
INSERT INTO lms_batch_topic_progress VALUES (7,71,1,NULL),(7,71,1,NULL),(7,71,4,NULL),(7,71,5,NULL),(7,71,999,NULL),(7,71,NULL,2),(7,72,NULL,1),(7,73,1,NULL),(7,16,1,NULL),(8,73,1,NULL),(16,71,1,NULL),(10,74,NULL,10),(10,74,NULL,11);
'''


def initialize(conn):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            if isinstance(conn, MySQLConnectionWrapper) and statement.strip().startswith('CREATE TABLE'):
                with conn._conn.cursor() as cursor:
                    cursor.execute(statement)
            else:
                conn.execute(statement)
    conn.commit()


@pytest.fixture
def database(tmp_path):
    path = tmp_path/'planner.db'
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    conn = connect()
    initialize(conn)
    conn.close()
    return connect


def planner_app(connect,monkeypatch,real_templates=False):
    app = Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='planner-regression')
    bp = Blueprint('attendance',__name__)
    bp.add_url_rule('/batch-planner',view_func=routes.batch_planner)
    bp.add_url_rule('/batch/new',endpoint='create_batch',view_func=lambda:'new')
    bp.add_url_rule('/batch/<int:batch_id>',endpoint='view_batch',view_func=lambda batch_id:'batch')
    app.register_blueprint(bp,url_prefix='/attendance')
    app.add_url_rule('/login',endpoint='core.login',view_func=lambda:'login')
    app.add_url_rule('/branch/<int:branch_id>/edit',endpoint='core.branch_edit',view_func=lambda branch_id:'branch')
    monkeypatch.setattr(routes,'get_conn',connect)
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kwargs:7)
    if real_templates:
        app.jinja_loader = ChoiceLoader([
            DictLoader({'base.html':'{% block extra_css %}{% endblock %}{% block content %}{% endblock %}'}),
            FileSystemLoader(str(Path(__file__).resolve().parents[1]/'templates')),
        ])
        monkeypatch.setattr(routes,'render_template',render_template)
    else:
        def serializable(value):
            if isinstance(value,(dict,sqlite3.Row)):
                return {key:serializable(value[key]) for key in value.keys()}
            if isinstance(value,list):
                return [serializable(item) for item in value]
            return value
        monkeypatch.setattr(routes,'render_template',lambda template,**context:serializable(context))
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=7,institute_id=7,role='admin',branch_id=7,can_view_all_branches=1)
    return app,client


def assert_progress(conn):
    result = batch_syllabus_progress(conn,7,[7,8,9,10,12,16])
    assert result[7] == {'total_topics':8,'completed_topics':3,'percent':37.5}
    assert result[8] == {'total_topics':5,'completed_topics':0,'percent':0.0}
    assert result[10] == {'total_topics':2,'completed_topics':2,'percent':100.0}
    for bid in [9,12,16]:
        assert result[bid] == {'total_topics':0,'completed_topics':0,'percent':0.0}


def test_counts_all_linked_syllabi_without_stale_duplicate_or_foreign_records(database):
    conn = database()
    assert_progress(conn)
    conn.close()


def test_refresh_reflects_taught_and_untaught_topics(database):
    conn = database()
    conn.execute('INSERT INTO lms_batch_topic_progress VALUES (7,71,2,NULL)')
    assert batch_syllabus_progress(conn,7,[7])[7]['percent'] == 50.0
    conn.execute('DELETE FROM lms_batch_topic_progress WHERE batch_id=7 AND program_id=71 AND master_topic_id=1')
    assert batch_syllabus_progress(conn,7,[7])[7]['percent'] == 37.5
    conn.close()


def test_uses_constant_number_of_bulk_queries_and_none_for_empty_batch_list(database):
    conn = database()
    queries = []
    conn.set_trace_callback(queries.append)
    assert batch_syllabus_progress(conn,7,[]) == {} and not queries
    batch_syllabus_progress(conn,7,[7])
    assert len(queries) == 3
    queries.clear()
    batch_syllabus_progress(conn,7,[7,8,9,10,11,12,16])
    assert len(queries) == 3
    conn.close()


def test_planner_adds_running_and_future_progress_without_changing_capacity(database,monkeypatch):
    app,client = planner_app(database,monkeypatch)
    data = client.get('/attendance/batch-planner?branch_id=7').json
    batches = {row['id']:row for row in data['existing_batches']}
    assert set(batches) == {7,9,10,12}
    assert batches[7]['syllabus_progress']['percent'] == 37.5
    assert batches[7]['student_count'] == 2 and batches[7]['computer_count'] == 1
    assert batches[7]['computers_free'] == 19
    assert data['future_batches'][0]['id'] == 8 and data['future_batches'][0]['syllabus_progress']['total_topics'] == 5
    assert batches[12]['course_name'] is None
    assert {row['id'] for row in data['branches']} == {7,8}


@pytest.mark.parametrize('branch',[16,17,999])
def test_planner_rejects_foreign_inactive_or_missing_branch(database,monkeypatch,branch):
    app,client = planner_app(database,monkeypatch)
    assert client.get(f'/attendance/batch-planner?branch_id={branch}').status_code == 403


def test_branch_limited_staff_cannot_override_branch_filter(database,monkeypatch):
    app,client = planner_app(database,monkeypatch)
    with client.session_transaction() as state:
        state.update(role='staff',can_view_all_branches=0)
    assert client.get('/attendance/batch-planner?branch_id=8').status_code == 403
    assert {b['id'] for b in client.get('/attendance/batch-planner').json['branches']} == {7}


def test_real_template_shows_percent_topic_counts_and_empty_state(database,monkeypatch):
    app,client = planner_app(database,monkeypatch,real_templates=True)
    result = client.get('/attendance/batch-planner?branch_id=7')
    assert result.status_code == 200
    assert result.text.count('>Syllabus Progress</th>') == 2
    assert '<strong>37.5%</strong>' in result.text and '3 / 8 topics taught' in result.text
    assert 'value="100.0" max="100"' in result.text and 'value="0.0" max="100"' in result.text
    assert 'No syllabus configured' in result.text and 'aria-label="Syllabus completed for Running batch"' in result.text


def test_planner_requires_login(database,monkeypatch):
    app,client = planner_app(database,monkeypatch)
    with client.session_transaction() as state:
        state.clear()
    assert client.get('/attendance/batch-planner').location.endswith('/login')


def test_mysql_bulk_summary_and_real_planner_query(mysql_server,monkeypatch):
    database_name = 'planner_test_'+uuid.uuid4().hex
    admin = pymysql.connect(**mysql_server)
    with admin.cursor() as cursor:
        cursor.execute('CREATE DATABASE `'+database_name+'`')
    admin.close()
    def connect():
        return MySQLConnectionWrapper(pymysql.connect(**mysql_server,database=database_name))
    conn = connect()
    initialize(conn)
    assert_progress(conn)
    conn.close()
    app,client = planner_app(connect,monkeypatch)
    response = client.get('/attendance/batch-planner?branch_id=7')
    assert response.status_code == 200
    assert next(row for row in response.json['existing_batches'] if row['id']==7)['syllabus_progress']['percent'] == 37.5
