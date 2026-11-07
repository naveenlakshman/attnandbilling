"""Behavioral regressions using disposable databases; no configured data is used."""
import ast
import json
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import pymysql
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from db import MySQLConnectionWrapper
from mysql_fixture import mysql_server
from services import admissions, collections, finance_ledger as ledger
from services.erp_schema import init_sqlite_schema
from services.accuracy_reports import build
from services.recovery_preview import preview
from modules.accuracy import routes

TABLES=set('students courses branches users invoices invoice_items receipts bad_debt_writeoffs installment_plans batches student_batches lms_batch_topic_progress expenses institute_settings institute_document_sequences leads followups attendance_records activity_logs'.split())

def seed(c,mysql=False):
    remaining=TABLES.copy()
    for n in ast.walk(ast.parse(Path('db.py').read_text(encoding='utf-8'))):
        if isinstance(n,ast.Constant) and isinstance(n.value,str):
            m=re.match(r'\s*CREATE TABLE IF NOT EXISTS (\w+)\s*\(',n.value)
            if m and m[1] in remaining:
                ddl=n.value
                if mysql:
                    ddl=ddl.replace('INTEGER PRIMARY KEY AUTOINCREMENT','INTEGER PRIMARY KEY AUTO_INCREMENT')
                    ddl=ddl.replace("DEFAULT (datetime('now'))","DEFAULT (CURRENT_TIMESTAMP)")
                    # Mirror deployed string/date fields; external FKs are tested in services.
                    ddl='\n'.join(line for line in ddl.splitlines() if not line.strip().startswith('FOREIGN KEY'))
                    ddl=re.sub(r',\s*\)',')',ddl)
                    ddl=ddl.replace('TEXT','VARCHAR(255)').replace('REAL','DECIMAL(14,2)')
                    with c._conn.cursor() as cur:cur.execute(ddl)
                else:c.execute(ddl)
                remaining.remove(m[1])
    for table in ['courses','invoices','receipts','bad_debt_writeoffs','expenses']:
        if mysql:
            with c._conn.cursor() as cur:
                cur.execute('SHOW COLUMNS FROM '+table+" LIKE 'institute_id'")
                exists=bool(cur.fetchone())
        else:
            exists='institute_id' in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}
        if exists:continue
        sql='ALTER TABLE '+table+' ADD COLUMN institute_id INTEGER NOT NULL DEFAULT 7'
        if mysql:
            with c._conn.cursor() as cur:cur.execute(sql)
        else:c.execute(sql)
    sql='ALTER TABLE students ADD COLUMN student_location VARCHAR(100)'
    if mysql:
        with c._conn.cursor() as cur:cur.execute(sql)
    else:c.execute(sql)
    statements=[
      "INSERT INTO branches(id,institute_id,branch_name,branch_code,created_at) VALUES(1,7,'Head Office','HO','2026-04-01'),(2,7,'Hoskote','HS','2026-04-01'),(8,8,'Foreign','F','2026-04-01')",
      "INSERT INTO users(id,institute_id,full_name,username,password_hash,role,branch_id,created_at) VALUES(10,7,'Chaithra','chaithra','x','admin',1,'2026-04-01'),(11,7,'Trainer B','trainerb','x','staff',2,'2026-04-01'),(80,8,'Foreign','foreign','x','admin',8,'2026-04-01')",
      "INSERT INTO students(id,institute_id,student_code,full_name,phone,joined_date,branch_id,created_at) VALUES(1,7,'S1','DFA Student','9999999999','2026-04-01',1,'2026-04-01'),(8,8,'F8','Foreign student','9999999998','2026-04-01',8,'2026-04-01')",
      "INSERT INTO courses(id,institute_id,course_name,fee,created_at) VALUES(1,7,'DFA',12000,'2026-04-01'),(2,7,'CCOM',5000,'2026-04-01'),(8,8,'Foreign',100,'2026-04-01')",
      "INSERT INTO batches(id,batch_name,course_id,branch_id,trainer_id,created_at) VALUES(1,'Basics',1,1,10,'2026-04-01'),(2,'Tally',1,2,11,'2026-04-01'),(3,'Basics again',1,2,11,'2026-04-01'),(8,'Foreign',8,8,80,'2026-04-01')",
      "INSERT INTO invoices(id,institute_id,invoice_no,student_id,branch_id,invoice_date,subtotal,discount_amount,total_amount,created_by,created_at) VALUES(1,7,'INV1',1,1,'2026-04-01',12000,2000,10000,10,'2026-04-01'),(2,7,'INV2',1,1,'2026-05-01',6000,0,6000,10,'2026-05-01'),(8,8,'FOREIGN',8,8,'2026-04-01',100,0,100,80,'2026-04-01')",
      "INSERT INTO invoice_items(id,invoice_id,course_id,description,line_total,created_at) VALUES(1,1,1,'DFA',10000,'2026-04-01'),(2,2,1,'DFA extra',1000,'2026-05-01'),(3,2,2,'CCOM',5000,'2026-05-01'),(8,8,8,'Foreign',100,'2026-04-01')",
      "INSERT INTO installment_plans(id,invoice_id,installment_no,due_date,amount_due,created_at) VALUES(1,1,1,'2026-04-01',4000,'2026-04-01'),(2,1,2,'2026-05-01',6000,'2026-04-01')",
      "INSERT INTO institute_settings(institute_id,receipt_prefix,created_at) VALUES(7,'AUD/RCP','2026-04-01')"]
    for statement in statements:c.execute(statement)
    if mysql:
        migration(c)
    else:init_sqlite_schema(c)
    c.commit()

