import sqlite3
from pathlib import Path

from flask import Flask, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from modules.core import routes
from test_batch_planner_progress import initialize


def test_staff_dashboard_queries_and_renders_own_progress_and_end_dates(tmp_path,monkeypatch):
    path=tmp_path/'staff.db'
    def connect():
        conn=sqlite3.connect(path)
        conn.row_factory=sqlite3.Row
        conn.create_function('parse_date',1,lambda value:value)
        return conn
    conn=connect()
    initialize(conn)
    conn.executescript('''
        ALTER TABLE batches ADD COLUMN trainer_id INTEGER;
        UPDATE batches SET trainer_id=7;
        UPDATE batches SET trainer_id=8 WHERE id=11;
        UPDATE batches SET end_date='2099-12-31' WHERE id=7;
        ALTER TABLE student_batches ADD COLUMN student_id INTEGER;
        UPDATE student_batches SET student_id=id+100;
        ALTER TABLE lms_batch_topic_progress ADD COLUMN taught_at TEXT;
        CREATE TABLE attendance_records (id INTEGER,student_id INTEGER,batch_id INTEGER,attendance_date TEXT,status TEXT);
        CREATE TABLE leads (id INTEGER,institute_id INTEGER,assigned_to_id INTEGER,status TEXT,is_deleted INTEGER,name TEXT,phone TEXT,next_followup_date TEXT,lead_score INTEGER,stage TEXT);
        CREATE TABLE students (id INTEGER,institute_id INTEGER,branch_id INTEGER,joined_date TEXT,full_name TEXT,student_code TEXT,phone TEXT);
        CREATE TABLE invoices (id INTEGER,student_id INTEGER,branch_id INTEGER,invoice_no TEXT,status TEXT);
        CREATE TABLE installment_plans (id INTEGER,invoice_id INTEGER,due_date TEXT,amount_due REAL,amount_paid REAL,remarks TEXT,status TEXT);
        CREATE TABLE activity_logs (institute_id INTEGER,user_id INTEGER,action_type TEXT,module_name TEXT,description TEXT,created_at TEXT);
        CREATE TABLE leave_requests (student_id INTEGER,status TEXT);
    ''')
    from datetime import datetime
    from services.batch_schedule import IST
    today=datetime.now(IST).date().isoformat()
    conn.executescript('''
        INSERT INTO students (id,institute_id) VALUES (101,7),(102,7),(103,7),(104,7),(105,7);
        INSERT INTO student_batches (id,batch_id,status,uses_own_laptop,student_id) VALUES (5,7,'completed',0,105);
    ''')
    conn.executemany('INSERT INTO attendance_records VALUES (?,?,?,?,?)',[
        (1,101,7,today,'present'),(2,102,7,today,'present'),(3,104,10,today,'present'),(4,105,7,today,'present'),
    ])
    conn.commit();conn.close()
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='staff-batch-status')
    app.jinja_loader=ChoiceLoader([
        DictLoader({'base.html':'{% block content %}{% endblock %}'}),
        FileSystemLoader(str(Path(__file__).resolve().parents[1]/'templates')),
    ])
    app.jinja_env.filters['format_time']=lambda value:value
    app.jinja_env.globals['url_for']=lambda endpoint,**values:'/test/'+endpoint
    monkeypatch.setattr(routes,'get_conn',connect)
    monkeypatch.setattr(routes,'_ensure_lms_batch_topic_progress_table',lambda conn:None)
    captured={}
    def rendering(template,**context):
        captured.update(context)
        return render_template(template,company={'company_short_name':'ERP'},**context)
    monkeypatch.setattr(routes,'render_template',rendering)
    app.add_url_rule('/dashboard',view_func=lambda:routes._staff_dashboard(7))
    client=app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=7,branch_id=7,full_name='Test Staff',can_view_all_branches=0,role='staff',institute_id=7)
    response=client.get('/dashboard')
    assert response.status_code==200
    batches={row['id']:row for row in captured['my_batches']}
    assert set(batches)=={7,8,9,10,12}
    assert batches[7]['syllabus_progress']==dict(total_topics=8,completed_topics=3,percent=37.5)
    assert batches[7]['end_summary']['date_label']=='31-12-2099'
    assert batches[7]['end_summary']['days_remaining']>0
    assert batches[9]['end_summary']['days_remaining'] is None
    assert '37.5%' in response.text and '3/8 topics completed' in response.text
    assert 'value="37.5" max="100"' in response.text
    assert 'End date: 31-12-2099' in response.text and 'End date not set' in response.text
    assert 'No syllabus configured' in response.text
    assert captured['att_marked']==captured['total_students_today']==3
    assert captured['attendance_rate']==100.0 and captured['att_outside_roster']==1
    assert batches[7]['att_today_count']==2 and batches[7]['attendance_pct']==100
    assert '1 additional attendance record outside the current roster.' in response.text
