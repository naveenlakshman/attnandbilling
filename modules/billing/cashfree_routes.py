"""Cashfree endpoints registered on the existing billing blueprint."""

from functools import wraps

from flask import current_app, jsonify, render_template, request, session, url_for

from db import get_conn
from extensions import csrf, limiter
from services import cashfree, cashfree_payments, payment_links
from services.tenant_context import get_current_institute_id


def _actor():
    if not session.get("user_id"):
        raise cashfree.CashfreeError("Please sign in to continue.", 401)
    institute_id = get_current_institute_id()
    if (not institute_id or session.get("institute_id") != institute_id
            or institute_id != current_app.config.get("CASHFREE_INSTITUTE_ID", 1)):
        raise cashfree.CashfreeError("Cashfree is unavailable for this institute.", 403)
    conn = get_conn()
    try:
        user = conn.execute("""SELECT id, institute_id, role, branch_id, can_view_all_branches, is_active
                               FROM users WHERE id = ? AND institute_id = ?""",
                            (session["user_id"], institute_id)).fetchone()
        if not user or not user["is_active"] or user["role"] not in {"admin", "staff"}:
            raise cashfree.CashfreeError("Active billing staff access is required.", 403)
        return dict(user)
    finally:
        conn.close()


def _errors(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            response = jsonify(result)
            response.headers["Cache-Control"] = "no-store"
            return response
        except cashfree.CashfreeError as exc:
            return jsonify(error=str(exc)), exc.status
        except Exception as exc:
            # Never log request bodies, provider responses, credentials or session IDs.
            current_app.logger.error("Cashfree operation failed (%s)", type(exc).__name__)
            return jsonify(error="Payment could not be processed. Retry verification before paying again."), 500
    return wrapped


def register_cashfree_routes(billing_bp):
    public_endpoints = {'billing.cashfree_public_pay', 'billing.cashfree_public_create', 'billing.cashfree_public_verify'}

    @billing_bp.after_request
    def cashfree_checkout_headers(response):
        public = request.endpoint in public_endpoints
        if public:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        if (
            (request.endpoint in {'billing.invoice_view', 'billing.receipt_new'} or public)
            and response.status_code == 200
            and current_app.config.get('SECURITY_HEADERS_ENABLED')
            and (public or session.get('role') in {'admin', 'staff'})
            and get_current_institute_id() == current_app.config.get('CASHFREE_INSTITUTE_ID', 1)
            and cashfree.configured()
        ):
            policy = response.headers.get('Content-Security-Policy', current_app.config['CONTENT_SECURITY_POLICY'])
            response.headers['Content-Security-Policy'] = cashfree.checkout_content_security_policy(policy)
        return response

    @billing_bp.route('/pay/<token>', methods=['GET'])
    @limiter.limit('60 per minute')
    def cashfree_public_pay(token):
        conn = get_conn()
        try:
            invoice = payment_links.resolve(conn, token, get_current_institute_id())
            current = payment_links.amounts(conn, invoice)
            pending_choice = None
            verified_payment = None
            if request.args.get('cashfree_order_id'):
                order = payment_links.linked_order(conn, token, request.args['cashfree_order_id'], invoice)
                pending_choice = order['payment_option']
            if request.args.get('cashfree_paid_order'):
                order = payment_links.linked_order(conn, token, request.args['cashfree_paid_order'], invoice)
                if order['status'] == 'PAID' and order['receipt_id']:
                    verified_payment = conn.execute('''SELECT receipt_no,amount_received FROM receipts
                        WHERE id=? AND invoice_id=? AND institute_id=?''',
                        (order['receipt_id'],invoice['id'],invoice['institute_id'])).fetchone()
            return render_template('billing/student_payment.html', invoice=invoice, amounts=current,
                                   token=token, pending_choice=pending_choice, verified_payment=verified_payment)
        except cashfree.CashfreeError as exc:
            return str(exc), exc.status
        finally:
            conn.close()

    @billing_bp.route('/pay/<token>/orders', methods=['POST'])
    @limiter.limit('10 per minute')
    @_errors
    def cashfree_public_create(token):
        return payment_links.create_order(token, get_current_institute_id(), request.get_json(silent=True),
                                          request.headers.get('Idempotency-Key'))

    @billing_bp.route('/pay/<token>/orders/<order_id>/verify', methods=['POST'])
    @limiter.limit('30 per minute')
    @_errors
    def cashfree_public_verify(token, order_id):
        return payment_links.verify_order(token, get_current_institute_id(), order_id)

    @billing_bp.route("/cashfree/orders", methods=["POST"])
    @limiter.limit("10 per minute")
    @_errors
    def cashfree_create_order():
        actor = _actor()
        return cashfree_payments.create_order(
            actor, request.get_json(silent=True), request.headers.get("Idempotency-Key"),
            lambda invoice_id, order_id: url_for(
                "billing.invoice_view", invoice_id=invoice_id, cashfree_order_id=order_id, _external=True
            ),
        )

    @billing_bp.route("/cashfree/orders/<order_id>/verify", methods=["POST"])
    @limiter.limit("30 per minute")
    @_errors
    def cashfree_verify_order(order_id):
        return cashfree_payments.verify_order(order_id, actor=_actor())

    @billing_bp.route("/cashfree/webhook", methods=["POST"])
    @csrf.exempt
    @_errors
    def cashfree_webhook():
        raw = request.get_data(cache=True)
        if not cashfree.valid_webhook(raw, request.headers.get("x-webhook-timestamp"),
                                      request.headers.get("x-webhook-signature")):
            raise cashfree.CashfreeError("Invalid webhook signature.", 401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise cashfree.CashfreeError("Invalid webhook payload.", 400)
        # Failed and abandoned attempts must never downgrade an already paid order.
        if data.get("type") != "PAYMENT_SUCCESS_WEBHOOK":
            return {"received": True}
        event = data.get("data")
        event_order = event.get("order") if isinstance(event, dict) else None
        order_id = event_order.get("order_id") if isinstance(event_order, dict) else None
        if not order_id:
            raise cashfree.CashfreeError("Webhook order_id is required.", 400)
        # Treat the event only as a signal. Accounting uses saved ownership and
        # authenticated GET order/payment results, never webhook amount/status.
        return cashfree_payments.verify_order(order_id)
