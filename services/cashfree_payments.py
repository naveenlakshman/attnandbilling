"""Persistent Cashfree orders and exactly-once posting into the fee ledger."""

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from db import get_conn
from services import cashfree
from services.document_numbers import allocate_document_number


def init_sqlite_schema(conn):
    # MySQL uses the explicit migration; no request-time DDL or implicit commits.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cashfree_orders (
            order_id VARCHAR(64) PRIMARY KEY,
            institute_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            amount_paise BIGINT NOT NULL CHECK(amount_paise > 0),
            request_fingerprint VARCHAR(64) NOT NULL,
            payment_session_id TEXT,
            status VARCHAR(24) NOT NULL DEFAULT 'CREATING',
            cf_payment_id VARCHAR(128) UNIQUE,
            receipt_id INTEGER UNIQUE,
            created_at VARCHAR(32) NOT NULL,
            updated_at VARCHAR(32) NOT NULL
        )
    """)
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_cashfree_invoice
                    ON cashfree_orders(institute_id, invoice_id, status)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cashfree_payment_link_orders (
        order_id VARCHAR(64) PRIMARY KEY,
        link_digest VARCHAR(64) NOT NULL,
        payment_option VARCHAR(16) NOT NULL CHECK(payment_option IN ('full','installment')),
        created_at VARCHAR(32) NOT NULL,
        FOREIGN KEY(order_id) REFERENCES cashfree_orders(order_id) ON DELETE RESTRICT
    )""")


def _now():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")


def _lock(conn):
    if current_app.config.get("DB_TYPE") != "mysql":
        conn.execute("BEGIN IMMEDIATE")


def _for_update():
    return " FOR UPDATE" if current_app.config.get("DB_TYPE") == "mysql" else ""


def _invoice(conn, invoice_id, student_id, institute_id):
    row = conn.execute("""
        SELECT i.id, i.student_id, i.branch_id, i.total_amount, i.status
        FROM invoices i JOIN students s ON s.id = i.student_id AND s.institute_id = i.institute_id
        WHERE i.id = ? AND i.student_id = ? AND i.institute_id = ?
    """ + _for_update(), (invoice_id, student_id, institute_id)).fetchone()
    if not row:
        raise cashfree.CashfreeError("Invoice not found.", 404)
    return dict(row)


def _totals(conn, invoice_id, institute_id):
    paid = conn.execute("""SELECT COALESCE(SUM(amount_received), 0) AS amount
                           FROM receipts WHERE invoice_id = ? AND institute_id = ?""",
                        (invoice_id, institute_id)).fetchone()["amount"]
    written_off = conn.execute("""SELECT COALESCE(SUM(amount_written_off), 0) AS amount
                                  FROM bad_debt_writeoffs WHERE invoice_id = ? AND institute_id = ?""",
                               (invoice_id, institute_id)).fetchone()["amount"]
    return _ledger_paise(paid), _ledger_paise(written_off)


