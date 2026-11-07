import re
import uuid
from datetime import date
from urllib.parse import urlsplit

import pytest
from flask import session
from itsdangerous import TimestampSigner

from modules.billing import auto_reminders, routes
from services import payment_links as links
from config import Config
from test_cashfree_payments import sandbox, create, details, execute, read


@pytest.fixture()
def linked(sandbox, monkeypatch):
    conn = sandbox.connect()
    conn.executescript('''
        ALTER TABLE invoices ADD COLUMN created_by INTEGER NOT NULL DEFAULT 10;
        ALTER TABLE invoices ADD COLUMN sms_token TEXT;
        ALTER TABLE invoices ADD COLUMN sms_sent_at TEXT;
        UPDATE invoices SET invoice_no='TEST-101' WHERE id=101;
        ALTER TABLE students ADD COLUMN phone TEXT;
        ALTER TABLE students ADD COLUMN email TEXT;
        UPDATE students SET phone='9999999999', email='private-student@example.com' WHERE id=100;
        ALTER TABLE installment_plans ADD COLUMN due_date TEXT DEFAULT '2026-10-29';
        CREATE TABLE institute_domains (id INTEGER PRIMARY KEY, institute_id INTEGER,
            hostname TEXT, status TEXT, is_primary INTEGER);
        INSERT INTO institute_domains VALUES (1,1,'tenant.example','active',1),
                                             (2,2,'other.example','active',1);
        CREATE TABLE reminder_logs (id INTEGER PRIMARY KEY, institute_id INTEGER, student_id INTEGER,
            invoice_id INTEGER, installment_id INTEGER, phone_number TEXT, reminder_type TEXT,
            message_text TEXT, status TEXT, sent_via TEXT, sent_by INTEGER, sent_at TEXT);
    ''')
    conn.commit(); conn.close()
    sandbox.app.config.update(CASHFREE_PAYMENT_LINKS_ENABLED=True,
        CASHFREE_PAYMENT_LINK_BASE_URL='https://tenant.example', CASHFREE_PAYMENT_LINK_DAYS=30, APP_ENV='testing')
    monkeypatch.setattr(links, 'get_conn', sandbox.connect)
    monkeypatch.setattr(routes, 'get_conn', sandbox.connect)
    monkeypatch.setattr(routes, 'get_current_institute_id', lambda **kwargs: 1)
    monkeypatch.setattr(routes, 'log_activity', lambda **kwargs: None)
    with sandbox.app.app_context():
        conn = sandbox.connect()
        sandbox.payment_url = links.build_link(conn, 1, 101)
        conn.close()
    sandbox.payment_path = urlsplit(sandbox.payment_url).path
    sandbox.payment_token = sandbox.payment_path.rsplit('/',1)[1]
    sandbox.public = sandbox.app.test_client()
    sandbox.public_csrf = re.search(r'name="csrf_token" value="([^"]+)"',
                                    sandbox.public.get(sandbox.payment_path).text).group(1)
    return sandbox


def public_post(linked, path, data=None, key=None):
    headers = {'X-CSRFToken':linked.public_csrf}
    if key:
        headers['Idempotency-Key'] = key
    return linked.public.post(path, json=data, headers=headers)


def student_order(linked, amount='500.00', option='installment', **changes):
    data = details()
    data.update(amount=amount, payment_option=option, **changes)
    response = public_post(linked, linked.payment_path+'/orders', data, str(uuid.uuid4()))
    assert response.status_code == 200, response.json
    return response.json['order_id']


def student_verify(linked, order_id):
    return public_post(linked, linked.payment_path+'/orders/'+order_id+'/verify')


def test_public_link_needs_no_login_and_offers_installment_or_full_amount(linked):
    page = linked.public.get(linked.payment_path)
    assert page.status_code == 200
    assert 'Next unpaid installment #1' in page.text
    assert '500.00' in page.text and '1000.00' in page.text
    assert 'private-student@example.com' not in page.text and '9999999999' not in page.text
    assert page.headers['Cache-Control'] == 'no-store'
    assert page.headers['Referrer-Policy'] == 'no-referrer'
    assert 'https://sandbox.cashfree.com/pg/view/sessions/checkout' in page.headers['Content-Security-Policy']
    with linked.public.session_transaction() as state:
        assert 'user_id' not in state


@pytest.mark.parametrize('amount,choice', [('500.00','installment'), ('1000.00','full')])
def test_student_selects_server_amount_and_order_is_bound_to_link(linked, amount, choice):
    order = student_order(linked, amount, choice)
    stored = read(linked, 'SELECT * FROM cashfree_payment_link_orders')[0]
    assert stored['order_id'] == order and stored['payment_option'] == choice
    assert stored['link_digest'] == links.link_digest(linked.payment_token)
    assert linked.payment_token not in str(stored)
    assert linked.remote[order]['order_amount'] == float(amount)
    assert '/billing/pay/' in linked.remote[order]['order_meta']['return_url']