def migration(c):
    for statement in Path('migrations/20261107_erp_data_accuracy.sql').read_text().split(';'):
        if statement.strip():
            with c._conn.cursor() as cur:cur.execute(statement)

@pytest.fixture
def connection(tmp_path,monkeypatch):
    from config import Config
    monkeypatch.setattr(Config,'DB_TYPE','sqlite')
    path=tmp_path/'accuracy.db'
    def connect():
        c=sqlite3.connect(path,timeout=10);c.row_factory=sqlite3.Row
        c.create_function('parse_date',1,lambda v:str(v or '')[:10]);return c
    c=connect();seed(c);c.close();return connect


@pytest.fixture(params=['sqlite','mysql'])
def release_connection(request,connection,monkeypatch):
    if request.param=='sqlite':return connection
    from config import Config
    options=request.getfixturevalue('mysql_server')
    monkeypatch.setattr(Config,'DB_TYPE','mysql')
    database='accuracy_release_'+uuid.uuid4().hex[:12]
    admin=pymysql.connect(**options)
    with admin.cursor() as cur:cur.execute('CREATE DATABASE '+database)
    admin.close()
    def connect():return MySQLConnectionWrapper(pymysql.connect(**options,database=database))
    c=connect();seed(c,True);c.commit();c.close()
    return connect

def create(c,course=1,day='2026-04-01',branch=1):
    return admissions.admission(c,7,10,1,course,day,branch)

def pay(c,amount,day,branch,key,invoice=1):
    return collections.payment(c,7,10,1,amount,day,branch,'branch','cash',None,key,invoice_id=invoice)

def writeoff(c):
    c.execute("INSERT INTO bad_debt_writeoffs(id,institute_id,invoice_id,amount_written_off,reason,writeoff_date,reference_no,created_at) VALUES(1,7,1,2500,'Uncollectible','2026-04-02','WO1','2026-04-02')")

def scenario(c):
    aid=create(c);admissions.link_item(c,7,10,1,aid,'2026-04-01','New purchase')
    modules={r['module_name']:r['id'] for r in c.execute('SELECT * FROM admission_modules').fetchall()}
    admissions.assign(c,7,10,aid,modules['Basics'],1,'2026-04-01',reason='Basics at Head Office')
    pay(c,4000,'2026-04-01',1,'first')
    c.execute('UPDATE students SET branch_id=2 WHERE id=1')
    admissions.assign(c,7,10,aid,modules['Tally'],2,'2026-05-01',reason='Tally at Hoskote')
    pay(c,6000,'2026-05-01',2,'second')
    assert c.execute('SELECT branch_id FROM invoices WHERE id=1').fetchone()['branch_id']==1
    assert admissions.owned(c,'course_admissions',aid,7)['origin_branch_id']==1
    assert ledger.totals(c,7,1)['outstanding']==0
    origin=build(c,7,'origin-collections','2026-04-01','2026-05-31','2026-05-31')
    assert origin['totals']['collected_paise']==1000000 and {r['branch_id'] for r in origin['rows']}=={1}
    local=build(c,7,'collections','2026-04-01','2026-05-31','2026-05-31')
    assert {r['branch_id']:r['collected_paise'] for r in local['rows']}=={1:400000,2:600000}
    assert build(c,7,'admissions','2026-04-01','2026-05-31','2026-05-31')['totals']['admissions']==1

def test_transfer_and_payments_at_both_branches(connection):
    c=connection();scenario(c);c.close()

def test_multi_course_multiple_invoices_discount_once(connection):
    c=connection();dfa=create(c);cc=create(c,2,'2026-05-01',2)
    for item,aid in [(1,dfa),(2,dfa),(3,cc)]:admissions.link_item(c,7,10,item,aid,'2026-05-01','Reviewed linkage')
    pay(c,3000,'2026-05-10',1,'split',2)
    r=build(c,7,'origin-collections','2026-05-01','2026-05-31','2026-05-31')
    assert {x['admission_id']:x['collected_paise'] for x in r['rows']}=={dfa:50000,cc:250000}
    assert build(c,7,'sales','2026-04-01','2026-05-31','2026-05-31')['totals']['net_sales_paise']==1600000

def test_partial_writeoff_durable_reversal_and_historical_balance(connection):
    c=connection();writeoff(c);pay(c,1000,'2026-04-03',1,'partial')
    assert ledger.totals(c,7,1)['outstanding']==650000
    assert c.execute('SELECT id FROM invoices i WHERE i.id=1 AND '+ledger.collectible_sql(c)).fetchone()
    ledger.adjust(c,7,10,1,'writeoff_reversal',2500,'2026-05-01','Incorrect write-off',writeoff_id=1,request_key='reverse')
    assert ledger.totals(c,7,1)['outstanding']==900000
    assert c.execute('SELECT COUNT(*) n FROM bad_debt_writeoffs').fetchone()['n']==1
    assert ledger.totals(c,7,1,'2026-04-30')['outstanding']==650000

