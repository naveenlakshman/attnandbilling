import base64
import hashlib
import hmac
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask
from flask_wtf.csrf import generate_csrf

from config import Config
from extensions import csrf, limiter
from modules.billing import cashfree_routes
from services import cashfree, cashfree_payments as payments


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    database = tmp_path / 'cashfree.db'

    def connect():
        conn = sqlite3.connect(database, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    conn = connect()
    conn.executescript('''
        CREATE TABLE users (id INTEGER PRIMARY KEY, institute_id INTEGER, role TEXT,
                            branch_id INTEGER, can_view_all_branches INTEGER, is_active INTEGER);
        INSERT INTO users VALUES (10, 1, 'staff', 3, 0, 1), (20, 2, 'admin', 8, 1, 1);
        CREATE TABLE students (id INTEGER PRIMARY KEY, institute_id INTEGER, full_name TEXT);
        INSERT INTO students VALUES (100, 1, 'Test Student'), (200, 2, 'Other Student');
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, institute_id INTEGER, student_id INTEGER,
                               branch_id INTEGER, total_amount NUMERIC, status TEXT, updated_at TEXT);
        INSERT INTO invoices VALUES (101, 1, 100, 3, 1000, 'unpaid', NULL),
                                    (201, 2, 200, 8, 2000, 'unpaid', NULL);
        ALTER TABLE invoices ADD COLUMN invoice_no TEXT;
        CREATE TABLE receipts (id INTEGER PRIMARY KEY, receipt_no TEXT UNIQUE, invoice_id INTEGER,
            institute_id INTEGER, receipt_date TEXT, amount_received NUMERIC, payment_mode TEXT,
            notes TEXT, created_by INTEGER, created_at TEXT);
        CREATE TABLE bad_debt_writeoffs (id INTEGER PRIMARY KEY, invoice_id INTEGER,
                                        institute_id INTEGER, amount_written_off NUMERIC);
        CREATE TABLE installment_plans (id INTEGER PRIMARY KEY, invoice_id INTEGER,
            installment_no INTEGER, amount_due NUMERIC, amount_paid NUMERIC, status TEXT, updated_at TEXT);
        INSERT INTO installment_plans VALUES (1,101,1,500,0,'pending',NULL),
                                             (2,101,2,500,0,'pending',NULL);
        CREATE TABLE institute_settings (institute_id INTEGER PRIMARY KEY, receipt_prefix TEXT);
        INSERT INTO institute_settings VALUES (1, 'TST/REC');
        CREATE TABLE institute_document_sequences (institute_id INTEGER, document_type TEXT,
            series_prefix TEXT, next_value INTEGER, created_at TEXT, updated_at TEXT,
            UNIQUE(institute_id,document_type,series_prefix));
        CREATE TABLE activity_logs (id INTEGER PRIMARY KEY, institute_id INTEGER, user_id INTEGER,
            branch_id INTEGER, action_type TEXT, module_name TEXT, record_id INTEGER,
            description TEXT, created_at TEXT);
    ''')
    payments.init_sqlite_schema(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(payments, 'get_conn', connect)
    monkeypatch.setattr(cashfree_routes, 'get_conn', connect)
    monkeypatch.setattr(cashfree_routes, 'get_current_institute_id', lambda: 1)
    monkeypatch.setattr(Config, 'DB_TYPE', 'sqlite')
    app = Flask(__name__, template_folder='../templates')
    app.config.update(TESTING=True, SECRET_KEY='cashfree-test', DB_TYPE='sqlite',
                      CASHFREE_APP_ID='TEST-fixture', CASHFREE_SECRET_KEY='fixture-secret',
                      CASHFREE_API_URL='https://sandbox.cashfree.com/pg', CASHFREE_INSTITUTE_ID=1,
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=True,
                      SECURITY_HEADERS_ENABLED=True, CONTENT_SECURITY_POLICY=Config.CONTENT_SECURITY_POLICY)
    csrf.init_app(app)
    limiter.init_app(app)
    bp = Blueprint('billing', __name__)
    cashfree_routes.register_cashfree_routes(bp)

    @bp.route('/invoice/<int:invoice_id>')
    def invoice_view(invoice_id):
        return 'invoice'

    @bp.route('/invoice/download/<token>')
    def invoice_public_download(token):
        return 'invoice download'

    app.register_blueprint(bp, url_prefix='/billing')

    @app.get('/token')
    def token():
        return generate_csrf()

    @app.after_request
    def default_security_headers(response):
        if app.config['SECURITY_HEADERS_ENABLED']:
            response.headers.setdefault('Content-Security-Policy', app.config['CONTENT_SECURITY_POLICY'])
        return response

    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(user_id=10, institute_id=1, role='staff')
    token = client.get('/token').text
    calls = []
    remote = {}

    def fake_api(method, path, payload=None, idempotency_key=None):
        calls.append((method, path, payload, idempotency_key))
        if method == 'POST':
            order = dict(payload, payment_session_id='test-session', order_status='ACTIVE')
            remote[payload['order_id']] = order
            return order
        order_id = path.split('/')[2]
        order = remote[order_id]
        if path.endswith('/payments'):
            return order.get('payments', [{
                'cf_payment_id': 'pay_' + order_id, 'payment_status': 'SUCCESS',
                'payment_amount': order['order_amount'], 'payment_currency': 'INR',
                'payment_method': {'upi': {}},
            }])
        return order

    http_api = cashfree.api_request
    monkeypatch.setattr(cashfree, 'api_request', fake_api)

    def post(path, data=None, key=None):
        headers = {'X-CSRFToken': token}
        if key:
            headers['Idempotency-Key'] = key
        return client.post(path, json=data, headers=headers)

    return SimpleNamespace(app=app, client=client, connect=connect, post=post, calls=calls, remote=remote,
                           http_api=http_api)


def details(**updates):
    return dict(student_id=100, invoice_id=101, amount='750.00', phone='9876543210',
                email='student@example.com', name='Test Student', **updates)


def create(sandbox, data=None, key=None):
    response = sandbox.post('/billing/cashfree/orders', data or details(), key)
    assert response.status_code == 200, response.json
    return response.json['order_id']


def verify(sandbox, order_id):
    return sandbox.post(f'/billing/cashfree/orders/{order_id}/verify')


def read(sandbox, sql):
    conn = sandbox.connect()
    try:
        return [dict(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def execute(sandbox, sql):
    conn = sandbox.connect()
    try:
        conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def webhook(sandbox, order_id, event_type='PAYMENT_SUCCESS_WEBHOOK', signed=True):
    body = json.dumps({'type': event_type, 'data': {'order': {'order_id': order_id}}})
    timestamp = '1793220000000'
    signature = base64.b64encode(hmac.new(b'fixture-secret', (timestamp + body).encode(), hashlib.sha256).digest()).decode()
    return sandbox.client.post('/billing/cashfree/webhook', data=body, content_type='application/json',
                               headers={'x-webhook-timestamp': timestamp,
                                        'x-webhook-signature': signature if signed else 'invalid'})


def test_order_persists_mapping_before_checkout_and_reuses_idempotency_key(sandbox):
    key = str(uuid.uuid4())
    order_id = create(sandbox, key=key)
    assert create(sandbox, key=key) == order_id
    assert len(sandbox.calls) == 1
    _, path, body, request_key = sandbox.calls[0]
    assert path == '/orders' and request_key == key
    assert body['order_currency'] == 'INR' and body['order_amount'] == 750
    assert body['customer_details']['customer_id'] == 'inst_1_student_100'
    assert order_id in body['order_meta']['return_url']
    assert not read(sandbox, 'SELECT * FROM receipts')
    assert read(sandbox, 'SELECT * FROM cashfree_orders')[0]['amount_paise'] == 75000


def test_idempotency_key_cannot_be_reused_for_changed_amount(sandbox):
    key = str(uuid.uuid4())
    create(sandbox, key=key)
    data = details(); data['amount'] = '50'
    assert sandbox.post('/billing/cashfree/orders', data, key).status_code == 409


@pytest.mark.parametrize('amount', ['0', '-1', '0.99', 'NaN', 'Infinity', '1.001', '1001', True, {}, '1e100000'])
def test_invalid_amounts_do_not_create_orders(sandbox, amount):
    data = details(); data['amount'] = amount
    assert sandbox.post('/billing/cashfree/orders', data).status_code in (400, 409)
    assert not sandbox.calls


@pytest.mark.parametrize('field,value', [('student_id', 200), ('invoice_id', 201), ('student_id', 101)])
def test_foreign_student_invoice_and_mismatched_student_are_rejected(sandbox, field, value):
    data = details(); data[field] = value
    assert sandbox.post('/billing/cashfree/orders', data).status_code == 404
    assert not sandbox.calls


def test_staff_cannot_pay_or_verify_another_branch(sandbox):
    order = create(sandbox)
    execute(sandbox, 'UPDATE invoices SET branch_id = 4 WHERE id = 101')
    assert sandbox.post('/billing/cashfree/orders', details()).status_code == 404
    assert verify(sandbox, order).status_code == 404


@pytest.mark.parametrize('status', ['cancelled', 'write_off', 'partially_written_off'])
def test_closed_invoices_cannot_create_orders(sandbox, status):
    execute(sandbox, f"UPDATE invoices SET status = '{status}' WHERE id = 101")
    assert sandbox.post('/billing/cashfree/orders', details()).status_code == 409


def test_student_only_request_resolves_one_invoice_but_rejects_ambiguity(sandbox):
    data = details(); data.pop('invoice_id')
    create(sandbox, data)
    execute(sandbox, "INSERT INTO invoices VALUES (102,1,100,3,100,'unpaid',NULL,NULL)")
    assert sandbox.post('/billing/cashfree/orders', data).status_code == 400


def test_verified_success_posts_one_receipt_and_allocates_installments(sandbox):
    order = create(sandbox)
    sandbox.remote[order]['order_status'] = 'PAID'
    result = verify(sandbox, order)
    assert result.status_code == 200 and result.json['paid']
    assert verify(sandbox, order).json == result.json
    assert webhook(sandbox, order).json == result.json
    receipts = read(sandbox, 'SELECT * FROM receipts')
    assert len(receipts) == 1 and receipts[0]['amount_received'] == 750
    assert receipts[0]['receipt_no'] == 'TST/REC/001'
    assert receipts[0]['institute_id'] == 1 and receipts[0]['created_by'] == 10
    assert 'SANDBOX Cashfree' in receipts[0]['notes']
    assert read(sandbox, 'SELECT status FROM invoices WHERE id=101')[0]['status'] == 'partially_paid'
    installments = read(sandbox, 'SELECT amount_paid, status FROM installment_plans ORDER BY id')
    assert installments == [{'amount_paid': 500, 'status': 'paid'}, {'amount_paid': 250, 'status': 'partially_paid'}]
    assert len(read(sandbox, 'SELECT * FROM activity_logs')) == 1


def test_full_payment_marks_invoice_paid(sandbox):
    data = details(); data['amount'] = '1000'
    order = create(sandbox, data)
    sandbox.remote[order]['order_status'] = 'PAID'
    assert verify(sandbox, order).json['paid']
    assert read(sandbox, 'SELECT status FROM invoices WHERE id=101')[0]['status'] == 'paid'


def test_verified_gateway_receipt_cannot_be_edited_through_manual_route(sandbox, monkeypatch):
    from flask import session
    from modules.billing import routes
    order = create(sandbox)
    sandbox.remote[order]['order_status'] = 'PAID'
    receipt_id = verify(sandbox, order).json['receipt_id']
    monkeypatch.setattr(routes, 'get_conn', sandbox.connect)
    monkeypatch.setattr(routes, 'get_current_institute_id', lambda **kwargs: 1)
    with sandbox.app.test_request_context(f'/billing/receipt/{receipt_id}/edit', method='POST'):
        session.update(user_id=10, role='admin', institute_id=1)
        response = routes.receipt_edit(receipt_id)
        assert response.status_code == 302
        assert '/invoice/101' in response.location
    assert read(sandbox, 'SELECT amount_received FROM receipts')[0]['amount_received'] == 750


def test_pending_order_does_not_update_ledger(sandbox):
    order = create(sandbox)
    assert verify(sandbox, order).json == {'paid': False, 'status': 'ACTIVE', 'receipt_id': None,
                                         'payment_session_id': 'test-session'}
    assert not read(sandbox, 'SELECT * FROM receipts')


@pytest.mark.parametrize('field,value', [('order_currency','USD'), ('order_amount', 20),
                                        ('customer_details', {'customer_id': 'wrong'}), ('order_id', 'wrong')])
def test_provider_order_mismatches_never_post_fees(sandbox, field, value):
    order = create(sandbox)
    sandbox.remote[order].update(order_status='PAID')
    sandbox.remote[order][field] = value
    assert verify(sandbox, order).status_code == 409
    assert not read(sandbox, 'SELECT * FROM receipts')


@pytest.mark.parametrize('payment', [
    {'payment_status':'FAILED', 'payment_amount':750, 'payment_currency':'INR', 'cf_payment_id':'pay_1'},
    {'payment_status':'SUCCESS', 'payment_amount':749, 'payment_currency':'INR', 'cf_payment_id':'pay_1'},
    {'payment_status':'SUCCESS', 'payment_amount':750, 'payment_currency':'USD', 'cf_payment_id':'pay_1'},
])
def test_provider_payment_mismatches_never_post_fees(sandbox, payment):
    order = create(sandbox)
    sandbox.remote[order].update(order_status='PAID', payments=[payment])
    assert verify(sandbox, order).status_code == 409
    assert not read(sandbox, 'SELECT * FROM receipts')


def test_unsigned_webhook_rejected_and_signed_webhook_verifies_api(sandbox):
    order = create(sandbox)
    assert webhook(sandbox, order, signed=False).status_code == 401
    # Even signed success payloads cannot create receipts while API says ACTIVE.
    assert webhook(sandbox, order).json['paid'] is False
    sandbox.remote[order]['order_status'] = 'PAID'
    with sandbox.client.session_transaction() as sess:
        sess.clear()  # Webhook is authenticated by its signature, without cookies/CSRF.
    assert webhook(sandbox, order).json['paid']
    assert webhook(sandbox, order, 'PAYMENT_FAILED_WEBHOOK').status_code == 200
    assert len(read(sandbox, 'SELECT * FROM receipts')) == 1


def test_raw_body_signature_rejects_reserialized_payload(sandbox):
    with sandbox.app.app_context():
        raw = b'{"amount": 750.00}'
        timestamp = '12345'
        sig = base64.b64encode(hmac.new(b'fixture-secret', timestamp.encode() + raw, hashlib.sha256).digest()).decode()
        assert cashfree.valid_webhook(raw, timestamp, sig)
        assert not cashfree.valid_webhook(b'{"amount":750.0}', timestamp, sig)


def test_invoice_change_after_checkout_requires_reconciliation(sandbox):
    order = create(sandbox)
    sandbox.remote[order]['order_status'] = 'PAID'
    execute(sandbox, 'UPDATE invoices SET total_amount = 500 WHERE id=101')
    assert verify(sandbox, order).json['status'] == 'REVIEW'
    assert webhook(sandbox, order).json['status'] == 'REVIEW'
    assert not read(sandbox, 'SELECT * FROM receipts')
    assert len(read(sandbox, 'SELECT * FROM activity_logs')) == 1


def test_receipt_and_ledger_rollback_together_on_posting_error(sandbox):
    order = create(sandbox)
    sandbox.remote[order]['order_status'] = 'PAID'
    execute(sandbox, 'DROP TABLE activity_logs')
    assert verify(sandbox, order).status_code == 500
    assert not read(sandbox, 'SELECT * FROM receipts')
    assert read(sandbox, 'SELECT status FROM invoices WHERE id=101')[0]['status'] == 'unpaid'
    assert read(sandbox, 'SELECT status FROM cashfree_orders')[0]['status'] == 'ACTIVE'


def test_concurrent_confirmations_post_exactly_once(sandbox):
    order = create(sandbox)
    sandbox.remote[order]['order_status'] = 'PAID'

    def confirm(_):
        with sandbox.app.app_context():
            return payments.verify_order(order)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(confirm, range(4)))
    assert all(result['paid'] for result in results)
    assert len(read(sandbox, 'SELECT * FROM receipts')) == 1


def test_concurrent_different_orders_do_not_overpay_invoice(sandbox):
    orders = [create(sandbox), create(sandbox)]
    for order in orders:
        sandbox.remote[order]['order_status'] = 'PAID'

    def confirm(order):
        with sandbox.app.app_context():
            return payments.verify_order(order)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, orders))
    assert sorted(result['status'] for result in results) == ['PAID', 'REVIEW']
    assert len(read(sandbox, 'SELECT * FROM receipts')) == 1


def test_order_and_verification_require_login_and_csrf(sandbox):
    order = create(sandbox)
    assert sandbox.client.post('/billing/cashfree/orders', json=details()).status_code == 400
    assert sandbox.client.post(f'/billing/cashfree/orders/{order}/verify').status_code == 400
    with sandbox.client.session_transaction() as sess:
        sess.pop('user_id')
    assert verify(sandbox, order).status_code == 401


def test_session_tenant_and_inactive_users_rejected(sandbox):
    with sandbox.client.session_transaction() as sess:
        sess['institute_id'] = 2
    assert sandbox.post('/billing/cashfree/orders', details()).status_code == 403
    with sandbox.client.session_transaction() as sess:
        sess['institute_id'] = 1
    execute(sandbox, 'UPDATE users SET is_active=0 WHERE id=10')
    assert sandbox.post('/billing/cashfree/orders', details()).status_code == 403


def test_provider_timeout_leaves_order_retryable(sandbox, monkeypatch):
    key = str(uuid.uuid4())
    original = cashfree.api_request

    def unavailable(*args, **kwargs):
        raise cashfree.CashfreeError('Cashfree is temporarily unavailable.')

    monkeypatch.setattr(cashfree, 'api_request', unavailable)
    assert sandbox.post('/billing/cashfree/orders', details(), key).status_code == 502
    assert read(sandbox, 'SELECT status FROM cashfree_orders')[0]['status'] == 'CREATING'
    monkeypatch.setattr(cashfree, 'api_request', original)
    create(sandbox, key=key)
    assert len(read(sandbox, 'SELECT * FROM cashfree_orders')) == 1


def test_masked_secret_and_production_url_fail_closed(sandbox):
    sandbox.app.config['CASHFREE_SECRET_KEY'] = 'cfsxxxxxxxxxfce'
    assert sandbox.post('/billing/cashfree/orders', details()).status_code == 503
    sandbox.app.config.update(CASHFREE_SECRET_KEY='fixture-secret', CASHFREE_API_URL='https://api.cashfree.com/pg')
    assert sandbox.post('/billing/cashfree/orders', details()).status_code == 503
    assert not sandbox.calls


def test_checkout_template_uses_server_urls_and_escapes_student_data(sandbox):
    from flask import render_template
    with sandbox.app.test_request_context('/billing/invoice/101'):
        rendered = render_template('billing/_cashfree_checkout.html', cashfree_available=True,
            balance_amount=750, effective_status='unpaid',
            invoice=SimpleNamespace(id=101, student_id=100, full_name='Student <script>',
                                    phone='9876543210', email='student@example.com'))
        assert 'https://sdk.cashfree.com/js/v3/cashfree.js' in rendered
        assert 'Student &lt;script&gt;' in rendered
        assert 'fixture-secret' not in rendered and 'TEST-fixture' not in rendered
        assert 'data-create-url="/billing/cashfree/orders"' in rendered
        assert 'id="cashfree-pay" type="submit" disabled' in rendered
        assert 'cashfree_checkout.js' in rendered
        hidden = render_template('billing/_cashfree_checkout.html', cashfree_available=False)
        assert 'cashfree-payment-form' not in hidden
        sandbox.app.jinja_env.filters['format_ist_datetime'] = str
        sandbox.app.jinja_env.get_template('billing/invoice_view.html')


def test_invoice_allows_sdk_checkout_post_without_relaxing_other_pages(sandbox):
    destination = 'https://sandbox.cashfree.com/pg/view/sessions/checkout'
    response = sandbox.client.get('/billing/invoice/101')
    policy = response.headers['Content-Security-Policy']
    directives = {part.split()[0] : part.split()[1:] for part in policy.split(';') if part.strip()}
    assert directives['form-action'] == ["'self'", destination]
    assert directives['object-src'] == ["'none'"]
    assert directives['frame-ancestors'] == ["'self'"]
    assert sandbox.client.get('/token').headers['Content-Security-Policy'] == sandbox.app.config['CONTENT_SECURITY_POLICY']


def test_custom_checkout_policy_preserves_existing_sources_and_does_not_add_wildcards(sandbox):
    sandbox.app.config['CONTENT_SECURITY_POLICY'] = "default-src 'none'; form-action 'self' https://forms.example; frame-src 'self';"
    response = sandbox.client.get('/billing/invoice/101')
    assert response.headers['Content-Security-Policy'] == (
        "default-src 'none';form-action 'self' https://forms.example https://sandbox.cashfree.com/pg/view/sessions/checkout; frame-src 'self';"
    )


def test_checkout_policy_exception_is_bound_to_configured_institute(sandbox, monkeypatch):
    monkeypatch.setattr(cashfree_routes, 'get_current_institute_id', lambda: 2)
    response = sandbox.client.get('/billing/invoice/101')
    assert response.headers['Content-Security-Policy'] == sandbox.app.config['CONTENT_SECURITY_POLICY']


def test_http_client_uses_required_headers_timeout_and_does_not_leak_secret(sandbox, monkeypatch):
    original = sandbox.http_api
    recorded = {}

    def request(method, url, **kwargs):
        recorded.update(method=method, url=url, **kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {'order_id': 'example'})

    monkeypatch.setattr(cashfree.requests, 'request', request)
    with sandbox.app.app_context():
        assert original('POST', '/orders', {'order_amount': 1}, str(uuid.uuid4())) == {'order_id': 'example'}
        assert recorded['headers']['x-api-version'] == '2023-08-01'
        assert recorded['headers']['x-client-id'] == 'TEST-fixture'
        assert recorded['headers']['x-client-secret'] == 'fixture-secret'
        assert recorded['timeout'] == (5, 20) and recorded['allow_redirects'] is False
        monkeypatch.setattr(cashfree.requests, 'request', lambda *a, **k: SimpleNamespace(status_code=401))
        with pytest.raises(cashfree.CashfreeError) as error:
            original('GET', '/orders/example')
        assert 'fixture-secret' not in str(error.value)
