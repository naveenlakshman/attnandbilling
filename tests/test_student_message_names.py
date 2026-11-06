from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import sqlite3

import pytest
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from modules.billing.auto_reminders import _build_message
from modules.notifications import service as notices
from modules.notifications.models import Base, Notification, FeeReminderSettings
from services.student_messages import (
    invoice_message, receipt_message, registration_message, personalize_student_message,
)


def test_invoice_receipt_and_manual_reminder_senders_use_authoritative_full_name(monkeypatch):
    from modules.billing import routes
    conn=sqlite3.connect(':memory:'); conn.row_factory=sqlite3.Row
    conn.executescript('''
        CREATE TABLE students (id INTEGER,institute_id INTEGER,full_name TEXT,phone TEXT);
        CREATE TABLE invoices (id INTEGER,institute_id INTEGER,student_id INTEGER,branch_id INTEGER,invoice_no TEXT,total_amount REAL,sms_token TEXT,sms_sent_at TEXT);
        CREATE TABLE receipts (id INTEGER,invoice_id INTEGER,receipt_no TEXT,amount_received REAL,sms_token TEXT,sms_sent_at TEXT);
        CREATE TABLE installment_plans (id INTEGER,invoice_id INTEGER);
        CREATE TABLE reminder_logs (id INTEGER PRIMARY KEY,institute_id INTEGER,student_id INTEGER,invoice_id INTEGER,installment_id INTEGER,phone_number TEXT,reminder_type TEXT,message_text TEXT,status TEXT,sent_via TEXT,sent_by INTEGER,sent_at TEXT);
        INSERT INTO students VALUES (1,7,'Sujan H C','9999999999'),(2,8,'Foreign Student','8888888888');
        INSERT INTO invoices VALUES (1,7,1,7,'INV-7',1000,'invoice-token',NULL),(2,8,2,8,'INV-8',2000,'foreign-token',NULL);
        INSERT INTO receipts VALUES (1,1,'REC-7',250,'receipt-token',NULL),(2,2,'REC-8',500,'foreign-token',NULL);
        INSERT INTO installment_plans VALUES (1,1),(2,2);
    ''')
    class Connection:
        def cursor(self): return conn.cursor()
        def commit(self): conn.commit()
        def close(self): pass
    sent=[]
    monkeypatch.setattr(routes,'get_conn',Connection)
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kw:7)
    monkeypatch.setattr(routes,'send_sms',lambda phone,message:sent.append((phone,message)) or {'success':True})
    monkeypatch.setattr(routes,'log_activity',lambda **kw:None)
    app=Flask('sender-tests'); app.config.update(TESTING=True,SECRET_KEY='sender-test')
    app.register_blueprint(routes.billing_bp,url_prefix='/billing')
    client=app.test_client()
    with client.session_transaction() as state: state.update(user_id=7,role='admin',institute_id=7)
    assert client.post('/billing/invoice/1/send-sms').status_code==302
    assert 'Dear Sujan H C,' in sent[-1][1] and '/invoice/download/invoice-token' in sent[-1][1]
    assert client.post('/billing/receipt/1/send-sms').status_code==302
    assert 'Dear Sujan H C,' in sent[-1][1] and '/receipt/download/receipt-token' in sent[-1][1]
    response=client.post('/billing/reminder/send-sms',json=dict(installment_id=1,reminder_type='due_today',message_text='Please pay Rs.750.'))
    assert response.status_code==200 and sent[-1][1]=='Dear Sujan H C,\nPlease pay Rs.750.'
    assert conn.execute('SELECT message_text FROM reminder_logs').fetchone()[0]==sent[-1][1]
    before=len(sent)
    assert client.post('/billing/invoice/2/send-sms').status_code==302
    assert client.post('/billing/receipt/2/send-sms').status_code==302
    assert client.post('/billing/reminder/send-sms',json=dict(installment_id=2,reminder_type='due_today',message_text='Pay now.')).status_code==404
    assert len(sent)==before
    conn.close()


@pytest.mark.parametrize('name', ['Sujan H C', "Mary Ann D’Souza", 'ಶ್ರೀ ರಮೇಶ್ ಕುಮಾರ್'])
def test_registration_invoice_and_payment_receipts_keep_complete_names_and_references(name):
    welcome = registration_message(name, '1516559')
    invoice = invoice_message(name, 'INV-7', Decimal('1250'), 'https://example.test/invoice/token')
    receipt = receipt_message(name, 'REC-7', Decimal('250'), 'https://example.test/receipt/token')
    assert name in welcome and '1516559' in welcome
    assert f'Dear {name},' in invoice and 'INV-7' in invoice and 'Rs.1250' in invoice
    assert invoice.endswith('https://example.test/invoice/token - Global IT Education')
    assert f'Dear {name},' in receipt and 'REC-7' in receipt and 'Rs.250' in receipt
    assert receipt.endswith('https://example.test/receipt/token - Global IT Education')