def test_cancellation_refund_and_reversal_preserve_originals(connection):
    c=connection();aid=create(c);admissions.link_item(c,7,10,1,aid,'2026-04-01','Purchase');pay(c,4000,'2026-04-05',1,'pay')
    receipt=c.execute('SELECT id FROM receipts').fetchone()['id']
    cancel=ledger.adjust(c,7,10,1,'cancellation',10000,'2026-05-01','Course cancelled',request_key='cancel')
    assert ledger.totals(c,7,1)['credit']==400000
    assert ledger.totals(c,7,1,'2026-04-30')['outstanding']==600000
    ledger.adjust(c,7,10,1,'refund',4000,'2026-05-02','Refund course',receipt_id=receipt,request_key='refund')
    assert ledger.totals(c,7,1)['outstanding']==ledger.totals(c,7,1)['credit']==0
    assert build(c,7,'sales','2026-04-01','2026-04-30','2026-04-30')['totals']['net_sales_paise']==1000000
    assert build(c,7,'sales','2026-05-01','2026-05-31','2026-05-31')['totals']['net_sales_paise']==-400000
    assert build(c,7,'collections','2026-04-01','2026-05-31','2026-05-31')['totals']['collected_paise']==0
    assert c.execute('SELECT total_amount FROM invoices WHERE id=1').fetchone()['total_amount']==10000
    ledger.adjust(c,7,10,1,'adjustment_reversal',10000,'2026-06-01','Resumed',reverse_of=cancel,request_key='restore')
    assert ledger.totals(c,7,1)['outstanding']==1000000

def test_origin_correction_after_cutoff_and_transfer_dates(connection):
    c=connection();aid=create(c);m=c.execute("SELECT id FROM admission_modules WHERE module_name='Basics'").fetchone()['id']
    old=admissions.assign(c,7,10,aid,m,1,'2026-04-01',reason='Start')
    admissions.assign(c,7,10,aid,m,3,'2026-05-01',previous=old,reason='Transfer')
    assert c.execute('SELECT start_date FROM training_assignments WHERE id=?',(old,)).fetchone()['start_date']=='2026-04-01'
    admissions.correct(c,7,10,aid,{'origin_branch_id':2},'Confirmed correction','2026-06-01')
    assert admissions.as_of(c,7,'2026-04-30')[0]['origin_branch_id']==1
    assert admissions.as_of(c,7,'2026-06-30')[0]['origin_branch_id']==2
    with pytest.raises(ValueError):admissions.assign(c,7,10,aid,m,8,'2026-06-01',reason='Wrong tenant')

def test_legacy_collection_unresolved_and_advance_allocation(connection):
    c=connection()
    c.execute("INSERT INTO receipts(institute_id,receipt_no,invoice_id,receipt_date,amount_received,payment_mode,created_by,created_at) VALUES(7,'LEGACY',1,'2026-04-02',100,'cash',10,'2026-04-02')")
    pid=pay(c,500,'2026-04-03',2,'advance',None)
    assert build(c,7,'collections','2026-04-01','2026-04-30','2026-04-30','unresolved')['totals']['collected_paise']==10000
    collections.allocate(c,7,10,pid,1,200,request_key="allocation")
    for kind in ['collections','origin-collections']:
        assert build(c,7,kind,'2026-04-01','2026-04-30','2026-04-30')['totals']['collected_paise']==60000

def test_idempotency_concurrency_references_and_foreign_keys(connection):
    def run(key):
        c=connection()
        try:
            ledger.begin(c);pid=collections.payment(c,7,10,1,6000,'2026-04-02',1,'branch','upi','REF',key,invoice_id=1);c.commit();return pid
        except ValueError:c.rollback();return None
        finally:c.close()
    first=run('key');assert first==run('key')
    with ThreadPoolExecutor(2) as pool:assert list(pool.map(run,['duplicate1','duplicate2']))==[None,None]
    c=connection()
    with pytest.raises(ValueError):admissions.admission(c,7,10,8,1,'2026-04-01',1)
    with pytest.raises(ValueError):collections.payment(c,7,10,1,1,'2026-04-01',8,'branch','cash',None,'foreign')

def test_recovery_preview_never_guesses_or_writes(connection):
    c=connection();aid=create(c);writeoff(c)
    c.execute("INSERT INTO expenses(institute_id,expense_date,branch_id,category_id,title,amount,payment_mode,reference_no,created_by,created_at) VALUES(7,'2026-04-02',1,1,'Bad Debt Write-off - INV1',2500,'cash','WO1',10,'2026-04-02')")
    before=c.total_changes;assert preview(c,7)['proposals'][0]['proposed'] is None
    p=preview(c,7,{aid:dict(original_admission_creator_id=10,evidence='signed form 123')})
    assert p['proposals'][0]['proposed']==1 and p['proposals'][1]['entity']=='noncash_writeoff_expense'
    assert c.total_changes==before

