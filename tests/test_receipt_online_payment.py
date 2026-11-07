"""Receipt collection uses the existing verified Cashfree flow and tenant ownership."""

from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from extensions import csrf, limiter
from modules.billing import routes
from test_cashfree_payments import sandbox, read
from test_student_payment_links import linked


@pytest.fixture()
def collection(linked):
    conn = linked.connect()
    conn.execute('ALTER TABLE installment_plans ADD COLUMN remarks TEXT')
    conn.commit()
    conn.close()
    app = Flask(__name__)
    app.config.update(linked.app.config)
    app.jinja_loader = ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}'}),
        FileSystemLoader('templates'),
    ])
    csrf.init_app(app)
    limiter.init_app(app)
    app.register_blueprint(routes.billing_bp, url_prefix='/billing')
    app.add_url_rule('/login', endpoint='core.login', view_func=lambda: 'login')

    @app.after_request
    def default_security_headers(response):
        response.headers.setdefault('Content-Security-Policy', app.config['CONTENT_SECURITY_POLICY'])
        return response

    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=10, institute_id=1, role='staff')
    return SimpleNamespace(app=app, client=client, ledger=linked)


def update(collection, sql):
    conn = collection.ledger.connect()
    conn.execute(sql)
    conn.commit()
    conn.close()


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = {}
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'form':
            assert self.current is None, 'Payment forms must not be nested'
            self.current = values['id']
            self.forms[self.current] = {'attributes': values, 'inputs': {}}
        if tag == 'input' and self.current and 'name' in values:
            self.forms[self.current]['inputs'][values['name']] = values

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


def test_receivables_destination_offers_online_and_manual_collection(collection):
    page = collection.client.get('/billing/receipt/new?invoice_id=101')
    assert page.status_code == 200
    forms = Forms(page.text).forms
    online = forms['cashfree-payment-form']
    manual = forms['manual-receipt-form']
    assert online['attributes']['data-invoice-id'] == '101'
    assert online['attributes']['data-student-id'] == '100'
    assert online['inputs']['amount']['max'] == '1000.00'
    assert online['inputs']['name']['value'] == 'Test Student'
    assert online['inputs']['phone']['value'] == '9999999999'
    assert online['inputs']['email']['value'] == 'private-student@example.com'
    assert online['inputs']['csrf_token']['value']
    assert manual['inputs']['csrf_token']['value']
    assert manual['attributes']['action'] == '/billing/receipt/new?invoice_id=101'
    assert 'sdk.cashfree.com/js/v3/cashfree.js' in page.text
    assert collection.ledger.payment_url in page.text
    assert not read(collection.ledger, 'SELECT * FROM receipts')
    assert not collection.ledger.calls


@pytest.mark.parametrize('mode,host', [('sandbox','sandbox.cashfree.com'), ('production','api.cashfree.com')])
def test_receipt_checkout_csp_allows_only_the_configured_gateway(collection, mode, host):
    collection.app.config.update(CASHFREE_MODE=mode, CASHFREE_APP_ID='TEST-fixture' if mode == 'sandbox' else 'LIVE-fixture',
                                 CASHFREE_API_URL='https://'+host+'/pg')
    page = collection.client.get('/billing/receipt/new?invoice_id=101')
    policy = page.headers['Content-Security-Policy']
    directives = {part.split()[0]: part.split()[1:] for part in policy.split(';') if part.strip()}
    assert directives['form-action'] == ["'self'", 'https://'+host+'/pg/view/sessions/checkout']
    assert directives['object-src'] == ["'none'"]
    assert directives['frame-ancestors'] == ["'self'"]
    assert f'data-mode="{mode}"' in page.text


@pytest.mark.parametrize('unavailable', ['no_keys', 'other_merchant', 'not_billing_staff'])
def test_manual_collection_remains_available_without_cashfree(collection, unavailable):
    if unavailable == 'no_keys':
        collection.app.config['CASHFREE_SECRET_KEY'] = ''
    elif unavailable == 'other_merchant':
        collection.app.config['CASHFREE_INSTITUTE_ID'] = 2
    else:
        with collection.client.session_transaction() as state:
            state['role'] = 'viewer'
    page = collection.client.get('/billing/receipt/new?invoice_id=101')
    assert page.status_code == 200
    assert 'cashfree-payment-form' not in Forms(page.text).forms
    assert 'manual-receipt-form' in Forms(page.text).forms
    assert page.headers['Content-Security-Policy'] == collection.app.config['CONTENT_SECURITY_POLICY']