@pytest.mark.parametrize('kind', ['before_3_days', 'before_2_days', 'due_today', 'overdue_day_7'])
def test_all_automatic_reminder_types_use_full_name(kind):
    message = _build_message(dict(student_name='  Sujan  H C ', balance_due=1250,
                                 due_date_iso='2026-11-06', invoice_no='INV-7'), kind,
                             dict(company_name='Test Institute', phone='9999999999'))
    assert message.startswith('Dear Sujan H C,')
    assert 'Rs.1,250' in message and 'INV-7' in message and '9999999999' in message


def test_custom_messages_are_personalized_once_without_changing_links_or_braces():
    body = 'Please pay Rs.500. https://example.test/pay/token?value={amount}'
    result = personalize_student_message(body, 'Sujan H C')
    assert result == 'Dear Sujan H C,\n'+body
    assert personalize_student_message(result, 'Sujan H C') == result
    assert personalize_student_message('Hello {student_name}, balance Rs.500.', 'Sujan H C') == 'Hello Sujan H C, balance Rs.500.'
    assert personalize_student_message('Annual fee is due.', 'Ann').startswith('Dear Ann,')
    assert registration_message('  ', '123').startswith('Welcome to Global IT Education, Student!')


def test_portal_messages_use_each_students_tenant_scoped_name_and_preserve_saved_templates(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for sql in [
            'CREATE TABLE students (id INTEGER, institute_id INTEGER, full_name TEXT)',
            'CREATE TABLE batches (id INTEGER, course_id INTEGER)',
            'CREATE TABLE student_batches (student_id INTEGER, batch_id INTEGER, status TEXT)',
            'CREATE TABLE invoices (id INTEGER, student_id INTEGER, institute_id INTEGER, invoice_no TEXT, status TEXT)',
            'CREATE TABLE installment_plans (id INTEGER, invoice_id INTEGER, due_date TEXT, amount_due REAL, amount_paid REAL, status TEXT)',
            "INSERT INTO students VALUES (1,7,'Sujan H C'),(2,7,'Mary Ann D’Souza'),(3,8,'Other Institute Student')",
            "INSERT INTO invoices VALUES (10,1,7,'INV-7','unpaid'),(20,2,7,'INV-8','unpaid')",
            "INSERT INTO installment_plans VALUES (10,10,'2026-11-07',1000,250,'pending'),(20,20,'2026-11-07',1000,0,'pending')",
        ]: conn.execute(text(sql))
    now = datetime(2026,11,6,9)
    with Session(engine) as db:
        db.add(Notification(institute_id=7, notification_type='holiday', title='Holiday',
                            message='Classes resume Monday.', icon='bi-calendar', color='success',
                            audience_type='all_students', starts_at=datetime(2026,1,1), created_by=7))
        db.commit()
    @contextmanager
    def connect():
        with Session(engine) as db: yield db
    monkeypatch.setattr(notices, 'notification_session', connect)
    for student_id, name in [(1,'Sujan H C'),(2,'Mary Ann D’Souza')]:
        messages = notices.applicable_notifications(student_id,7,now=now)
        assert len(messages)==2 and all(name in item['message'] for item in messages)
    assert notices.applicable_notifications(3,7,now=now)==[]
    # Existing due/overdue/locked templates with no name are personalized at delivery time.
    for when in (datetime(2026,11,6),datetime(2026,11,8),datetime(2026,11,15)):
        with Session(engine) as db:
            automatic = notices._automatic_fee_notifications(db,1,7,when)
            assert automatic and automatic[0]['message'].startswith('Dear Sujan H C,')
            assert 'Rs.750' in automatic[0]['message']
    with Session(engine) as db:
        db.add(FeeReminderSettings(institute_id=7, **dict(notices.DEFAULT_FEE_REMINDER_SETTINGS,
               message_template='Dear {student_name}, pay {amount} for {invoice_no}.')))
        db.commit()
    messages = notices.applicable_notifications(1,7,now=now)
    fee = next(item for item in messages if item['source']=='automatic_fee')
    assert fee['message']=='Dear Sujan H C, pay Rs.750 for INV-7.'
    with Session(engine) as db:
        assert db.get(Notification,1).message=='Classes resume Monday.'
        assert '{student_name}' in db.get(FeeReminderSettings,7).message_template
    engine.dispose()