def test_ui_reports_and_api_isolation(connection,monkeypatch):
    monkeypatch.setattr(routes,'get_conn',connection);monkeypatch.setattr(routes,'get_current_institute_id',lambda:7)
    app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='test')
    app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),FileSystemLoader('templates')])
    app.jinja_env.globals['csrf_token']=lambda:'test'
    app.register_blueprint(routes.accuracy_bp,url_prefix='/accuracy')
    app.add_url_rule('/login',endpoint='core.login',view_func=lambda:'login')
    app.add_url_rule('/dashboard',endpoint='core.dashboard',view_func=lambda:'dashboard')
    client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7)
    assert client.get('/accuracy/').status_code==200
    assert 'Foreign' not in client.get('/accuracy/').text
    assert client.get('/accuracy/reports/admissions').status_code==200
    assert client.get('/accuracy/reports/admissions?branch=8').status_code==400
    assert client.post('/accuracy/action',json=dict(operation='admission',student_id=8,course_id=1,admission_date='2026-04-01',branch_id=1)).status_code==400

def test_mysql_migration_and_transfer(mysql_server,monkeypatch):
    from config import Config
    monkeypatch.setattr(Config,'DB_TYPE','mysql')
    name='accuracy_'+uuid.uuid4().hex[:12];admin=pymysql.connect(**mysql_server)
    with admin.cursor() as cur:cur.execute('CREATE DATABASE '+name)
    admin.close();c=MySQLConnectionWrapper(pymysql.connect(**mysql_server,database=name))
    try:
        seed(c,True);scenario(c);c.commit();migration(c)
        assert ledger.totals(c,7,1)['outstanding']==0
    finally:c.close()



def test_canonical_installments_ignore_stale_paid_cache_and_reminders(connection):
    from modules.billing.auto_reminders import _load_due_installments
    from datetime import date
    c=connection();writeoff(c);pay(c,1000,'2026-04-03',1,'partial')
    c.execute("UPDATE installment_plans SET status='paid',amount_paid=amount_due")
    rows=_load_due_installments(c.cursor(),date(2026,4,1))
    assert len(rows)==1 and rows[0]['balance_due']==500
    assert sum(r['due'] for r in c.execute('SELECT '+ledger.installment_balance_sql(c)+' due FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id').fetchall())==6500


def test_allocation_retry_and_advance_refund(connection):
    c=connection();pid=pay(c,500,'2026-04-03',2,'advance',None)
    first=collections.allocate(c,7,10,pid,1,200,request_key='allocate')
    assert collections.allocate(c,7,10,pid,1,200,request_key='allocate')==first
    collections.return_advance(c,7,10,pid,300,'2026-04-04','Advance returned','return')
    assert build(c,7,'collections','2026-04-01','2026-04-30','2026-04-30')['totals']['collected_paise']==20000
    with pytest.raises(ValueError):collections.allocate(c,7,10,pid,1,1,request_key='more')


def test_flagged_exports_and_related_paths_are_tenant_scoped(connection,monkeypatch):
    from modules.reports import routes as reports
    monkeypatch.setattr(reports,'get_conn',connection)
    monkeypatch.setattr(reports,'get_current_institute_id',lambda **kw:7)
    app=Flask('exports');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(reports.reports_bp,url_prefix='/reports')
    client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7)
    for path in ['/reports/export-students-detailed','/reports/daily/download?date=2026-04-01','/reports/export/courses']:
        response=client.get(path)
        assert response.status_code==200,(path,response.status_code)
        assert b'Foreign' not in response.data
    assert client.get('/reports/daily/download?branch_id=8').status_code==403


def test_writeoff_posting_period_differs_from_admission_cohort(connection):
    c=connection();aid=create(c);admissions.link_item(c,7,10,1,aid,'2026-04-01','Admission')
    writeoff(c);c.execute("UPDATE bad_debt_writeoffs SET writeoff_date='2026-05-01'")
    assert build(c,7,'writeoffs-posted','2026-05-01','2026-05-31','2026-05-31')['totals']['written_off_paise']==250000
    assert build(c,7,'writeoffs-posted','2026-04-01','2026-04-30','2026-05-31')['rows']==[]
    assert build(c,7,'writeoffs-cohort','2026-04-01','2026-04-30','2026-05-31')['totals']['written_off_paise']==250000

def test_existing_dashboard_null_branch_and_cancellations(connection,monkeypatch):
    from modules.billing import routes as billing
    c=connection();c.execute('UPDATE invoices SET branch_id=NULL WHERE id=2');c.commit();c.close()
    monkeypatch.setattr(billing,'get_conn',connection)
    monkeypatch.setattr(billing,'get_current_institute_id',lambda **kw:7)
    captured={}
    monkeypatch.setattr(billing,'render_template',lambda template,**data:captured.update(data) or 'ok')
    app=Flask('billing-dashboard');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(billing.billing_bp,url_prefix='/billing');client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7,branch_id=1)
    for branch,expected in [('1',10000),('2',0),('unresolved',6000)]:
        assert client.get('/billing/dashboard?branch_id='+branch).status_code==200
        assert captured['total_sales']==expected
    c=connection();c.execute("UPDATE invoices SET status='cancelled' WHERE id=1");c.commit();c.close()
    client.get('/billing/dashboard?branch_id=1');assert captured['total_sales']==0