@pytest.mark.parametrize('method', ['get', 'post'])
@pytest.mark.parametrize('invoice_id', [201, 999])
def test_receipt_cannot_view_or_post_other_tenants_invoice(collection, method, invoice_id):
    own_page = collection.client.get('/billing/receipt/new?invoice_id=101')
    token = Forms(own_page.text).forms['manual-receipt-form']['inputs']['csrf_token']['value']
    response = getattr(collection.client, method)(f'/billing/receipt/new?invoice_id={invoice_id}',
        headers={'X-CSRFToken': token}, data={'amount_received':'100', 'payment_mode':'cash'})
    assert response.status_code == 302
    assert response.location.endswith('/billing/invoices')
    assert not read(collection.ledger, 'SELECT * FROM receipts')


@pytest.mark.parametrize('method', ['get', 'post'])
@pytest.mark.parametrize('status', ['cancelled', 'write_off', 'partially_written_off'])
def test_non_payable_invoice_cannot_be_collected(collection, status, method):
    own_page = collection.client.get('/billing/receipt/new?invoice_id=101')
    token = Forms(own_page.text).forms['manual-receipt-form']['inputs']['csrf_token']['value']
    update(collection, "UPDATE invoices SET status='"+status+"' WHERE id=101")
    page = getattr(collection.client, method)('/billing/receipt/new?invoice_id=101',
        headers={'X-CSRFToken': token}, data={'amount_received':'100', 'payment_mode':'cash'})
    assert page.status_code == 302
    assert page.location.endswith('/billing/invoice/101')
    assert not read(collection.ledger, 'SELECT * FROM receipts')


def test_current_receipts_reduce_online_amount_and_full_payment_hides_checkout(collection):
    update(collection, "INSERT INTO receipts (invoice_id,institute_id,amount_received) VALUES (101,1,300)")
    page = collection.client.get('/billing/receipt/new?invoice_id=101')
    amount = Forms(page.text).forms['cashfree-payment-form']['inputs']['amount']
    assert amount['value'] == amount['max'] == '700.00'
    update(collection, "INSERT INTO receipts (invoice_id,institute_id,amount_received) VALUES (101,1,700)")
    assert 'cashfree-payment-form' not in Forms(collection.client.get('/billing/receipt/new?invoice_id=101').text).forms


def test_online_collection_records_only_after_verification_and_is_idempotent(collection):
    page = collection.client.get('/billing/receipt/new?invoice_id=101')
    online = Forms(page.text).forms['cashfree-payment-form']
    headers = {'X-CSRFToken': online['inputs']['csrf_token']['value']}
    data = {name: online['inputs'][name]['value'] for name in ('amount', 'name', 'phone', 'email')}
    data.update(student_id=100, invoice_id=101)
    order = collection.client.post(online['attributes']['data-create-url'], json=data, headers=headers)
    assert order.status_code == 200
    order_id = order.json['order_id']
    assert not read(collection.ledger, 'SELECT * FROM receipts')
    collection.ledger.remote[order_id]['order_status'] = 'PAID'
    verify_url = online['attributes']['data-verify-url'].replace('ORDER_ID', order_id)
    assert collection.client.post(verify_url, headers=headers).json['paid']
    assert collection.client.post(verify_url, headers=headers).json['paid']
    assert len(read(collection.ledger, 'SELECT * FROM receipts')) == 1
    assert 'cashfree-payment-form' not in Forms(collection.client.get('/billing/receipt/new?invoice_id=101').text).forms


def test_manual_receipt_still_records_and_reduces_next_online_balance(collection):
    update(collection, 'UPDATE students SET phone=NULL WHERE id=100')
    page = collection.client.get('/billing/receipt/new?invoice_id=101')
    token = Forms(page.text).forms['manual-receipt-form']['inputs']['csrf_token']['value']
    result = collection.client.post('/billing/receipt/new?invoice_id=101', data={
        'csrf_token':token, 'amount_received':'250', 'payment_mode':'cash', 'receipt_date':'2026-11-07'})
    assert result.status_code == 302
    receipts = read(collection.ledger, 'SELECT * FROM receipts')
    assert len(receipts) == 1 and receipts[0]['amount_received'] == 250
    assert receipts[0]['payment_mode'] == 'cash' and receipts[0]['institute_id'] == 1
    assert not collection.ledger.calls
    amount = Forms(collection.client.get('/billing/receipt/new?invoice_id=101').text).forms['cashfree-payment-form']['inputs']['amount']
    assert amount['value'] == amount['max'] == '750.00'