def _ledger_paise(amount):
    return int((Decimal(str(amount or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _authorize_branch(actor, invoice):
    if (actor["role"] != "admin" and not actor["can_view_all_branches"]
            and actor["branch_id"] != invoice["branch_id"]):
        raise cashfree.CashfreeError("Invoice not found.", 404)


def get_order(conn, order_id):
    if not isinstance(order_id, str) or not re.fullmatch(r"cf_(?:live_)?[0-9]+_[a-f0-9]{32}", order_id):
        raise cashfree.CashfreeError("Order not found.", 404)
    order_mode = 'production' if order_id.startswith('cf_live_') else 'sandbox'
    if order_mode != cashfree.mode():
        raise cashfree.CashfreeError("Order not found.", 404)
    row = conn.execute("SELECT * FROM cashfree_orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row or row['institute_id'] != current_app.config.get('CASHFREE_INSTITUTE_ID', 1):
        raise cashfree.CashfreeError("Order not found.", 404)
    return dict(row)


def authorize_order(conn, order, actor):
    if order["institute_id"] != actor["institute_id"]:
        raise cashfree.CashfreeError("Order not found.", 404)
    invoice = _invoice(conn, order["invoice_id"], order["student_id"], actor["institute_id"])
    _authorize_branch(actor, invoice)


def create_order(actor, data, request_key, return_url, public_link=None):
    cashfree.require_config()
    if not isinstance(data, dict):
        raise cashfree.CashfreeError("A JSON object is required.", 400)
    try:
        student_id = int(str(data.get("student_id", "")))
        invoice_id = int(str(data["invoice_id"])) if data.get("invoice_id") is not None else None
        key = str(uuid.UUID(request_key)) if request_key else str(uuid.uuid4())
    except (ValueError, TypeError, AttributeError):
        raise cashfree.CashfreeError("Use valid student/invoice IDs and a UUID Idempotency-Key.", 400)
    amount = cashfree.amount_paise(data.get("amount"))
    phone = str(data.get("phone") or "").strip()
    email = str(data.get("email") or "").strip()
    name = str(data.get("name") or "").strip()
    if not re.fullmatch(r"(?:\+91)?[6-9][0-9]{9}", phone):
        raise cashfree.CashfreeError("Enter a valid Indian mobile number.", 400)
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise cashfree.CashfreeError("Enter a valid email address.", 400)
    if not name or len(name) > 100:
        raise cashfree.CashfreeError("Name is required (maximum 100 characters).", 400)
    institute_id = actor["institute_id"]
    prefix = 'cf_live' if cashfree.mode() == 'production' else 'cf'
    order_id = f"{prefix}_{institute_id}_{uuid.UUID(key).hex}"
    conn = get_conn()
    try:
        _lock(conn)
        if invoice_id is None:
            invoices = conn.execute("""SELECT i.id FROM invoices i
                JOIN students s ON s.id = i.student_id AND s.institute_id = i.institute_id
                WHERE i.student_id = ? AND i.institute_id = ?
                  AND i.status IN ('unpaid', 'partially_paid')""", (student_id, institute_id)).fetchall()
            if len(invoices) != 1:
                raise cashfree.CashfreeError("Specify invoice_id to select one payable student invoice.", 400)
            invoice_id = invoices[0]["id"]
            if current_app.config.get("DB_TYPE") == "mysql":
                conn.rollback()  # Do not carry a snapshot from invoice selection into the lock.
        invoice = _invoice(conn, invoice_id, student_id, institute_id)
        _authorize_branch(actor, invoice)
        if public_link:
            public_link['validate_amount'](conn, invoice)
        fingerprint_values = [actor["id"], student_id, invoice_id, amount, phone, email, name]
        if public_link:
            fingerprint_values += [public_link['digest'], public_link['option']]
        fingerprint = hashlib.sha256(json.dumps(
            fingerprint_values,
            separators=(",", ":"), ensure_ascii=True,
        ).encode()).hexdigest()
        existing = conn.execute("SELECT * FROM cashfree_orders WHERE order_id = ?", (order_id,)).fetchone()
        if existing:
            existing = dict(existing)
            if existing["request_fingerprint"] != fingerprint:
                raise cashfree.CashfreeError("This request key was already used for different payment details.", 409)
            if existing["status"] in {"PAID", "REVIEW"}:
                raise cashfree.CashfreeError("This order was already paid. Verify its status.", 409)
            if existing["payment_session_id"]:
                conn.rollback()
                return {"order_id": order_id, "payment_session_id": existing["payment_session_id"]}
        else:
            paid, written_off = _totals(conn, invoice_id, institute_id)
            balance = _ledger_paise(invoice["total_amount"]) - paid - written_off
            if invoice["status"] in {"cancelled", "write_off", "partially_written_off"} or written_off:
                raise cashfree.CashfreeError("This invoice cannot accept online payments.", 409)
            if amount > balance:
                raise cashfree.CashfreeError("Amount exceeds the current invoice balance.", 409)
            now = _now()
            conn.execute("""INSERT INTO cashfree_orders (
                order_id, institute_id, student_id, invoice_id, created_by,
                amount_paise, request_fingerprint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (order_id, institute_id, student_id, invoice_id, actor["id"], amount, fingerprint, now, now))
            if public_link:
                conn.execute('''INSERT INTO cashfree_payment_link_orders
                    (order_id,link_digest,payment_option,created_at) VALUES (?,?,?,?)''',
                    (order_id,public_link['digest'],public_link['option'],now))
        conn.commit()  # Persist the mapping before a webhook can arrive.
        payload = {
            "order_id": order_id, "order_amount": amount / 100, "order_currency": "INR",
            "customer_details": {"customer_id": f"inst_{institute_id}_student_{student_id}",
                                 "customer_phone": phone, "customer_email": email, "customer_name": name},
            "order_meta": {"return_url": return_url(invoice_id, order_id)},
        }
        notify_url = current_app.config.get("CASHFREE_NOTIFY_URL", "").strip()
        if notify_url:
            if not notify_url.startswith("https://"):
                raise cashfree.CashfreeError("CASHFREE_NOTIFY_URL must use HTTPS.", 503)
            payload["order_meta"]["notify_url"] = notify_url
        remote = cashfree.api_request("POST", "/orders", payload, key)
        if (not isinstance(remote, dict) or remote.get("order_id") != order_id
                or not isinstance(remote.get("payment_session_id"), str) or not remote["payment_session_id"]):
            raise cashfree.CashfreeError("Cashfree returned an invalid order response.")
        conn.execute("""UPDATE cashfree_orders SET payment_session_id = ?,
                        status = CASE WHEN status = 'CREATING' THEN 'ACTIVE' ELSE status END,
                        updated_at = ? WHERE order_id = ?""", (remote["payment_session_id"], _now(), order_id))
        conn.commit()
        return {"order_id": order_id, "payment_session_id": remote["payment_session_id"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_order(order_id, actor=None):
    conn = get_conn()
    try:
        order = get_order(conn, order_id)
        if actor is not None:
            authorize_order(conn, order, actor)
        # End any MySQL read transaction before external I/O and subsequent locks.
        conn.rollback()
        if order["receipt_id"] or order["status"] == "REVIEW":
            return _result(order)
    finally:
        conn.close()
    remote = cashfree.api_request("GET", f"/orders/{order_id}")
    if not isinstance(remote, dict):
        raise cashfree.CashfreeError("Cashfree returned an invalid order response.")
    if (remote.get("order_id") != order_id or remote.get("order_currency") != "INR"
            or cashfree.amount_paise(remote.get("order_amount")) != order["amount_paise"]
            or (remote.get("customer_details") or {}).get("customer_id")
            != f"inst_{order['institute_id']}_student_{order['student_id']}"):
        raise cashfree.CashfreeError("Cashfree order details do not match the saved payment.", 409)
    if remote.get("order_status") != "PAID":
        return {"status": remote.get("order_status", "PENDING"), "paid": False, "receipt_id": None,
                "payment_session_id": order["payment_session_id"] if remote.get("order_status") == "ACTIVE" else None}
    payments = cashfree.api_request("GET", f"/orders/{order_id}/payments")
    if not isinstance(payments, list):
        raise cashfree.CashfreeError("Cashfree returned an invalid payment response.")
    successful = [p for p in payments if isinstance(p, dict) and p.get("payment_status") == "SUCCESS"]
    if len(successful) != 1:
        raise cashfree.CashfreeError("Cashfree has not confirmed one successful payment. Verify again shortly.", 409)
    payment = successful[0]
    if (payment.get("payment_currency") != "INR"
            or cashfree.amount_paise(payment.get("payment_amount")) != order["amount_paise"]
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(payment.get("cf_payment_id") or ""))):
        raise cashfree.CashfreeError("Cashfree payment details do not match the saved payment.", 409)
    return _post_receipt(order_id, payment)


def _result(order):
    return {"status": order["status"], "paid": order["status"] == "PAID", "receipt_id": order["receipt_id"]}


def _audit(conn, order, invoice, action, record_id, description):
    conn.execute("""INSERT INTO activity_logs (
        institute_id, user_id, branch_id, action_type, module_name, record_id, description, created_at
    ) VALUES (?, ?, ?, ?, 'receipts', ?, ?, ?)""",
                 (order["institute_id"], order["created_by"], invoice["branch_id"], action, record_id, description, _now()))


def _post_receipt(order_id, payment):
    conn = get_conn()
    try:
        _lock(conn)
        # Lock invoice first everywhere, then the order. Different orders for the
        # same invoice serialize too. Unique payment/receipt IDs are the backstop.
        initial = get_order(conn, order_id)
        if current_app.config.get("DB_TYPE") == "mysql":
            conn.rollback()  # First consistent read must happen AFTER taking the invoice lock.
        invoice = _invoice(conn, initial["invoice_id"], initial["student_id"], initial["institute_id"])
        order = dict(conn.execute("SELECT * FROM cashfree_orders WHERE order_id = ?" + _for_update(),
                                  (order_id,)).fetchone())
        if order["receipt_id"] or order["status"] == "REVIEW":
            conn.rollback()
            return _result(order)
        paid, written_off = _totals(conn, invoice["id"], order["institute_id"])
        balance = _ledger_paise(invoice["total_amount"]) - paid - written_off
        now = _now()
        payment_id = str(payment["cf_payment_id"])
        sandbox = not order_id.startswith('cf_live_')
        gateway_label = 'Sandbox Cashfree' if sandbox else 'Cashfree'
        if (invoice["status"] in {"cancelled", "write_off", "partially_written_off"}
                or written_off or order["amount_paise"] > balance):
            conn.execute("""UPDATE cashfree_orders SET status = 'REVIEW', cf_payment_id = ?,
                            updated_at = ? WHERE order_id = ?""", (payment_id, now, order_id))
            _audit(conn, order, invoice, "reconcile", invoice["id"],
                   f"{gateway_label} payment {payment_id} for {order_id} requires reconciliation; invoice changed.")
            conn.commit()
            return {"status": "REVIEW", "paid": False, "receipt_id": None}
        cur = conn.cursor()
        settings = conn.execute("SELECT receipt_prefix FROM institute_settings WHERE institute_id = ?",
                                (order["institute_id"],)).fetchone()
        if not settings or not settings["receipt_prefix"]:
            raise cashfree.CashfreeError("Configure this institute's receipt prefix before posting payments.", 409)
        receipt_no = allocate_document_number(cur, order["institute_id"], "receipt", settings["receipt_prefix"])
        methods = payment.get("payment_method") or {}
        mode = "upi" if "upi" in methods else "card" if "card" in methods else "bank_transfer"
        cur.execute("""INSERT INTO receipts (
            receipt_no, invoice_id, institute_id, receipt_date, amount_received,
            payment_mode, notes, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (receipt_no, invoice["id"], order["institute_id"], now[:10], order["amount_paise"] / 100,
                     mode, f"{'SANDBOX ' if sandbox else ''}Cashfree order {order_id}; payment {payment_id}", order["created_by"], now))
        receipt_id = cur.lastrowid
        total_paid = paid + order["amount_paise"]
        status = "paid" if total_paid >= _ledger_paise(invoice["total_amount"]) else "partially_paid"
        conn.execute("UPDATE invoices SET status = ?, updated_at = ? WHERE id = ? AND institute_id = ?",
                     (status, now, invoice["id"], order["institute_id"]))
        installments = conn.execute("""SELECT id, amount_due FROM installment_plans
            WHERE invoice_id = ? ORDER BY installment_no, id""", (invoice["id"],)).fetchall()
        remaining = total_paid
        for installment in installments:
            due = _ledger_paise(installment["amount_due"])
            allocated = min(max(remaining, 0), due)
            installment_status = "paid" if allocated >= due else "partially_paid" if allocated else "pending"
            conn.execute("""UPDATE installment_plans SET amount_paid = ?, status = ?, updated_at = ?
                            WHERE id = ? AND invoice_id = ?""",
                         (allocated / 100, installment_status, now, installment["id"], invoice["id"]))
            remaining -= allocated
        conn.execute("""UPDATE cashfree_orders SET status = 'PAID', receipt_id = ?,
                        cf_payment_id = ?, updated_at = ? WHERE order_id = ?""",
                     (receipt_id, payment_id, now, order_id))
        _audit(conn, order, invoice, "create", receipt_id,
               f"Created {'sandbox ' if sandbox else ''}Cashfree receipt {receipt_no}; order {order_id}; payment {payment_id}")
        conn.commit()
        return {"status": "PAID", "paid": True, "receipt_id": receipt_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
