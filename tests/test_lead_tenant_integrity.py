"""Isolated manual enquiry/contact regressions; never use configured data."""
import ast
import re
import sqlite3
import uuid
from datetime import date
from pathlib import Path

import pymysql
import pytest
from flask import Flask, jsonify, session

import db
from db import MySQLConnectionWrapper
from modules.leads import routes, services
from services import tenant_context
from mysql_fixture import mysql_server


TABLES = {'branches', 'users', 'leads', 'followups', 'courses', 'activity_logs', 'students'}


def seed(conn, mysql=False):
    remaining = TABLES.copy()
    for node in ast.walk(ast.parse(Path('db.py').read_text(encoding='utf8'))):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        match = re.match(r'\s*CREATE TABLE IF NOT EXISTS (\w+)\s*\(', node.value)
        if not match or match[1] not in remaining:
            continue
        sql = node.value
        if mysql:
            sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'INTEGER PRIMARY KEY AUTO_INCREMENT')
            sql = sql.replace('TEXT', 'VARCHAR(255)').replace('REAL', 'DECIMAL(14,2)')
            sql = '\n'.join(line for line in sql.splitlines() if not line.strip().startswith('FOREIGN KEY'))
            sql = re.sub(r',\s*\)', ')', sql)
            with conn._conn.cursor() as q:
                q.execute(sql)
        else:
            conn.execute(sql)
        remaining.remove(match[1])
    assert not remaining
    # These are supported additive lead fields in db.py, not invented fixture columns.
    for table, column, definition in [
        ('leads', 'branch_id', 'INTEGER'),
        ('leads', 'email', 'VARCHAR(255)'),
        ('leads', 'parent_discussion_status', 'VARCHAR(50)'),
        ('leads', 'visit_status', 'VARCHAR(50)'),
        ('students', 'lead_id', 'INTEGER'),
        ('courses', 'institute_id', 'INTEGER NOT NULL DEFAULT 1'),
    ]:
        if mysql:
            with conn._conn.cursor() as q:
                q.execute('SHOW COLUMNS FROM '+table+' LIKE %s', (column,))
                exists = bool(q.fetchone())
                if not exists:
                    q.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        else:
            db.add_column_if_not_exists(conn.cursor(), table, column, definition)
    for ident, institute, active in [(1, 1, 1), (2, 2, 1), (3, 2, 1), (4, 2, 0)]:
        conn.execute('INSERT INTO branches(id,institute_id,branch_name,branch_code,is_active,created_at) VALUES(?,?,?,?,?,?)',
                     (ident, institute, f'Branch {ident}', f'B{ident}', active, '2026-01-01'))
    for ident, institute, role, branch in [(11, 1, 'admin', 1), (20, 2, 'admin', 2), (22, 2, 'staff', 2), (23, 2, 'staff', 3)]:
        conn.execute('INSERT INTO users(id,institute_id,full_name,username,password_hash,role,branch_id,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)',
                     (ident, institute, f'User {ident}', f'u{ident}', 'unused-fixture', role, branch, '2026-01-01'))
    for ident, institute, name, phone, owner, branch in [
        (101, 1, 'Same Person', '9871111111', 11, 1),
        (201, 2, 'Local Person', '9872222222', 22, 2),
        (202, 2, 'Other Owner', '9873333333', 23, 3),
    ]:
        conn.execute('INSERT INTO leads(id,institute_id,name,phone,whatsapp,assigned_to_id,branch_id,created_at,stage,status,is_deleted,followup_count) VALUES(?,?,?,?,?,?,?,?,?,?,0,0)',
                     (ident, institute, name, phone, phone, owner, branch, '2026-01-01', 'New Lead', 'active'))
    for ident, institute in [(10, 1), (20, 2)]:
        conn.execute('INSERT INTO courses(id,institute_id,course_name,fee,is_active,created_at) VALUES(?,?,?,?,1,?)',
                     (ident, institute, f'Course {ident}', 100, '2026-01-01'))
    conn.commit()