def test_invoice_creation_links_explicit_new_and_existing_admissions(connection,monkeypatch):
    from modules.billing import routes as billing
    monkeypatch.setattr(billing,'get_conn',connection)
    monkeypatch.setattr(billing,'get_current_institute_id',lambda **kw:7)
    monkeypatch.setattr(billing,'_provision_program_access_for_course',lambda *a:None)
    monkeypatch.setattr(billing,'_auto_enable_portal',lambda *a:None)
    monkeypatch.setattr(billing,'_send_invoice_sms_link',lambda *a,**kw:{'success':True,'phone':'synthetic'})
    monkeypatch.setattr(billing,'log_activity',lambda *a,**kw:None)
    app=Flask('invoice-create');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(billing.billing_bp,url_prefix='/billing');client=app.test_client()
    def post(mode,aid=''):
        with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7,branch_id=1,invoice_form_token='test'+mode)
        response=client.post('/billing/invoice/new',data={'form_token':'test'+mode,'student_id':'1','invoice_date':'2026-04-01','installment_type':'full',
            'full_due_date':'2026-04-15','invoice_branch_id':'1','admission_mode':mode,'item_course_id[]':'1','item_course_name[]':'DFA','item_qty[]':'1','item_rate[]':'12000','item_discount[]':'2000','item_admission_id[]':aid})
        assert response.status_code==302 and '/billing/invoice/' in response.location,response.location
    post('new')
    c=connection();aid=c.execute('SELECT id FROM course_admissions').fetchone()['id'];c.close()
    post('existing',aid)
    c=connection()
    assert c.execute('SELECT COUNT(*) n FROM course_admissions').fetchone()['n']==1
    assert c.execute('SELECT COUNT(*) n FROM invoice_item_admissions WHERE admission_id=?',(aid,)).fetchone()['n']==2
    assert c.execute('SELECT COUNT(*) n FROM admission_modules WHERE admission_id=?',(aid,)).fetchone()['n']==2

def test_installment_correction_keeps_prior_aging_and_requires_reason(connection):
    c=connection()
    with pytest.raises(ValueError):ledger.correct_installment(c,7,10,1,'2026-06-01',4000,'','', '2026-05-01')
    ledger.correct_installment(c,7,10,1,'2026-06-01',4000,'Rescheduled','Student request','2026-05-01')
    assert ledger.installments_as_of(c,7,1,'2026-04-30')[0]['due_date']=='2026-04-01'
    assert ledger.installments_as_of(c,7,1,'2026-05-31')[0]['due_date']=='2026-06-01'

def test_import_rejects_double_discount_and_keeps_creator_provenance(connection,monkeypatch):
    import io
    from modules.reports import routes as reports
    monkeypatch.setattr(reports,'get_conn',connection);monkeypatch.setattr(reports,'get_current_institute_id',lambda **kw:7)
    monkeypatch.setattr(reports,'log_activity',lambda *a,**kw:None)
    app=Flask('imports');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(reports.reports_bp,url_prefix='/reports');client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7)
    data='invoice_number,student_id,invoice_date,subtotal,discount_type,discount_value,discount_amount,total_amount,installment_type,notes,status,created_by,branch_id\nBAD,1,2026-04-01,12000,fixed,2000,2000,8000,full,,unpaid,10,1\n'
    response=client.post('/reports/upload',data={'table_name':'invoices','file':(io.BytesIO(data.encode()),'import.csv')},content_type='multipart/form-data')
    assert response.status_code==302
    c=connection();assert c.execute("SELECT COUNT(*) n FROM invoices WHERE invoice_no='BAD'").fetchone()['n']==0

@pytest.mark.parametrize('with_timestamp',[True,False])
def test_gateway_partial_writeoff_preserves_payment_time_and_unknown_physical_location(release_connection,monkeypatch,with_timestamp):
    from services import cashfree_payments as gateway
    c=release_connection()
    is_mysql=hasattr(c,'_conn')
    if is_mysql:
        for filename in ['20261029_cashfree_sandbox.sql','20261029_cashfree_student_payment_links.sql']:
            sql='\n'.join(line for line in (Path('migrations')/filename).read_text().splitlines() if not line.startswith('--'))
            for statement in sql.split(';'):
                if statement.strip():
                    with c._conn.cursor() as cur:cur.execute(statement)
    else:gateway.init_sqlite_schema(c)
    writeoff(c)
    order='cf_live_7_'+uuid.uuid4().hex
    c.execute("INSERT INTO cashfree_orders(order_id,institute_id,student_id,invoice_id,created_by,amount_paise,request_fingerprint,status,created_at,updated_at) VALUES(?,7,1,1,10,750000,'test','ACTIVE','2026-04-01','2026-04-01')",(order,))
    c.commit();c.close()
    monkeypatch.setattr(gateway,'get_conn',release_connection)
    monkeypatch.setattr(gateway,'_now',lambda:'2026-05-01T10:00:00+05:30')
    app=Flask('gateway');app.config.update(DB_TYPE='mysql' if is_mysql else 'sqlite',CASHFREE_MODE='production',CASHFREE_INSTITUTE_ID=7)
    with app.app_context():
        data={'cf_payment_id':'PAY1','payment_method':{'upi':{}}}
        if with_timestamp:data['payment_completion_time']='2026-05-01T10:00:00+05:30'
        first=gateway._post_receipt(order,data)
        assert first['paid'] and gateway._post_receipt(order,data)['receipt_id']==first['receipt_id']
    c=release_connection();p=c.execute('SELECT * FROM collection_payments').fetchone()
    assert p['payment_date']=='2026-05-01' and p['collection_branch_id'] is None and p['payment_channel']=='online'
    assert c.execute('SELECT COUNT(*) n FROM receipts').fetchone()['n']==1
    assert ledger.totals(c,7,1)['outstanding']==0
    assert p['date_source']==('gateway_timestamp' if with_timestamp else 'posting_fallback')
    c.close()

