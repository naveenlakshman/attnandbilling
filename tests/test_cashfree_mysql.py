"""Opt-in integration test using an isolated temporary MySQL process.

Set CASHFREE_RUN_MYSQL_TESTS=1. No configured ERP database or credentials are used.
"""

import os
import shutil
import socket
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymysql
import pytest
from flask import Flask

from config import Config
from db import MySQLConnectionWrapper
from services import cashfree, cashfree_payments as payments


@pytest.fixture(scope='module')
def mysql_server(tmp_path_factory):
    if os.environ.get('CASHFREE_RUN_MYSQL_TESTS') != '1':
        pytest.skip('Set CASHFREE_RUN_MYSQL_TESTS=1 for the disposable MySQL integration test.')
    executable = shutil.which('mysqld')
    if not executable:
        pytest.skip('mysqld is unavailable.')
    directory = tmp_path_factory.mktemp('cashfree-mysql')
    datadir = directory / 'data'
    datadir.mkdir()
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    base = [executable, '--no-defaults', f'--basedir={Path(executable).parent.parent}',
            f'--datadir={datadir}']
    initialized = subprocess.run(base + ['--initialize-insecure'], capture_output=True,
                                 timeout=60, creationflags=flags)
    assert initialized.returncode == 0, initialized.stderr.decode(errors='replace')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with (directory / 'server.log').open('wb') as log:
        process = subprocess.Popen(base + ['--bind-address=127.0.0.1', f'--port={port}',
                                          '--mysqlx=0', '--console'],
                                   stdout=log, stderr=log, creationflags=flags)
        options = dict(host='127.0.0.1', port=port, user='root', password='',
                       charset='utf8mb4', connect_timeout=2, autocommit=False)
        try:
            deadline = time.monotonic() + 45
            while True:
                try:
                    admin = pymysql.connect(**options)
                    break
                except pymysql.Error:
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail((directory / 'server.log').read_text(errors='replace'))
                    time.sleep(0.25)
            admin.close()
            yield options
        finally:
            try:
                admin = pymysql.connect(**options)
                try:
                    with admin.cursor() as cursor:
                        cursor.execute('SHUTDOWN')
                finally:
                    admin.close()
                process.wait(timeout=15)
            except (pymysql.Error, subprocess.TimeoutExpired):
                process.terminate()
                process.wait(timeout=10)