def plain(value):
    if hasattr(value, 'keys'):
        return {key: plain(value[key]) for key in value.keys()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


@pytest.fixture(params=['sqlite', 'mysql'])
def fixture(request, tmp_path, monkeypatch):
    from config import Config
    mysql = request.param == 'mysql'
    if mysql:
        opts = request.getfixturevalue('mysql_server')
        database = 'lead_integrity_' + uuid.uuid4().hex[:10]
        admin = pymysql.connect(**opts)
        with admin.cursor() as q:
            q.execute('CREATE DATABASE '+database)
        admin.close()
        def connect():
            return MySQLConnectionWrapper(pymysql.connect(**opts, database=database, cursorclass=pymysql.cursors.DictCursor))
    else:
        path = tmp_path/'leads.db'
        def connect():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
    conn = connect()
    seed(conn, mysql=mysql)
    conn.close()
    monkeypatch.setattr(Config, 'DB_TYPE', 'mysql' if mysql else 'sqlite')
    monkeypatch.setattr(routes, 'get_conn', connect)
    monkeypatch.setattr(db, 'get_conn', connect)
    monkeypatch.setattr(tenant_context, 'get_current_institute_id', lambda default=None: session.get('institute_id', default))
    monkeypatch.setattr(routes, 'get_current_institute_id', tenant_context.get_current_institute_id)
    monkeypatch.setattr(routes, 'render_template', lambda template, **values: jsonify(template=template, **plain(values)))
    import modules.smart_counselling.insights_service as insights
    monkeypatch.setattr(insights, 'get_latest_counselling_insight', lambda *args: None)
    import requests
    monkeypatch.setattr(requests.Session, 'request', lambda *a, **k: pytest.fail('No outbound prospect/API calls in manual regressions'))
    app = Flask('lead-integrity')
    app.config.update(TESTING=True, SECRET_KEY='isolated-test-only')
    app.register_blueprint(routes.leads_bp, url_prefix='/leads')
    app.add_url_rule('/login', endpoint='core.login', view_func=lambda: 'Login')
    app.add_url_rule('/dashboard', endpoint='core.dashboard', view_func=lambda: 'Dashboard')
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=22, institute_id=2, branch_id=2, role='staff', can_view_all_branches=0)
    return client, connect


def admin(client):
    with client.session_transaction() as s:
        s.update(user_id=20, role='admin', can_view_all_branches=1)


def form(**changes):
    values = dict(name='New Person', phone='9874444444', whatsapp='9874444444',
                  stage='New Lead', branch_id='2', lead_source='Facebook',
                  last_contact_date=routes._today_ist_date_str())
    values.update(changes)
    return values


def test_manual_creation_keeps_new_lead_and_explicit_owner(fixture):
    client, connect = fixture
    assert client.post('/leads/new', data=form(branch_id='1')).status_code == 302
    c = connect()
    row = c.execute("SELECT * FROM leads WHERE name='New Person'").fetchone()
    assert (row['institute_id'], row['branch_id'], row['assigned_to_id']) == (2, 2, 22)
    assert row['stage']=='New Lead' and row['followup_count']==0 and row['last_contact_date']==routes._today_ist_date_str()
    assert row['lead_source']=='Facebook'
    assert c.execute('SELECT COUNT(*) n FROM followups').fetchone()['n']==0
    c.close()


@pytest.mark.parametrize('branch', ['1', '4'])
def test_manual_admin_cannot_create_in_foreign_or_inactive_branch(fixture, branch):
    client, connect = fixture
    admin(client)
    assert client.post('/leads/new', data=form(branch_id=branch)).status_code == 200
    c = connect()
    assert c.execute('SELECT COUNT(*) n FROM leads').fetchone()['n']==3
    c.close()


def test_manual_form_course_choices_are_tenant_scoped(fixture):
    client, _ = fixture
    assert [r['id'] for r in client.get('/leads/new').get_json()['active_courses']]==[20]


def test_foreign_name_phone_duplicate_does_not_block_edit(fixture):
    client, connect = fixture
    assert client.post('/leads/201/edit', data=form(name='Same Person', phone='9871111111')).status_code==302
    c=connect()
    assert c.execute('SELECT name FROM leads WHERE id=201').fetchone()['name']=='Same Person'
    assert c.execute('SELECT institute_id FROM leads WHERE id=101').fetchone()['institute_id']==1
    c.close()


def test_same_tenant_name_phone_duplicate_still_blocks_edit(fixture):
    client, connect = fixture
    assert client.post('/leads/201/edit', data=form(name='Other Owner', phone='9873333333')).status_code==200
    c=connect()
    assert c.execute('SELECT name FROM leads WHERE id=201').fetchone()['name']=='Local Person'
    c.close()


def test_missing_manual_whatsapp_still_fails_validation(fixture):
    client, connect=fixture
    assert client.post('/leads/new',data=form(whatsapp='')).status_code==200
    c=connect()
    assert c.execute('SELECT COUNT(*) n FROM leads').fetchone()['n']==3
    c.close()


def test_missing_manual_contact_date_still_fails_validation(fixture):
    client,connect=fixture
    assert client.post('/leads/new',data=form(last_contact_date='')).status_code==200
    c=connect()
    assert c.execute('SELECT COUNT(*) n FROM leads').fetchone()['n']==3
    c.close()


