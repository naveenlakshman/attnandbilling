import csv
import io
import sqlite3
import uuid
from decimal import Decimal
from pathlib import Path

import pymysql
import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from db import MySQLConnectionWrapper
from modules.reports import course_billing, routes
from mysql_fixture import mysql_server
from services.course_billing_reports import load_course_billing, split_amount


SCHEMA = '''
CREATE TABLE branches (id INTEGER PRIMARY KEY,institute_id INTEGER,branch_name VARCHAR(100));
CREATE TABLE courses (id INTEGER PRIMARY KEY,institute_id INTEGER,course_name VARCHAR(100));
CREATE TABLE students (id INTEGER PRIMARY KEY,institute_id INTEGER,full_name VARCHAR(150),student_code VARCHAR(50));
CREATE TABLE invoices (id INTEGER PRIMARY KEY,institute_id INTEGER,student_id INTEGER,branch_id INTEGER,invoice_no VARCHAR(50),invoice_date VARCHAR(30),total_amount DECIMAL(14,2),status VARCHAR(30));
CREATE TABLE invoice_items (id INTEGER PRIMARY KEY,invoice_id INTEGER,course_id INTEGER,line_total DECIMAL(14,2));
CREATE TABLE receipts (id INTEGER PRIMARY KEY,institute_id INTEGER,invoice_id INTEGER,receipt_no VARCHAR(50),receipt_date VARCHAR(30),amount_received DECIMAL(14,2),payment_mode VARCHAR(30));
INSERT INTO branches VALUES (7,7,'Hoskote'),(8,7,'Head Office'),(16,16,'Foreign branch');
INSERT INTO courses VALUES (71,7,'CCOM'),(72,7,'Python'),(73,7,'Free course'),(16,16,'Foreign course');
INSERT INTO students VALUES (701,7,'Anu Devi','REG-701'),(702,7,'Student <script>alert(1)</script>','REG-702'),(1601,16,'Foreign student','FOREIGN-REG');
INSERT INTO invoices VALUES (101,7,701,7,'INV-101','2026-01-10',1000,'paid'),(102,7,702,8,'INV-102','2026-02-01',500,'partially_paid'),(103,7,701,7,'CANCELLED','2026-01-11',100,'cancelled'),(104,7,701,7,'ZERO','2026-01-12',0,'paid'),(105,7,701,7,'LEGACY','2026-01-12',30,'paid'),(106,7,701,7,'BAD-MAP','2026-01-12',20,'paid'),(107,7,701,7,'FREE','2026-01-12',0,'paid'),(108,7,1601,7,'BAD-STUDENT','2026-01-12',111,'paid'),(109,16,1601,16,'FOREIGN-INVOICE','2026-01-12',999,'paid');
INSERT INTO invoice_items VALUES (1,101,71,300),(2,101,71,300),(3,101,72,400),(4,102,72,500),(5,103,71,100),(6,106,16,20),(7,107,73,0),(8,108,71,111),(9,109,16,999);
INSERT INTO receipts VALUES (1001,7,101,'REC-1001','2026-02-05T23:59:59',250,'cash'),(1002,7,101,'REC-1002','2026-02-06',100,'upi'),(1003,7,102,'REC-1003','2026-02-28',300,'card'),(1004,7,103,'REC-CANCELLED','2026-02-07',100,'cash'),(1005,7,105,'REC-LEGACY','2026-02-08',30,'cash'),(1006,7,106,'REC-BAD-MAP','2026-02-08',20,'cash'),(1007,16,109,'FOREIGN-RECEIPT','2026-02-08',999,'cash'),(1008,16,101,'BAD-TENANT-RECEIPT','2026-02-08',5000,'cash'),(1009,7,108,'BAD-STUDENT-RECEIPT','2026-02-08',111,'cash');
'''