def test_client_cannot_change_invoice_or_student_using_public_endpoint(linked):
    order = student_order(linked, student_id=200, invoice_id=201)
    assert linked.remote[order]['customer_details']['customer_id'] == 'inst_1_student_100'
    assert read(linked, 'SELECT invoice_id FROM cashfree_orders')[0]['invoice_id'] == 101


@pytest.mark.parametrize('amount,choice', [('1','installment'), ('1000','installment'), ('500','full')])
def test_student_cannot_tamper_with_selected_amount(linked, amount, choice):
    data = dict(details(), amount=amount, payment_option=choice)
    response = public_post(linked, linked.payment_path+'/orders', data, str(uuid.uuid4()))
    assert response.status_code == 409
    assert not linked.calls


@pytest.mark.parametrize('choice', ['custom', None, []])
def test_invalid_student_choice_is_rejected_before_provider_call(linked, choice):
    response = public_post(linked, linked.payment_path+'/orders', dict(details(),payment_option=choice))
    assert response.status_code == 400 and not linked.calls


def test_old_link_shows_updated_amount_and_rejects_stale_quote(linked):
    execute(linked, 'INSERT INTO receipts (invoice_id,institute_id,amount_received) VALUES (101,1,125)')
    page = linked.public.get(linked.payment_path)
    assert 'data-amount="375.00"' in page.text and 'data-amount="875.00"' in page.text
    stale = dict(details(), amount='500.00', payment_option='installment')
    response = public_post(linked, linked.payment_path+'/orders', stale)
    assert response.status_code == 409 and 'amount has changed' in response.json['error']
    assert not linked.calls


def test_verified_student_payment_posts_once_and_same_link_moves_to_next_installment(linked):
    order = student_order(linked)
    linked.remote[order]['order_status'] = 'PAID'
    assert student_verify(linked, order).json['paid']
    assert student_verify(linked, order).json['paid']
    assert len(read(linked, 'SELECT * FROM receipts')) == 1
    page = linked.public.get(linked.payment_path)
    assert 'Next unpaid installment #2' in page.text
    assert 'data-amount="500.00"' in page.text
    assert 'data-amount="1000.00"' not in page.text
    confirmed = linked.public.get(linked.payment_path+'?cashfree_paid_order='+order)
    assert 'Payment of INR 500.00 verified' in confirmed.text
    assert 'TST/REC/001' in confirmed.text


@pytest.mark.parametrize('status', ['paid','cancelled','write_off','partially_written_off'])
def test_settled_and_closed_links_cannot_create_orders(linked, status):
    if status == 'paid':
        execute(linked, 'INSERT INTO receipts (invoice_id,institute_id,amount_received) VALUES (101,1,1000)')
    execute(linked, f"UPDATE invoices SET status='{status}' WHERE id=101")
    page = linked.public.get(linked.payment_path)
    assert 'id="cashfree-payment-form"' not in page.text
    response = public_post(linked, linked.payment_path+'/orders', dict(details(), payment_option='full', amount='1000'))
    assert response.status_code == 409


def test_invalid_expired_wrong_purpose_and_cross_tenant_links_fail(linked, monkeypatch):
    assert linked.public.get(linked.payment_path+'broken').status_code == 404
    with linked.app.app_context():
        wrong_purpose = routes._make_invoice_token(101)
    assert linked.public.get('/billing/pay/'+wrong_purpose).status_code == 404
    from modules.billing import cashfree_routes
    monkeypatch.setattr(cashfree_routes, 'get_current_institute_id', lambda: 2)
    assert linked.public.get(linked.payment_path).status_code == 404
    monkeypatch.setattr(cashfree_routes, 'get_current_institute_id', lambda: 1)
    original = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: original(self)+31*86400)
    assert linked.public.get(linked.payment_path).status_code == 410


def test_public_link_cannot_verify_private_staff_order(linked):
    order = create(linked)
    call_count = len(linked.calls)
    assert student_verify(linked, order).status_code == 404
    assert len(linked.calls) == call_count


def test_another_signed_link_cannot_take_over_existing_checkout(linked):
    order = student_order(linked)
    with linked.app.app_context():
        alternate = links._serializer().dumps({'t':1,'i':101,'s':100,'version':'different'})
    response = public_post(linked, '/billing/pay/'+alternate+'/orders/'+order+'/verify')
    assert response.status_code == 404


def test_public_order_requires_csrf_and_link_feature_can_be_disabled(linked):
    assert linked.public.post(linked.payment_path+'/orders', json=details()).status_code == 400
    linked.app.config['CASHFREE_PAYMENT_LINKS_ENABLED'] = False
    assert linked.public.get(linked.payment_path).status_code == 404
    assert public_post(linked, linked.payment_path+'/orders', dict(details(),payment_option='full')).status_code == 404