@pytest.mark.parametrize('stage',['Converted','Lost'])
def test_manual_creation_cannot_bypass_dedicated_terminal_actions(fixture,stage):
    client,connect=fixture
    assert client.post('/leads/new',data=form(stage=stage)).status_code==200
    c=connect()
    assert c.execute('SELECT COUNT(*) n FROM leads').fetchone()['n']==3
    c.close()


def test_edit_preserves_owned_inactive_branch_but_rejects_foreign_move(fixture):
    client, connect=fixture
    admin(client)
    assert client.post('/leads/201/edit',data=form(branch_id='1')).status_code==200
    c=connect()
    c.execute('UPDATE leads SET branch_id=4 WHERE id=201')
    c.commit();c.close()
    assert client.post('/leads/201/edit',data=form(branch_id='4')).status_code==302


@pytest.mark.parametrize('path', ['/leads/201/followups/new','/leads/followups/complete'])
def test_manual_contact_writers_set_institute_and_keep_contact_semantics(fixture,path):
    client,connect=fixture
    data=dict(lead_id='201',method='Call',outcome='Interested',note='Actual staff contact',next_followup_date='2026-12-01')
    assert client.post(path,data=data).status_code==302
    c=connect()
    f=c.execute('SELECT * FROM followups').fetchone()
    lead=c.execute('SELECT * FROM leads WHERE id=201').fetchone()
    assert (f['institute_id'],f['lead_id'],f['user_id'])==(2,201,22)
    assert lead['followup_count']==1 and lead['stage']=='Contacted' and lead['last_contact_date']
    assert c.execute('SELECT followup_count FROM leads WHERE id=101').fetchone()['followup_count']==0
    c.close()


@pytest.mark.parametrize('lead_id',[101,202])
def test_foreign_or_unassigned_lead_cannot_receive_contact(fixture,lead_id):
    client,connect=fixture
    assert client.post(f'/leads/{lead_id}/followups/new',data={'note':'Forbidden'}).status_code==302
    assert client.post('/leads/followups/complete',data={'lead_id':str(lead_id)}).status_code==302
    c=connect()
    assert c.execute('SELECT COUNT(*) n FROM followups').fetchone()['n']==0
    c.close()


def test_misowned_history_is_hidden_and_retained(fixture):
    client,connect=fixture
    c=connect();today=date.today().isoformat()
    for ident,inst,note in [(1,2,'Visible Contact'),(2,1,'Hidden Misowned Contact')]:
        c.execute('INSERT INTO followups(id,institute_id,lead_id,user_id,note,created_at,next_followup_date) VALUES(?,?,201,22,?,?,?)',
                  (ident,inst,note,today,today))
    c.execute('UPDATE leads SET next_followup_date=? WHERE id=201',(today,));c.commit();c.close()
    response=client.get('/leads/followups?tab=completed')
    assert response.status_code==200
    assert 'Hidden Misowned Contact' not in response.get_data(as_text=True)
    assert 'Visible Contact' in response.get_data(as_text=True)
    detail=client.get('/leads/201')
    assert detail.status_code==200
    assert 'Hidden Misowned Contact' not in detail.get_data(as_text=True)
    assert 'Visible Contact' in detail.get_data(as_text=True)
    c=connect()
    assert c.execute('SELECT institute_id FROM followups WHERE id=2').fetchone()['institute_id']==1
    c.close()


def test_activity_feed_and_filter_metadata_are_tenant_scoped(fixture):
    client,connect=fixture;admin(client)
    c=connect()
    for ident,inst,user,lead,action in [(1,1,11,101,'Foreign Action'),(2,2,22,201,'Own Action')]:
        c.execute("INSERT INTO activity_logs(id,institute_id,user_id,branch_id,action_type,module_name,record_id,description,created_at) VALUES(?,?,?,?,?,'leads',?,?,?)",
                  (ident,inst,user,inst,action,lead,action,'2026-01-01'))
    c.commit();c.close()
    data=client.get('/leads/activity-log').get_json()
    assert [r['id'] for r in data['activities']]==[2]
    assert 11 not in [r['id'] for r in data['all_users']]
    assert data['all_action_types']==['Own Action']


def test_branch_validator_never_assigns_unknown_ownership(fixture):
    _,connect=fixture;c=connect()
    assert services.validate_lead_branch(c,2,None) is None
    with pytest.raises(ValueError):services.validate_lead_branch(c,None,2)
    with pytest.raises(ValueError):services.validate_lead_branch(c,2,1)
    c.close()
