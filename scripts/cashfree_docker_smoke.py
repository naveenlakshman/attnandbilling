"""Inspect and exercise Cashfree only inside the local Docker test environment."""

import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from config import Config
from db import get_conn


def local_connection():
    if (Config.APP_ENV != 'development' or Config.DB_TYPE != 'mysql'
            or Config.MYSQL_HOST != 'local-db' or Config.MYSQL_DB != 'attn_billing_testing'):
        raise RuntimeError('This smoke helper only runs against the local Docker test database.')
    return get_conn()


def inspect():
    conn = local_connection()
    try:
        print(json.dumps({key:getattr(Config,key,None) for key in (
            'APP_ENV','DB_TYPE','MYSQL_HOST','MYSQL_PORT','MYSQL_DB','STORAGE_PROVIDER',
            'CASHFREE_API_URL','CASHFREE_INSTITUTE_ID')}, indent=2))
        print('credentials', json.dumps({key:bool(getattr(Config,key,None)) for key in (
            'CASHFREE_APP_ID','CASHFREE_SECRET_KEY')}))
        print('database', dict(conn.execute('SELECT DATABASE() db, @@hostname host').fetchone()))
        print('order_table', len(conn.execute("SHOW TABLES LIKE 'cashfree_orders'").fetchall()))
        print('users', [dict(row) for row in conn.execute('''
            SELECT id,institute_id,role,branch_id,is_active FROM users
            WHERE is_active=1 AND role='admin' ORDER BY id LIMIT 5
        ''').fetchall()])
        for table in ('students','invoices','installment_plans','receipts'):
            print(table, [dict(row) for row in conn.execute('''
                SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?
                ORDER BY ORDINAL_POSITION
            ''', (table,)).fetchall()])
    finally:
        conn.close()


def migrate():
    conn = local_connection()
    try:
        migration = Path(__file__).resolve().parents[1] / 'migrations/20261029_cashfree_sandbox.sql'
        sql = '\n'.join(line for line in migration.read_text().splitlines() if not line.startswith('--'))
        cursor = conn._conn.cursor()
        for statement in sql.split(';'):
            if statement.strip():
                cursor.execute(statement)
        conn.commit()
        print('Cashfree order-table migration applied to local Docker test database.')
    finally:
        conn.close()


def routing():
    conn = local_connection()
    try:
        print('platform_hosts',sorted(Config.PLATFORM_CONTROL_HOSTS))
        print('session_cookie',Config.SESSION_COOKIE_NAME,'secure',Config.SESSION_COOKIE_SECURE)
        print('tenant_domains',[dict(row) for row in conn.execute('''SELECT hostname,institute_id,status
            FROM institute_domains WHERE institute_id=1 ORDER BY id''').fetchall()])
    finally:
        conn.close()


def diagnose():
    local_connection().close()
    from app import app
    from services.cashfree import api_request
    session = requests.Session()
    session.trust_env = False
    response = session.get('http://127.0.0.1:8080/login',timeout=10)
    print('response_security_headers',json.dumps({key:response.headers.get(key) for key in (
        'Content-Security-Policy','Permissions-Policy','X-Frame-Options')}))
    conn = local_connection()
    try:
        orders = [dict(row) for row in conn.execute('''SELECT order_id,status,amount_paise,receipt_id
            FROM cashfree_orders WHERE invoice_id=491 AND institute_id=1 ORDER BY created_at DESC LIMIT 3''').fetchall()]
        print('local_orders',json.dumps(orders))
        print('invoice_receipts',conn.execute('SELECT COUNT(*) n FROM receipts WHERE invoice_id=491 AND institute_id=1').fetchone()['n'])
    finally:
        conn.close()
    with app.app_context():
        for order in orders:
            remote = api_request('GET','/orders/'+order['order_id'])
            payments = api_request('GET','/orders/'+order['order_id']+'/payments')
            print('provider_order',order['order_id'],'status',remote.get('order_status'),
                  'payment_attempts',[payment.get('payment_status') for payment in payments])