def test_later_backdated_status_does_not_leak_future_origin_change(connection,monkeypatch):
    monkeypatch.setattr(ledger,'now',lambda:'2026-11-07T12:00:00.000000+05:30')
    c=connection();aid=create(c)
    admissions.correct(c,7,10,aid,{'origin_branch_id':2},'Origin corrected','2026-06-01')
    admissions.correct(c,7,10,aid,{'status':'completed'},'Completion recorded late','2026-05-01')
    old=admissions.as_of(c,7,'2026-05-31')[0]
    assert old['origin_branch_id']==1 and old['status']=='completed'




def test_advance_allocation_cutoff_does_not_rewrite_earlier_outstanding(connection):
    c=connection();aid=create(c);admissions.link_item(c,7,10,1,aid,'2026-04-01','Purchase')
    pid=pay(c,500,'2026-04-03',2,'advance',None)
    collections.allocate(c,7,10,pid,1,200,request_key='later-allocation',allocation_date='2026-05-01')
    assert ledger.totals(c,7,1,'2026-04-30')['outstanding']==1000000
    assert ledger.totals(c,7,1,'2026-05-31')['outstanding']==980000
    early=build(c,7,'origin-collections','2026-04-01','2026-04-30','2026-04-30')
    assert early['totals']['collected_paise']==50000 and all(r['branch_id'] is None for r in early['rows'])
    later=build(c,7,'origin-collections','2026-04-01','2026-04-30','2026-05-31')
    assert later['totals']['collected_paise']==50000 and any(r['branch_id']==1 for r in later['rows'])

def test_training_completion_and_legacy_enrollment_cannot_bypass_history(connection,monkeypatch):
    from modules.billing import routes as billing
    c=connection();aid=create(c);m=c.execute("SELECT id FROM admission_modules WHERE module_name='Basics'").fetchone()['id']
    assignment=admissions.assign(c,7,10,aid,m,1,'2026-04-01',reason='Start')
    admissions.close_assignment(c,7,10,assignment,'2026-04-30','Module completed')
    assert c.execute('SELECT start_date,end_date FROM training_assignments WHERE id=?',(assignment,)).fetchone()[:]==('2026-04-01','2026-04-30')
    assert c.execute('SELECT status FROM student_batches WHERE student_id=1 AND batch_id=1').fetchone()['status']=='completed'
    c.commit();c.close()
    monkeypatch.setattr(billing,'get_conn',connection)
    monkeypatch.setattr(billing,'get_current_institute_id',lambda **kw:7)
    app=Flask('training-guard');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(billing.billing_bp,url_prefix='/billing');client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7)
    assert client.post('/billing/student/1/add-to-batch',data={'batch_id':2}).status_code==409

@pytest.mark.parametrize('invoice_total,receipt,writeoff,schedule,expected',[
    (22000,10000,12000,[22000,6000,6000],0),
    (15300,5000,7225,[8375,5000,5300],3075),
    (7500,7500,0,[7500,3000,4000],0),
])
def test_oversized_legacy_schedules_cannot_manufacture_dues(release_connection,invoice_total,receipt,writeoff,schedule,expected):
    from modules.billing.auto_reminders import _load_due_installments
    from services.payment_links import amounts
    from datetime import date
    c=release_connection()
    c.execute('UPDATE invoices SET total_amount=? WHERE id=1',(invoice_total,))
    c.execute('DELETE FROM installment_plans WHERE invoice_id=1')
    for no,amount in enumerate(schedule,1):
        c.execute("INSERT INTO installment_plans(invoice_id,installment_no,due_date,amount_due,created_at) VALUES(1,?,'2026-04-01',?,'2026-04-01')",(no,amount))
    if receipt:
        c.execute("INSERT INTO receipts(institute_id,receipt_no,invoice_id,receipt_date,amount_received,created_by,created_at) VALUES(7,'OLD',1,'2026-04-01',?,10,'2026-04-01')",(receipt,))
    if writeoff:
        c.execute("INSERT INTO bad_debt_writeoffs(institute_id,invoice_id,amount_written_off,reason,writeoff_date,created_at) VALUES(7,1,?,'legacy','2026-04-01','2026-04-01')",(writeoff,))
    values=c.execute('SELECT '+ledger.installment_balance_sql(c)+' due FROM installment_plans ip JOIN invoices i ON i.id=ip.invoice_id WHERE i.id=1').fetchall()
    assert sum(float(r['due']) for r in values)==expected
    assert ledger.totals(c,7,1)['outstanding']==expected*100
    assert sum(float(r['balance_due']) for r in _load_due_installments(c.cursor(),date(2026,4,1)))==expected
    inv=dict(c.execute('SELECT * FROM invoices WHERE id=1').fetchone())
    assert amounts(c,inv)['balance_paise']==expected*100
    report=build(c,7,'outstanding','2026-04-01','2026-05-31','2026-05-31')
    assert sum(r.get('outstanding_paise',0) for r in report['rows'] if r['invoice_id']==1)==expected*100
    c.close()