def test_mysql_migration_and_concurrent_gateway_posting(mysql_server, monkeypatch):
    database = 'cashfree_test_' + uuid.uuid4().hex
    admin = pymysql.connect(**mysql_server)
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{database}`')
    finally:
        admin.close()

    def connect():
        return MySQLConnectionWrapper(pymysql.connect(**mysql_server, database=database))

    conn = connect()
    try:
        migration = Path(__file__).parents[1] / 'migrations/20261029_cashfree_sandbox.sql'
        sql = '\n'.join(line for line in migration.read_text().splitlines() if not line.startswith('--'))
        # Apply the actual migration with the raw cursor: the compatibility cursor
        # intentionally suppresses CREATE TABLE statements.
        for statement in sql.split(';'):
            if statement.strip():
                conn._conn.cursor().execute(statement)
        schema = '''
            CREATE TABLE students (id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL);
            INSERT INTO students VALUES (100, 1);
            CREATE TABLE invoices (id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL,
                student_id BIGINT NOT NULL, branch_id BIGINT, total_amount DECIMAL(12,2),
                status VARCHAR(32), updated_at VARCHAR(32));
            INSERT INTO invoices VALUES (101,1,100,3,1000,'unpaid',NULL);
            CREATE TABLE receipts (id BIGINT AUTO_INCREMENT PRIMARY KEY, receipt_no VARCHAR(128) UNIQUE,
                invoice_id BIGINT, institute_id BIGINT, receipt_date DATE, amount_received DECIMAL(12,2),
                payment_mode VARCHAR(32), notes TEXT, created_by BIGINT, created_at VARCHAR(32));
            CREATE TABLE bad_debt_writeoffs (id BIGINT PRIMARY KEY, invoice_id BIGINT,
                institute_id BIGINT, amount_written_off DECIMAL(12,2));
            CREATE TABLE installment_plans (id BIGINT PRIMARY KEY, invoice_id BIGINT,
                installment_no INT, amount_due DECIMAL(12,2), amount_paid DECIMAL(12,2),
                status VARCHAR(32), updated_at VARCHAR(32));
            INSERT INTO installment_plans VALUES (1,101,1,500,0,'pending',NULL), (2,101,2,500,0,'pending',NULL);
            CREATE TABLE institute_settings (institute_id BIGINT PRIMARY KEY, receipt_prefix VARCHAR(64));
            INSERT INTO institute_settings VALUES (1,'TEST/REC');
            CREATE TABLE institute_document_sequences (institute_id BIGINT, document_type VARCHAR(32),
                series_prefix VARCHAR(64), next_value BIGINT, created_at DATETIME, updated_at VARCHAR(32),
                UNIQUE(institute_id,document_type,series_prefix));
            CREATE TABLE activity_logs (id BIGINT AUTO_INCREMENT PRIMARY KEY, institute_id BIGINT,
                user_id BIGINT, branch_id BIGINT, action_type VARCHAR(32), module_name VARCHAR(32),
                record_id BIGINT, description TEXT, created_at VARCHAR(32));
        '''
        for statement in schema.split(';'):
            if statement.strip():
                conn._conn.cursor().execute(statement)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(payments, 'get_conn', connect)
    monkeypatch.setattr(Config, 'DB_TYPE', 'mysql')
    app = Flask(__name__)
    app.config.update(DB_TYPE='mysql', CASHFREE_APP_ID='test', CASHFREE_SECRET_KEY='fixture-secret',
                      CASHFREE_API_URL='https://sandbox.cashfree.com/pg')
    remote = {}

    def api(method, path, payload=None, idempotency_key=None):
        if method == 'POST':
            remote[payload['order_id']] = dict(payload, payment_session_id='test-session', order_status='PAID')
            return remote[payload['order_id']]
        order_id = path.split('/')[2]
        if path.endswith('/payments'):
            return [{'cf_payment_id': order_id, 'payment_amount': 750, 'payment_currency':'INR',
                     'payment_status':'SUCCESS', 'payment_method':{'upi':{}}}]
        return remote[order_id]

    monkeypatch.setattr(cashfree, 'api_request', api)
    actor = dict(id=10, institute_id=1, role='admin', can_view_all_branches=1, branch_id=3)
    details = dict(student_id=100, invoice_id=101, amount='750.00', phone='9876543210',
                   email='test@example.com', name='Test Student')
    with app.app_context():
        key = str(uuid.uuid4())
        orders = [payments.create_order(actor, details, key, lambda *args:'https://tenant.example/return')['order_id']]
        assert payments.create_order(actor, details, key, lambda *args:'https://tenant.example/return')['order_id'] == orders[0]
        orders.append(payments.create_order(actor, details, str(uuid.uuid4()),
                                             lambda *args:'https://tenant.example/return')['order_id'])

    def verify(order_id):
        with app.app_context():
            return payments.verify_order(order_id)

    # Both duplicate deliveries and distinct orders race for the same invoice.
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(verify, orders + orders))
    assert sorted(result['status'] for result in results) == ['PAID', 'PAID', 'REVIEW', 'REVIEW']
    conn = connect()
    try:
        rows = conn.execute('SELECT * FROM receipts').fetchall()
        assert len(rows) == 1 and str(rows[0]['amount_received']) == '750.00'
        assert rows[0]['receipt_no'] == 'TEST/REC/001'
        invoice = conn.execute('SELECT status FROM invoices WHERE id=101').fetchone()
        assert invoice['status'] == 'partially_paid'
        installments = conn.execute('SELECT amount_paid FROM installment_plans ORDER BY id').fetchall()
        assert [str(row['amount_paid']) for row in installments] == ['500.00','250.00']
        assert len(conn.execute('SELECT * FROM activity_logs').fetchall()) == 2
    finally:
        conn.close()