def initialize(conn):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            if isinstance(conn, MySQLConnectionWrapper) and statement.strip().startswith('CREATE TABLE'):
                with conn._conn.cursor() as cur:
                    cur.execute(statement)
            else:
                conn.execute(statement)
    conn.commit()


@pytest.fixture()
def connect(tmp_path):
    path = tmp_path/'course-reports.db'
    def connection():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    conn = connection()
    initialize(conn)
    conn.close()
    return connection


@pytest.fixture()
def web(connect, monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='course-reports-test-only')
    app.jinja_loader = ChoiceLoader([
        DictLoader({'base.html':'{% block extra_css %}{% endblock %}{% block content %}{% endblock %}'}),
        FileSystemLoader(str(Path(__file__).resolve().parents[1]/'templates'))])
    monkeypatch.setattr(course_billing, 'get_conn', connect)
    monkeypatch.setattr(course_billing, 'get_current_institute_id', lambda **kwargs:7)
    monkeypatch.setattr(routes, 'get_conn', connect)
    monkeypatch.setattr(routes, 'get_current_institute_id', lambda **kwargs:7)
    app.register_blueprint(routes.reports_bp, url_prefix='/reports')
    app.add_url_rule('/login', endpoint='core.login', view_func=lambda:'login')
    app.add_url_rule('/dashboard', endpoint='core.dashboard', view_func=lambda:'dashboard')
    app.add_url_rule('/daily', endpoint='attendance.daily_report', view_func=lambda:'daily')
    app.add_url_rule('/invoice/<int:invoice_id>', endpoint='billing.invoice_view', view_func=lambda invoice_id:'invoice')
    app.add_url_rule('/receipt/<int:receipt_id>', endpoint='billing.receipt_view', view_func=lambda receipt_id:'receipt')
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=10, institute_id=7, role='admin', branch_id=7)
    return app, client


def load(connect, kind, **kwargs):
    conn = connect()
    try:
        return load_course_billing(conn, 7, kind, **kwargs)
    finally:
        conn.close()


def csv_rows(response):
    assert response.status_code == 200
    assert 'attachment' in response.headers['Content-Disposition']
    assert response.headers['Cache-Control'] == 'private, no-store'
    return list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))


def test_invoice_summary_uses_items_not_student_course_and_never_duplicates_invoices(connect):
    report = load(connect, 'invoices')
    by_course = {row['course_key']:row for row in report['summary']}
    assert by_course['71']['amount'] == Decimal('600.00')
    assert by_course['71']['invoice_count'] == 1
    assert by_course['72']['amount'] == Decimal('900.00')
    assert by_course['72']['invoice_count'] == 2
    assert by_course['unassigned']['amount'] == Decimal('50.00')
    assert by_course['73']['amount'] == 0
    assert report['totals'] == dict(amount=Decimal('1550.00'), transaction_count=6,
                                   invoice_count=6, student_count=2, course_count=3)
    assert sum(row['amount'] for row in report['summary']) == report['totals']['amount']


def test_each_receipt_is_split_by_course_value_and_totals_use_unique_counts(connect):
    report = load(connect, 'receipts')
    by_course = {row['course_key']:row for row in report['summary']}
    assert by_course['71']['amount'] == Decimal('310.00')
    assert by_course['72']['amount'] == Decimal('440.00')
    assert by_course['unassigned']['amount'] == Decimal('50.00')
    assert report['totals']['amount'] == Decimal('800.00')
    assert report['totals']['transaction_count'] == 6
    assert report['totals']['invoice_count'] == 5
    assert sum(row['transaction_count'] for row in report['summary']) == 8
    first = {row['course_id']:row['amount'] for row in report['details'] if row['transaction_id'] == 1001}
    assert first == {71:Decimal('150.00'),72:Decimal('100.00')}


def test_course_filter_applies_after_allocation_not_before(connect):
    report = load(connect, 'receipts', course_filter='71')
    assert report['totals']['amount'] == Decimal('310.00')
    assert report['totals']['transaction_count'] == 3
    assert all(row['course_id'] == 71 for row in report['details'])