def test_csv_receipt_metadata_unknowns_atomicity_and_exports(release_connection,monkeypatch):
    import io,csv
    from modules.reports import routes as reports
    from modules.billing import routes as billing
    monkeypatch.setattr(reports,'get_conn',release_connection)
    monkeypatch.setattr(reports,'get_current_institute_id',lambda **kw:7)
    monkeypatch.setattr(reports,'log_activity',lambda *a,**kw:None)
    c=release_connection()
    if hasattr(c,'_conn'):
        with c._conn.cursor() as cur:cur.execute('CREATE TABLE institutes(id BIGINT PRIMARY KEY,name VARCHAR(100))')
    else:c.execute('CREATE TABLE institutes(id INTEGER PRIMARY KEY,name TEXT)')
    c.execute("INSERT INTO institutes VALUES(7,'Synthetic'),(8,'Foreign')");c.commit();c.close()
    app=Flask('receipt-imports');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(reports.reports_bp,url_prefix='/reports');client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7,branch_id=1)
    headers='receipt_number,invoice_id,payment_date,amount_received,payment_mode,collection_branch_id,payment_channel,payment_reference,notes\n'
    content=headers+'CSV1,1,2026-04-02,1000,upi,2,branch,UPI-001,Confirmed source\nCSV2,1,,500,,,,,Historical unknowns\nBAD,1,2026-04-03,200,cash,8,branch,,Wrong tenant\nDUPREF,1,2026-04-03,200,upi,2,branch,UPI-001,Duplicate\n'
    response=client.post('/reports/upload',data={'table_name':'receipts','file':(io.BytesIO(content.encode()),'import.csv')},content_type='multipart/form-data')
    assert response.status_code==302
    # Replay is idempotent, and a conflict cannot overwrite the existing row.
    client.post('/reports/upload',data={'table_name':'receipts','file':(io.BytesIO(content.encode()),'import.csv')},content_type='multipart/form-data')
    c=release_connection();ps=c.execute('SELECT * FROM collection_payments ORDER BY payment_date DESC').fetchall()
    assert len(ps)==2 and c.execute('SELECT COUNT(*) n FROM receipts').fetchone()['n']==2
    assert ps[0]['collection_branch_id']==2 and ps[0]['payment_date']=='2026-04-02' and ps[0]['payment_reference']=='UPI-001'
    assert ps[1]['collection_branch_id'] is None and ps[1]['payment_channel']=='unresolved' and ps[1]['date_source']=='import_unknown'
    assert ps[1]['payment_reference'] is None and ps[1]['payment_date']==''
    assert ledger.totals(c,7,1)['outstanding']==850000
    sql=c.execute('SELECT '+ledger.outstanding_sql(c)+' due FROM invoices i WHERE id=1').fetchone()['due']
    assert float(sql)==8500
    report=build(c,7,'collections','2026-04-01','2026-04-30','2026-04-30')
    assert report['totals']['collected_paise']==100000 and report['undated_payment_paise']==50000
    c.close()
    exported=client.get('/reports/export/receipts')
    assert exported.status_code==200 and b'Foreign' not in exported.data
    rows=list(csv.DictReader(io.StringIO(exported.data.decode('utf-8-sig'))))
    assert rows[0]['collection_branch_id']=='2' and rows[0]['payment_reference']=='UPI-001'
    assert rows[1]['payment_channel']=='unresolved' and rows[1]['payment_date']==''
    assert client.get('/reports/export/invoices').status_code==200
    daily=client.get('/reports/daily/download?date=2026-04-02&branch_id=2')
    assert daily.status_code==200 and b'CSV1' in daily.data and b'CSV2' not in daily.data
    assert b'Collection branch' in daily.data and b'Hoskote' in daily.data


@pytest.mark.parametrize('changes',[
    {'payment_date':'bad'},{'payment_date':'2999-01-01'},{'collection_branch_id':'8'},
    {'payment_channel':'invented'},{'payment_reference':'X'*151},{'payment_mode':'invented'},
    {'receipt_date':'2026-04-03','payment_date':'2026-04-02'}, {'amount_received':'NaN'},
])
def test_import_rejects_invalid_metadata(release_connection,changes):
    c=release_connection()
    row=dict(receipt_number='IMPORT',invoice_id=1,payment_date='2026-04-02',amount_received='100',payment_mode='cash')
    row.update(changes)
    with pytest.raises(ValueError):collections.import_receipt(c,7,10,row)
    assert c.execute('SELECT COUNT(*) n FROM receipts').fetchone()['n']==0
    c.close()


