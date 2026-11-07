import csv
import io
from decimal import Decimal

import pytest

from modules.reports import routes
from test_course_billing_reports import connect, web


@pytest.fixture()
def receipts(connect, web):
    conn = connect()
    conn.executescript('''
        CREATE TABLE institutes (id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY,institute_id INTEGER,full_name TEXT,username TEXT);
        INSERT INTO institutes VALUES (7,'Global IT Education'),(16,'Other Institute');
        INSERT INTO users VALUES (10,7,'Naveen Lakshman','naveen'),(11,7,'','counter'),(20,16,'Foreign user','foreign');
        ALTER TABLE receipts ADD COLUMN created_by INTEGER;
        ALTER TABLE receipts ADD COLUMN created_at TEXT;
        ALTER TABLE receipts ADD COLUMN notes TEXT;
        UPDATE receipts SET created_by=10,created_at='2026-11-07T09:30:00',notes='Bank reference REF-123' WHERE institute_id=7;
        UPDATE receipts SET created_by=20 WHERE institute_id=16;
        UPDATE receipts SET created_by=20 WHERE id=1002;
        UPDATE receipts SET created_by=999 WHERE id=1003;
        UPDATE receipts SET created_by=NULL WHERE id=1004;
        UPDATE receipts SET created_by=11 WHERE id=1005;
    ''')
    conn.commit(); conn.close()
    return web


def export(client):
    response = client.get('/reports/export/receipts')
    assert response.status_code == 200
    assert 'receipts_' in response.headers['Content-Disposition']
    assert response.data.startswith(b'\xef\xbb\xbf')
    reader = csv.DictReader(io.StringIO(response.data.decode('utf-8-sig')))
    return reader.fieldnames, {row['id']:row for row in reader}


def test_receipt_export_replaces_creator_and_institute_ids_with_names(receipts):
    _, client = receipts
    columns, rows = export(client)
    assert {'created_by_name','institute_name'} <= set(columns)
    assert not {'created_by','institute_id'} & set(columns)
    assert len(columns) == len(set(columns))
    assert rows['1001']['created_by_name'] == 'Naveen Lakshman'
    assert rows['1001']['institute_name'] == 'Global IT Education'
    assert rows['1001']['invoice_id'] == '101'
    assert rows['1001']['receipt_no'] == 'REC-1001'
    assert rows['1001']['payment_mode'] == 'cash'
    assert rows['1001']['notes'] == 'Bank reference REF-123'
    assert rows['1001']['created_at'] == '2026-11-07T09:30:00'
    assert Decimal(rows['1001']['amount_received']) == Decimal('250')


def test_foreign_and_deleted_creators_do_not_leak_names_or_drop_receipts(receipts):
    _, client = receipts
    _, rows = export(client)
    assert set(rows) == {'1001','1002','1003','1004','1005','1006','1009'}
    assert sum(Decimal(row['amount_received']) for row in rows.values()) == Decimal('911')
    assert 'Foreign user' not in str(rows) and 'Other Institute' not in str(rows)
    for receipt_id in ('1002','1003','1004'):
        assert rows[receipt_id]['created_by_name'] == ''
        assert rows[receipt_id]['institute_name'] == 'Global IT Education'


def test_username_is_used_if_creator_has_no_full_name(receipts):
    _, client = receipts
    _, rows = export(client)
    assert rows['1005']['created_by_name'] == 'counter'


def test_other_institute_gets_only_its_own_receipts_and_creator_names(receipts, monkeypatch):
    _, client = receipts
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kwargs:16)
    with client.session_transaction() as state:
        state['institute_id'] = 16
    _, rows = export(client)
    assert set(rows) == {'1007','1008'}
    assert all(row['institute_name'] == 'Other Institute' for row in rows.values())
    assert all(row['created_by_name'] == 'Foreign user' for row in rows.values())


def test_unicode_names_and_commas_round_trip_through_excel_csv(receipts, connect):
    conn = connect()
    conn.execute('UPDATE users SET full_name=? WHERE id=10', ('ಶ್ರೀ ನವೀನ್',))
    conn.execute('UPDATE institutes SET name=? WHERE id=7', ('Global IT, "Education"',))
    conn.commit();conn.close()
    _, client = receipts
    _, rows = export(client)
    assert rows['1001']['created_by_name'] == 'ಶ್ರೀ ನವೀನ್'
    assert rows['1001']['institute_name'] == 'Global IT, "Education"'


def test_joined_names_are_spreadsheet_text_while_amounts_remain_numeric(receipts, connect):
    conn = connect()
    conn.execute("UPDATE users SET full_name='=2+3' WHERE id=10")
    conn.execute("UPDATE institutes SET name='@SUM(1,2)' WHERE id=7")
    conn.execute('UPDATE receipts SET amount_received=-25 WHERE id=1001')
    conn.commit();conn.close()
    _, client = receipts
    _, rows = export(client)
    assert rows['1001']['created_by_name'] == "'=2+3"
    assert rows['1001']['institute_name'] == "'@SUM(1,2)"
    assert Decimal(rows['1001']['amount_received']) == Decimal('-25')


@pytest.mark.parametrize('logged_in,role,location', [(False,None,'/login'),(True,'staff','/dashboard')])
def test_receipt_export_remains_admin_only(receipts, logged_in, role, location):
    _, client = receipts
    with client.session_transaction() as state:
        state.clear()
        if logged_in:
            state.update(user_id=10,institute_id=7,role=role)
    response = client.get('/reports/export/receipts')
    assert response.status_code == 302 and response.location.endswith(location)