def test_receipt_date_range_includes_payments_on_older_invoices_and_end_of_day(connect):
    report = load(connect, 'receipts', start_date='2026-02-05', end_exclusive='2026-02-06')
    assert report['totals']['amount'] == Decimal('250.00')
    assert report['totals']['transaction_count'] == 1
    invoice_report = load(connect, 'invoices', start_date='2026-02-05', end_exclusive='2026-02-06')
    assert not invoice_report['details']


def test_branch_filter_and_cancelled_invoice_handling(connect):
    assert load(connect, 'receipts', branch_id=8)['totals']['amount'] == Decimal('300.00')
    assert load(connect, 'invoices', include_cancelled=True)['totals']['amount'] == Decimal('1650.00')
    assert any(row['transaction_no'] == 'REC-CANCELLED' for row in load(connect, 'receipts')['details'])


def test_net_discounts_and_legacy_invoice_total_adjustments_reconcile(connect):
    conn = connect()
    conn.execute('UPDATE invoice_items SET line_total=200 WHERE id=1')
    conn.execute('UPDATE invoice_items SET line_total=0 WHERE id=2')
    conn.execute('UPDATE invoices SET total_amount=540 WHERE id=101')
    conn.commit(); conn.close()
    report = load(connect, 'invoices')
    invoice = {row['course_id']:row['amount'] for row in report['details'] if row['invoice_id'] == 101}
    assert invoice == {71:Decimal('180.00'),72:Decimal('360.00')}


@pytest.mark.parametrize('amount', [0,1,2,3,7,999,1000000000001,-1,-999])
def test_rounding_is_deterministic_and_preserves_every_paise(amount):
    first = split_amount(amount, {73:1,71:1,72:1})
    assert first == split_amount(amount, {71:1,72:1,73:1})
    assert sum(first.values()) == amount
    assert max(map(abs,first.values()))-min(map(abs,first.values())) <= 1


def test_zero_weights_do_not_invent_course_allocations():
    assert split_amount(100, {71:0,72:0}) == {None:100}
    assert split_amount(100, {}) == {None:100}
    assert split_amount(0, {71:0}) == {71:0}


@pytest.mark.parametrize('kind', ['invoices','receipts'])
def test_pages_render_escape_student_names_and_do_not_expose_foreign_data(web, kind):
    _, client = web
    response = client.get('/reports/course-wise/'+kind)
    assert response.status_code == 200
    assert 'Course summary' in response.text and 'Download details CSV' in response.text
    assert 'Foreign' not in response.text and 'BAD-STUDENT' not in response.text
    assert 'Student &lt;script&gt;' in response.text and 'Student <script>' not in response.text
    assert 'Unassigned / legacy items' in response.text
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_dashboard_exposes_both_reports(web):
    _, client = web
    page = client.get('/reports/')
    assert page.status_code == 200
    assert '/reports/course-wise/invoices' in page.text
    assert '/reports/course-wise/receipts' in page.text


@pytest.mark.parametrize('kind,expected', [('invoices','1550.00'),('receipts','800.00')])
@pytest.mark.parametrize('download', ['summary','details'])
def test_csv_matches_report_totals_without_foreign_rows(web, kind, expected, download):
    _, client = web
    rows = csv_rows(client.get('/reports/course-wise/'+kind+'?download='+download))
    amount_key = 'Course share received (INR)' if kind == 'receipts' else 'Net course invoiced (INR)'
    assert sum(Decimal(row[amount_key]) for row in rows) == Decimal(expected)
    assert not any('Foreign' in str(row) or 'BAD-STUDENT' in str(row) or 'BAD-TENANT' in str(row) for row in rows)


