"""Signed, tenant-owned student payment links with current ledger amounts."""

import hashlib
import hmac
from urllib.parse import quote, urlsplit

from flask import current_app, has_app_context
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import Config
from db import get_conn
from services import cashfree, cashfree_payments as payments


def config():
    return current_app.config if has_app_context() else vars(Config)


def enabled(institute_id):
    values = config()
    return bool(institute_id and values.get('CASHFREE_PAYMENT_LINKS_ENABLED')
                and int(institute_id) == int(values.get('CASHFREE_INSTITUTE_ID', 1)))


def _serializer():
    return URLSafeTimedSerializer(config()['SECRET_KEY'], salt='cashfree-student-payment-v1')


def _invoice(conn, invoice_id, institute_id):
    row = conn.execute('''SELECT i.id, i.institute_id, i.student_id, i.branch_id, i.created_by,
        i.invoice_no, i.total_amount, i.status FROM invoices i
        JOIN students s ON s.id=i.student_id AND s.institute_id=i.institute_id
        WHERE i.id=? AND i.institute_id=?''', (invoice_id, institute_id)).fetchone()
    if not row:
        raise cashfree.CashfreeError('Payment link not found.', 404)
    return dict(row)


def amounts(conn, invoice):
    paid, written_off = payments._totals(conn, invoice['id'], invoice['institute_id'])
    balance = max(0, payments._ledger_paise(invoice['total_amount']) - paid - written_off)
    payable = invoice['status'] not in {'cancelled', 'write_off', 'partially_written_off'} and not written_off
    # Receipts are allocated in installment order in this ERP. Derive the next
    # unpaid installment from actual receipts, rather than trusting cached amounts.
    remaining_paid = paid
    installment = None
    for row in conn.execute('''SELECT id, installment_no, due_date, amount_due FROM installment_plans
                              WHERE invoice_id=? ORDER BY installment_no,id''', (invoice['id'],)).fetchall():
        due = payments._ledger_paise(row['amount_due'])
        covered = min(max(remaining_paid, 0), due)
        remaining_paid -= covered
        if due > covered:
            installment = dict(row)
            installment['amount_paise'] = min(due - covered, balance)
            break
    return dict(balance_paise=balance, installment=installment, payable=bool(payable and balance >= 100))


def _base_url(conn, institute_id):
    configured = config().get('CASHFREE_PAYMENT_LINK_BASE_URL', '')
    if configured:
        parsed = urlsplit(configured)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}):
            raise cashfree.CashfreeError('Configure a valid payment link base URL.', 503)
        if config().get('APP_ENV') == 'production' and parsed.scheme != 'https':
            raise cashfree.CashfreeError('Payment links require HTTPS in production.', 503)
        domain = conn.execute('''SELECT hostname FROM institute_domains
            WHERE institute_id=? AND hostname=? AND status='active' ''',
                              (institute_id, parsed.hostname.lower())).fetchone()
        if not domain:
            raise cashfree.CashfreeError('Payment link host is not an active institute domain.', 503)
        return configured.rstrip('/')
    domain = conn.execute('''SELECT hostname FROM institute_domains
        WHERE institute_id=? AND status='active' ORDER BY is_primary DESC,id LIMIT 1''',
                          (institute_id,)).fetchone()
    if not domain:
        raise cashfree.CashfreeError('An active institute domain is required for payment links.', 503)
    return 'https://' + domain['hostname']


def build_link(conn, institute_id, invoice_id):
    if not enabled(institute_id):
        return None
    invoice = _invoice(conn, invoice_id, institute_id)
    if not amounts(conn, invoice)['payable']:
        return None
    token = _serializer().dumps({'t':int(institute_id), 'i':int(invoice_id), 's':int(invoice['student_id'])})
    return _base_url(conn, institute_id) + '/billing/pay/' + quote(token, safe='')


def append_to_message(message, payment_url):
    if not payment_url or payment_url in message:
        return message
    return message.rstrip() + '\nPay online (sandbox): ' + payment_url


def resolve(conn, token, institute_id):
    try:
        data = _serializer().loads(token, max_age=config().get('CASHFREE_PAYMENT_LINK_DAYS',30) * 86400)
    except SignatureExpired:
        raise cashfree.CashfreeError('This payment link has expired. Request a new link from your institute.', 410)
    except BadSignature:
        raise cashfree.CashfreeError('Invalid payment link.', 404)
    if (not isinstance(data, dict) or data.get('t') != institute_id
            or not enabled(institute_id)):
        raise cashfree.CashfreeError('Payment link not found.', 404)
    invoice = _invoice(conn, data.get('i'), institute_id)
    if invoice['student_id'] != data.get('s'):
        raise cashfree.CashfreeError('Payment link not found.', 404)
    return invoice


def link_digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def linked_order(conn, token, order_id, invoice):
    order = payments.get_order(conn, order_id)
    binding = conn.execute('''SELECT link_digest, payment_option FROM cashfree_payment_link_orders
                             WHERE order_id=?''', (order_id,)).fetchone()
    if (not binding or not hmac.compare_digest(binding['link_digest'], link_digest(token))
            or order['institute_id'] != invoice['institute_id'] or order['invoice_id'] != invoice['id']):
        raise cashfree.CashfreeError('Order not found.', 404)
    order['payment_option'] = binding['payment_option']
    return order


def create_order(token, institute_id, data, request_key):
    choice = data.get('payment_option') if isinstance(data,dict) else None
    if not isinstance(choice,str) or choice not in {'full', 'installment'}:
        raise cashfree.CashfreeError('Choose the installment amount or full invoice balance.', 400)
    conn = get_conn()
    try:
        invoice = resolve(conn, token, institute_id)
        return_base = _base_url(conn, institute_id)
    finally:
        conn.close()
    def validate_amount(connection, locked_invoice):
        current = amounts(connection, dict(locked_invoice, institute_id=institute_id))
        if not current['payable']:
            raise cashfree.CashfreeError('This invoice no longer has a payable balance.', 409)
        expected = current['balance_paise'] if choice == 'full' else (
            current['installment']['amount_paise'] if current['installment'] else 0)
        if cashfree.amount_paise(data.get('amount')) != expected:
            raise cashfree.CashfreeError('The amount has changed. Refresh this payment page before paying.', 409)

    # A bearer payment link grants only this invoice. The original invoice author
    # remains the ledger's user attribution; the binding records student-link origin.
    actor = dict(id=invoice['created_by'], institute_id=institute_id, role='payment_link',
                 branch_id=invoice['branch_id'], can_view_all_branches=False)
    return payments.create_order(actor, dict(data, student_id=invoice['student_id'], invoice_id=invoice['id']),
        request_key, lambda _invoice_id, order_id: return_base+'/billing/pay/'+quote(token,safe='')+'?cashfree_order_id='+order_id,
        public_link=dict(digest=link_digest(token), option=choice, validate_amount=validate_amount))


def verify_order(token, institute_id, order_id):
    conn = get_conn()
    try:
        invoice = resolve(conn, token, institute_id)
        order = linked_order(conn, token, order_id, invoice)
    finally:
        conn.close()
    result = payments.verify_order(order_id)
    if result.get('status') == 'ACTIVE':
        conn = get_conn()
        try:
            current = amounts(conn, _invoice(conn, invoice['id'], institute_id))
            expected = current['balance_paise'] if order['payment_option'] == 'full' else (
                current['installment']['amount_paise'] if current['installment'] else 0)
            if not current['payable'] or expected != order['amount_paise']:
                raise cashfree.CashfreeError('The balance changed after checkout started. Contact your institute to reconcile this checkout.', 409)
        finally:
            conn.close()
    return result
