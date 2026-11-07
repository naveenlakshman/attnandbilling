import csv
import io
from decimal import Decimal

import pytest

from modules.reports import routes
from test_course_billing_reports import connect, web
from test_receipt_report_export import receipts


@pytest.fixture()
def invoices(connect, receipts):
    conn = connect()
    conn.executescript('''
        ALTER TABLE invoices ADD COLUMN created_by INTEGER;
        ALTER TABLE invoices ADD COLUMN created_at TEXT;
        ALTER TABLE invoices ADD COLUMN notes TEXT;
        CREATE TABLE bad_debt_writeoffs (id INTEGER PRIMARY KEY,institute_id INTEGER,
            invoice_id INTEGER,amount_written_off NUMERIC);
        UPDATE invoices SET created_by=10,created_at='2026-11-07T10:00:00',notes='Invoice note' WHERE institute_id=7;
        UPDATE invoices SET created_by=20 WHERE institute_id=16;
        UPDATE invoices SET created_by=20 WHERE id=103;
        UPDATE invoices SET created_by=999 WHERE id=104;
        UPDATE invoices SET created_by=NULL WHERE id=105;
        UPDATE invoices SET created_by=11 WHERE id=106;
        UPDATE invoices SET status='write_off' WHERE id=102;
        INSERT INTO bad_debt_writeoffs VALUES
            (1,7,101,100.10),(2,7,101,0.20),(3,7,102,500),
            (4,16,101,999),(5,16,109,25),(6,7,109,123),(7,7,999,20);
    ''')
    conn.commit();conn.close()
    return receipts


def export(client):
    response = client.get('/reports/export/invoices')
    assert response.status_code == 200
    assert 'invoices_' in response.headers['Content-Disposition']
    assert response.data.startswith(b'\xef\xbb\xbf')
    reader = csv.DictReader(io.StringIO(response.data.decode('utf-8-sig')))
    return reader.fieldnames, {row['id']:row for row in reader}


def test_invoice_export_shows_names_and_retains_other_invoice_fields(invoices):
    _, client = invoices
    columns, rows = export(client)
    assert {'created_by_name','institute_name','total_written_off'} <= set(columns)
    assert not {'created_by','institute_id'} & set(columns)
    assert len(columns) == len(set(columns))
    assert rows['101']['created_by_name'] == 'Naveen Lakshman'
    assert rows['101']['institute_name'] == 'Global IT Education'
    assert rows['101']['student_id'] == '701'
    assert rows['101']['branch_id'] == '7'
    assert rows['101']['invoice_no'] == 'INV-101'
    assert rows['101']['invoice_date'] == '2026-01-10'
    assert rows['101']['notes'] == 'Invoice note'
    assert rows['101']['created_at'] == '2026-11-07T10:00:00'


def test_multiple_writeoffs_sum_once_per_invoice_without_multiplying_invoice_totals(invoices):
    _, client = invoices
    _, rows = export(client)
    assert set(rows) == {str(i) for i in range(101,109)}
    assert Decimal(rows['101']['total_written_off']) == Decimal('100.30')
    assert rows['101']['status'] == 'paid'  # Use actual write-offs even when status is stale.
    assert Decimal(rows['102']['total_written_off']) == Decimal('500.00')
    assert rows['102']['status'] == 'write_off'
    assert sum(Decimal(row['total_amount']) for row in rows.values()) == Decimal('1761.00')
    assert sum(Decimal(row['total_written_off']) for row in rows.values()) == Decimal('600.30')
    assert all(Decimal(rows[str(i)]['total_written_off']) == 0 for i in range(103,109))


def test_invalid_creator_lookups_do_not_expose_foreign_names_or_drop_invoices(invoices):
    _, client = invoices
    _, rows = export(client)
    for invoice_id in ('103','104','105'):
        assert rows[invoice_id]['created_by_name'] == ''
        assert rows[invoice_id]['institute_name'] == 'Global IT Education'
    assert rows['106']['created_by_name'] == 'counter'
    assert 'Foreign user' not in str(rows) and 'Other Institute' not in str(rows)


def test_writeoffs_and_names_are_restricted_to_the_selected_institute(invoices, monkeypatch):
    _, client = invoices
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kwargs:16)
    with client.session_transaction() as state:
        state['institute_id'] = 16
    _, rows = export(client)
    assert set(rows) == {'109'}
    assert rows['109']['created_by_name'] == 'Foreign user'
    assert rows['109']['institute_name'] == 'Other Institute'
    assert Decimal(rows['109']['total_written_off']) == Decimal('25.00')


def test_names_remain_excel_text_and_writeoffs_remain_numeric(invoices, connect):
    conn = connect()
    conn.execute("UPDATE users SET full_name='=2+3' WHERE id=10")
    conn.execute("UPDATE institutes SET name='@SUM(1,2)' WHERE id=7")
    conn.commit();conn.close()
    _, client = invoices
    _, rows = export(client)
    assert rows['101']['created_by_name'] == "'=2+3"
    assert rows['101']['institute_name'] == "'@SUM(1,2)"
    assert Decimal(rows['101']['total_written_off']) == Decimal('100.30')


@pytest.mark.parametrize('logged_in,role,location', [(False,None,'/login'),(True,'staff','/dashboard')])
def test_invoice_export_remains_admin_only(invoices, logged_in, role, location):
    _, client = invoices
    with client.session_transaction() as state:
        state.clear()
        if logged_in:
            state.update(user_id=10,institute_id=7,role=role)
    response = client.get('/reports/export/invoices')
    assert response.status_code == 302 and response.location.endswith(location)