def prepare():
    conn = local_connection()
    try:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec='seconds')
        user = conn.execute('''SELECT id,branch_id FROM users WHERE institute_id=1
            AND role='admin' AND is_active=1 AND branch_id IS NOT NULL ORDER BY id LIMIT 1''').fetchone()
        if not user:
            raise RuntimeError('An existing active institute-1 branch administrator is required.')
        student = conn.execute("SELECT id FROM students WHERE institute_id=1 AND student_code='CF-SANDBOX-LOCAL'").fetchone()
        cur = conn.cursor()
        if not student:
            cur.execute('''INSERT INTO students (institute_id,student_code,full_name,phone,email,
                joined_date,status,branch_id,created_at)
                VALUES (1,'CF-SANDBOX-LOCAL','Cashfree Sandbox Test','9999999999',
                'cashfree-sandbox@example.com',?,'active',?,?)''', (now[:10],user['branch_id'],now))
            student_id = cur.lastrowid
        else:
            student_id = student['id']
        invoice = conn.execute('''SELECT id,invoice_no FROM invoices WHERE institute_id=1 AND student_id=?
            AND notes='Cashfree local sandbox smoke test' AND status='unpaid' ORDER BY id DESC LIMIT 1''', (student_id,)).fetchone()
        if not invoice:
            invoice_no = 'CF-SANDBOX-LOCAL-' + uuid.uuid4().hex[:8].upper()
            cur.execute('''INSERT INTO invoices (institute_id,invoice_no,student_id,invoice_date,
                subtotal,total_amount,installment_type,notes,status,created_by,branch_id,created_at)
                VALUES (1,?,?,?,10,10,'full','Cashfree local sandbox smoke test','unpaid',?,?,?)''',
                        (invoice_no,student_id,now[:10],user['id'],user['branch_id'],now))
            invoice_id = cur.lastrowid
            cur.execute('''INSERT INTO invoice_items (invoice_id,description,quantity,unit_price,
                line_total,created_at) VALUES (?,'Cashfree sandbox payment test',1,10,10,?)''', (invoice_id,now))
            cur.execute('''INSERT INTO installment_plans (invoice_id,installment_no,due_date,
                amount_due,amount_paid,status,created_at) VALUES (?,1,?,10,0,'pending',?)''', (invoice_id,now[:10],now))
        else:
            invoice_id,invoice_no = invoice['id'],invoice['invoice_no']
        conn.commit()
        fixture = dict(student_id=student_id,invoice_id=invoice_id,invoice_no=invoice_no,admin_user_id=user['id'])
        print('test_fixture',json.dumps(fixture))
        return fixture
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def smoke():
    # Existing accounts and passwords are unchanged. The ephemeral signed session
    # is used only for requests to loopback on the guarded local Docker database.
    local_connection().close()
    fixture = prepare()
    from app import app
    conn = local_connection()
    try:
        user = conn.execute('SELECT id,username,role,branch_id,can_view_all_branches FROM users WHERE id=?',
                            (fixture['admin_user_id'],)).fetchone()
        existing = conn.execute('''SELECT order_id FROM cashfree_orders WHERE institute_id=1
            AND invoice_id=? AND status='ACTIVE' ORDER BY created_at DESC LIMIT 1''', (fixture['invoice_id'],)).fetchone()
    finally:
        conn.close()
    serializer = app.session_interface.get_signing_serializer(app)
    session = requests.Session()
    session.trust_env = False
    # Raw localhost is the platform control plane. Use the existing local
    # institute domain while sending traffic directly to Docker loopback.
    session.headers['Host'] = 'globalit.localhost:8080'
    session.cookies.set(app.config['SESSION_COOKIE_NAME'], serializer.dumps(dict(
        user_id=user['id'],username=user['username'],full_name='Local Sandbox Smoke',role=user['role'],
        branch_id=user['branch_id'],can_view_all_branches=user['can_view_all_branches'],institute_id=1,
        membership_role='institute_admin')),domain='globalit.localhost',path='/')
    base = 'http://127.0.0.1:8080'
    page = session.get(f"{base}/billing/invoice/{fixture['invoice_id']}",timeout=15,allow_redirects=False)
    print('invoice_http',page.status_code)
    if page.is_redirect:
        print('invoice_redirect',page.headers.get('Location'))
    if page.status_code != 200:
        raise RuntimeError('Test invoice did not render; check web logs.')
    if app.config['SECURITY_HEADERS_ENABLED']:
        policy = page.headers.get('Content-Security-Policy','')
        form_sources = next((part.split()[1:] for part in policy.split(';')
                             if part.strip().startswith('form-action ')), [])
        print('invoice_form_action',form_sources)
        if 'https://sandbox.cashfree.com/pg/view/sessions/checkout' not in form_sources:
            raise RuntimeError('Invoice policy blocks the SDK checkout form submission.')
    if 'cashfree-payment-form' not in page.text:
        raise RuntimeError('Cashfree checkout form is missing from the test invoice.')
    token = re.search(r'name="csrf_token" value="([^"]+)"',page.text)
    if not token:
        raise RuntimeError('CSRF token is missing from the invoice.')
    headers = {'X-CSRFToken':token.group(1)}
    if existing:
        order_id = existing['order_id']
        print('create_order','reusing existing ACTIVE sandbox order')
    else:
        response = session.post(base+'/billing/cashfree/orders',headers=dict(headers,**{'Idempotency-Key':str(uuid.uuid4())}),
            json=dict(student_id=fixture['student_id'],invoice_id=fixture['invoice_id'],amount='10.00',
                      phone='9999999999',email='cashfree-sandbox@example.com',name='Cashfree Sandbox Test'),timeout=35)
        print('create_order_http',response.status_code)
        result = response.json()
        if response.status_code != 200:
            print('create_order_error',result.get('error','Unexpected provider response'))
            raise RuntimeError('Sandbox order creation failed.')
        order_id = result['order_id']
        print('payment_session_returned',bool(result.get('payment_session_id')))
    response = session.post(f'{base}/billing/cashfree/orders/{order_id}/verify',headers=headers,timeout=35)
    result = response.json()
    print('verify_http',response.status_code,'status',result.get('status'),'paid',result.get('paid'))
    if response.status_code != 200:
        print('verification_error',result.get('error','Unexpected provider response'))
        raise RuntimeError('Sandbox verification failed.')
    unsigned = session.post(base+'/billing/cashfree/webhook',json={'type':'PAYMENT_SUCCESS_WEBHOOK'},timeout=10)
    print('unsigned_webhook_http',unsigned.status_code)
    conn = local_connection()
    try:
        receipts = conn.execute('SELECT COUNT(*) n FROM receipts WHERE invoice_id=? AND institute_id=1',
                                (fixture['invoice_id'],)).fetchone()['n']
        print('test_invoice_receipts',receipts)
    finally:
        conn.close()
    print('checkout_url',f"http://globalit.localhost:8080/billing/invoice/{fixture['invoice_id']}?cashfree_order_id={order_id}")


if __name__ == '__main__':
    commands = {'inspect': inspect, 'migrate': migrate, 'routing': routing, 'diagnose': diagnose,
                'prepare': prepare, 'smoke': smoke}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit('Usage: python -m scripts.cashfree_docker_smoke inspect|migrate|routing|diagnose|prepare|smoke')
    commands[sys.argv[1]]()