def test_exports_keep_course_branch_and_inclusive_date_filters(web):
    _, client = web
    rows = csv_rows(client.get('/reports/course-wise/receipts?download=details&course_id=71&branch_id=7&start_date=2026-02-05&end_date=2026-02-05'))
    assert len(rows) == 1 and rows[0]['Course share received (INR)'] == '150.00'
    assert rows[0]['Receipt no'] == 'REC-1001'


@pytest.mark.parametrize('query', ['course_id=16','branch_id=16','course_id=999','branch_id=999',
    'start_date=2026-02-30','end_date=20260101','start_date=2026-02-01&end_date=2026-01-01',
    'download=arbitrary','page=0','page=-1','page=²','course_id=71%20OR%201=1','end_date=9999-12-31'])
def test_invalid_and_foreign_filters_are_rejected(web, query):
    _, client = web
    assert client.get('/reports/course-wise/receipts?'+query).status_code == 400
    export_query = query if query.startswith('download=') else 'download=details&'+query
    assert client.get('/reports/course-wise/invoices?'+export_query).status_code == 400


@pytest.mark.parametrize('download', ['', '?download=summary', '?download=details'])
def test_reports_and_exports_require_admin_and_resolved_tenant(web, monkeypatch, download):
    _, client = web
    with client.session_transaction() as state:
        state.clear()
    response = client.get('/reports/course-wise/invoices'+download)
    assert response.status_code == 302 and response.location.endswith('/login')
    with client.session_transaction() as state:
        state.update(user_id=10,institute_id=7,role='staff')
    response = client.get('/reports/course-wise/invoices'+download)
    assert response.status_code == 302 and response.location.endswith('/dashboard')
    with client.session_transaction() as state:
        state['role'] = 'admin'
    monkeypatch.setattr(course_billing,'get_current_institute_id',lambda:None)
    assert client.get('/reports/course-wise/invoices'+download).status_code == 403


def test_pagination_does_not_truncate_csv_or_summary_totals(connect, web):
    conn = connect()
    conn.executemany('INSERT INTO receipts VALUES (?,7,101,?,\'2026-02-28\',1.01,\'cash\')',
                     [(2000+i,'EXTRA-'+str(i)) for i in range(60)])
    conn.commit(); conn.close()
    _, client = web
    page = client.get('/reports/course-wise/receipts?page=2')
    assert page.status_code == 200 and '51–100 of 128' in page.text
    assert '860.60' in page.text
    rows = csv_rows(client.get('/reports/course-wise/receipts?page=2&download=details'))
    assert len(rows) == 128
    assert sum(Decimal(row['Course share received (INR)']) for row in rows) == Decimal('860.60')


def test_csv_text_cannot_execute_spreadsheet_formulas(connect, web):
    conn = connect()
    conn.execute("UPDATE students SET full_name='=2+3' WHERE id=701")
    conn.execute("UPDATE courses SET course_name='@SUM(1,2)' WHERE id=71")
    conn.commit();conn.close()
    _, client = web
    rows = csv_rows(client.get('/reports/course-wise/receipts?download=details&course_id=71'))
    assert all(row['Student full name'] == "'=2+3" for row in rows)
    assert all(row['Course'] == "'@SUM(1,2)" for row in rows)
    assert all(Decimal(row['Course share received (INR)']) > 0 for row in rows)


def test_mysql_allocation_and_tenant_joins(mysql_server):
    database = 'course_reports_'+uuid.uuid4().hex[:12]
    admin = pymysql.connect(**mysql_server)
    with admin.cursor() as cur:
        cur.execute('CREATE DATABASE '+database)
    admin.close()
    conn = MySQLConnectionWrapper(pymysql.connect(**mysql_server,database=database))
    try:
        initialize(conn)
        report = load_course_billing(conn,7,'receipts',start_date='2026-02-05',end_exclusive='2026-02-06',course_filter='71')
        assert report['totals']['amount'] == Decimal('150.00')
        assert report['totals']['transaction_count'] == 1
    finally:
        conn.close()