def test_credit_is_visible_separately_and_never_reduces_other_dues(release_connection,monkeypatch):
    c=release_connection();pay(c,10000,'2026-04-03',1,'paid')
    ledger.adjust(c,7,10,1,'fee_reduction',500,'2026-04-04','Confirmed fee reduction',request_key='reduce')
    report=build(c,7,'outstanding','2026-04-01','2026-05-31','2026-05-31')
    assert report['totals']['outstanding_paise']==600000 and report['totals']['credit_paise']==50000
    rows=c.execute('SELECT '+ledger.outstanding_sql(c)+' due,'+ledger.credit_sql(c)+' credit FROM invoices i WHERE institute_id=7').fetchall()
    assert sum(float(r['due']) for r in rows)==6000 and sum(float(r['credit']) for r in rows)==500
    cancel=ledger.adjust(c,7,10,1,'cancellation',9500,'2026-04-05','Cancelled',request_key='cancel-credit')
    t=ledger.totals(c,7,1);assert t['credit']==1000000 and t['outstanding']==0
    row=c.execute('SELECT '+ledger.credit_sql(c)+' credit FROM invoices i WHERE id=1').fetchone()
    assert float(row['credit'])==10000
    c.commit();c.close()
    from modules.billing import routes as billing
    monkeypatch.setattr(billing,'get_conn',release_connection)
    monkeypatch.setattr(billing,'get_current_institute_id',lambda **kw:7)
    captured={};monkeypatch.setattr(billing,'render_template',lambda template,**data:captured.update(data) or 'ok')
    app=Flask('credit-list');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(billing.billing_bp,url_prefix='/billing');client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7,branch_id=1)
    assert client.get('/billing/invoices').status_code==200
    row=next(r for r in captured['invoices'] if r['id']==1)
    assert float(row['outstanding_amount'])==0 and float(row['credit_amount'])==10000
    assert float(captured['overall_stats']['all_outstanding_amount'])==6000


def test_blank_modules_and_import_origin_provenance(release_connection):
    c=release_connection()
    aid=admissions.admission(c,7,10,1,1,'2026-04-01',1,modules=[''])
    assert {r['module_name'] for r in c.execute('SELECT module_name FROM admission_modules WHERE admission_id=?',(aid,)).fetchall()}=={'Basics','Tally'}
    recovered=admissions.admission(c,7,10,1,1,'2026-04-01',None,source='import',source_reference='Reviewed CSV batch ABC',modules=[''])
    row=admissions.owned(c,'course_admissions',recovered,7)
    assert row['origin_branch_id'] is None and row['original_creator_id'] is None and row['imported_by']==10
    c.close()


def test_writeoff_form_and_api_share_collectible_balance(release_connection,monkeypatch):
    from modules.baddebt import routes as baddebt
    c=release_connection();writeoff(c);pay(c,1000,'2026-04-03',1,'partial')
    c.execute("UPDATE invoices SET status='paid' WHERE id=1")
    c.commit();c.close()
    monkeypatch.setattr(baddebt,'get_conn',release_connection)
    monkeypatch.setattr(baddebt,'get_current_institute_id',lambda **kw:7)
    captured={};monkeypatch.setattr(baddebt,'render_template',lambda template,**data:captured.update(data) or 'ok')
    app=Flask('writeoff-form');app.config.update(TESTING=True,SECRET_KEY='test')
    app.register_blueprint(baddebt.baddebt_bp,url_prefix='/baddebt');client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=10,role='admin',institute_id=7)
    assert client.get('/baddebt/create?invoice_id=1').status_code==200
    assert float(captured['pre_selected_invoice']['balance_amount'])==6500
    assert client.get('/baddebt/api/get-invoice/1').json['balance']==6500
    assert client.get('/baddebt/api/get-invoice/8').status_code==404


def test_all_tables_export_cannot_include_global_or_foreign_accuracy_data(release_connection,monkeypatch):
    from modules.import_export import routes as exports
    c=release_connection()
    sql='CREATE TABLE platform_fixture_secrets (id INTEGER PRIMARY KEY,secret VARCHAR(100))'
    if hasattr(c,'_conn'):
        with c._conn.cursor() as cur:cur.execute(sql)
    else:c.execute(sql)
    c.execute("INSERT INTO platform_fixture_secrets VALUES(1,'GLOBAL-DO-NOT-EXPORT')")
    admissions.admission(c,7,10,1,1,'2026-04-01',1)
    admissions.admission(c,8,80,8,8,'2026-04-01',8)
    pay(c,100,'2026-04-01',1,'owned-payment')
    c.execute("INSERT INTO institute_settings(institute_id,receipt_prefix,created_at) VALUES(8,'FOREIGN/RCP','2026-04-01')")
    collections.payment(c,8,80,8,10,'2026-04-01',8,'branch','cash',None,'foreign-payment',invoice_id=8)
    c.execute("INSERT INTO attendance_records(student_id,batch_id,branch_id,attendance_date,status,created_at) VALUES(8,1,1,'2026-04-01','present','2026-04-01')")
    c.commit();c.close()
    monkeypatch.setattr(exports,'get_conn',release_connection)
    data=exports.get_all_tables_data(current_inst=7)
    assert 'platform_fixture_secrets' not in data
    for table in ['course_admissions','collection_payments','receipt_details','accuracy_audit']:
        assert data[table]['data'] and all(r['institute_id']==7 for r in data[table]['data'])
    assert data['attendance_records']['data']==[]