def test_pending_checkout_does_not_resume_after_balance_changes(linked):
    order = student_order(linked)
    execute(linked, 'INSERT INTO receipts (invoice_id,institute_id,amount_received) VALUES (101,1,125)')
    assert student_verify(linked, order).status_code == 409


def test_payment_link_host_must_belong_to_invoice_tenant(linked):
    with linked.app.app_context():
        linked.app.config['CASHFREE_PAYMENT_LINK_BASE_URL'] = 'https://evil.example'
        conn = linked.connect()
        try:
            with pytest.raises(Exception, match='not an active institute domain'):
                links.build_link(conn, 1, 101)
        finally:
            conn.close()


def test_invoice_sms_keeps_download_link_and_adds_dynamic_payment_link(linked, monkeypatch):
    messages = []
    monkeypatch.setattr(routes, 'send_sms', lambda phone,message: messages.append(message) or {'success':True})
    with linked.app.test_request_context('/billing/invoice/101/send-sms', method='POST'):
        result = routes._send_invoice_sms_link(101,user_id=10,branch_id=3)
    assert result['success'] and len(messages) == 1
    assert '/billing/invoice/download/' in messages[0] and '/billing/pay/' in messages[0]
    assert 'Pay online (sandbox)' in messages[0]
    assert 'amount=' not in messages[0]


def test_foreign_invoice_sms_is_not_sent(linked, monkeypatch):
    monkeypatch.setattr(routes, 'send_sms', lambda *args: pytest.fail('Foreign invoice must not be sent'))
    with linked.app.test_request_context('/billing/invoice/201/send-sms', method='POST'):
        assert not routes._send_invoice_sms_link(201,user_id=10)['success']


def test_manual_reminder_adds_payment_link_to_sent_and_logged_message(linked, monkeypatch):
    messages = []
    monkeypatch.setattr(routes, 'send_sms', lambda phone,message: messages.append(message) or {'success':True})
    with linked.app.test_request_context('/billing/reminder/send-sms', method='POST',
            json={'installment_id':1,'reminder_type':'due_today','message_text':'Please pay your installment.'}):
        session.update(user_id=10,institute_id=1,role='staff')
        response = routes.reminder_send_sms()
    assert response.json['success']
    assert '/billing/pay/' in messages[0]
    assert read(linked, 'SELECT message_text FROM reminder_logs')[0]['message_text'] == messages[0]


def test_automatic_reminder_adds_same_link_without_request_context(linked, monkeypatch):
    row = dict(installment_id=1, invoice_id=101, invoice_no='TEST-101', institute_id=1,
        branch_id=3,student_id=100,student_name='Student',student_phone='9999999999',
        balance_due=500,due_date_iso=date.today().isoformat())
    messages = []
    monkeypatch.setattr(auto_reminders, 'get_conn', linked.connect)
    monkeypatch.setattr(auto_reminders, '_load_due_installments', lambda *args:[row])
    monkeypatch.setattr(auto_reminders, 'get_company_profile', lambda institute_id:{'company_name':'Test Institute'})
    monkeypatch.setattr(auto_reminders, 'log_activity', lambda **kwargs: None)
    monkeypatch.setattr(auto_reminders, 'send_sms', lambda phone,message: messages.append(message) or {'success':True})
    monkeypatch.setattr(Config, 'CASHFREE_PAYMENT_LINKS_ENABLED', True)
    monkeypatch.setattr(Config, 'CASHFREE_PAYMENT_LINK_BASE_URL', 'https://tenant.example')
    monkeypatch.setattr(Config, 'SECRET_KEY', linked.app.config['SECRET_KEY'])
    for key,value in dict(APP_ENV='testing', CASHFREE_MODE='sandbox', CASHFREE_APP_ID='TEST-fixture',
                          CASHFREE_SECRET_KEY='fixture-secret', CASHFREE_API_URL='https://sandbox.cashfree.com/pg',
                          CASHFREE_INSTITUTE_ID=1).items():
        monkeypatch.setattr(Config, key, value)
    result = auto_reminders.send_automatic_fee_reminders()
    assert result['sent'] == 1 and '/billing/pay/' in messages[0]
    assert read(linked, 'SELECT message_text FROM reminder_logs')[0]['message_text'] == messages[0]


def test_live_student_page_and_sms_do_not_describe_payments_as_sandbox(linked):
    linked.app.config.update(APP_ENV='production', CASHFREE_MODE='production',
        CASHFREE_API_URL='https://api.cashfree.com/pg',CASHFREE_APP_ID='LIVE-fixture')
    page = linked.public.get(linked.payment_path)
    assert page.status_code == 200
    assert 'data-mode="production"' in page.text
    assert 'Sandbox test payment' not in page.text
    assert 'Pay with Cashfree (sandbox)' not in page.text
    with linked.app.app_context():
        message = links.append_to_message('Your invoice is ready.',linked.payment_url)
    assert 'Pay online: ' in message and '(sandbox)' not in message
