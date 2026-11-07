import csv
import io
from decimal import Decimal

import pytest

from modules.reports import routes
from test_course_billing_reports import connect, web


@pytest.fixture()
def expenses(connect, web):
    conn = connect()
    conn.executescript('''
        CREATE TABLE institutes (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE expense_categories (id INTEGER PRIMARY KEY,institute_id INTEGER,category_name TEXT);
        CREATE TABLE expenses (id INTEGER PRIMARY KEY,expense_date TEXT,branch_id INTEGER,category_id INTEGER,
            title TEXT,amount NUMERIC,payment_mode TEXT,reference_no TEXT,notes TEXT,created_by INTEGER,institute_id INTEGER);
        INSERT INTO institutes VALUES (7,'Global IT Education'),(16,'Other Institute');
        INSERT INTO expense_categories VALUES (7,7,'Rent'),(8,7,'Travel'),(16,16,'Foreign category');
        INSERT INTO expenses VALUES
            (1,'2026-11-01',7,7,'Office rent',1000,'cash','REF-1','Monthly rent',10,7),
            (2,'2026-11-02',8,8,'Fuel',250,'upi','REF-2',NULL,10,7),
            (3,'2026-11-02',16,16,'Foreign expense',100000,'cash',NULL,NULL,16,16),
            (4,'2026-11-03',16,16,'Invalid references',25,'cash',NULL,NULL,10,7),
            (5,'2026-11-04',999,999,'Missing references',50,'cash',NULL,NULL,10,7),
            (6,'2026-11-05',NULL,NULL,'Unassigned references',0,'cash',NULL,NULL,10,7);
    ''')
    conn.commit()
    conn.close()
    return web


def export(client):
    response = client.get('/reports/export/expenses')
    assert response.status_code == 200
    assert 'expenses_' in response.headers['Content-Disposition']
    assert response.data.startswith(b'\xef\xbb\xbf')
    reader = csv.DictReader(io.StringIO(response.data.decode('utf-8-sig')))
    return reader.fieldnames, {row['id']:row for row in reader}


def test_expense_export_replaces_ids_with_names_and_preserves_other_fields(expenses):
    _, client = expenses
    columns, rows = export(client)
    assert columns[:5] == ['id','expense_date','branch_name','category_name','title']
    assert columns[-1] == 'institute_name'
    assert len(columns) == len(set(columns))
    assert not {'branch_id','category_id','institute_id'} & set(columns)
    assert rows['1']['branch_name'] == 'Hoskote'
    assert rows['1']['category_name'] == 'Rent'
    assert rows['1']['institute_name'] == 'Global IT Education'
    assert rows['2']['branch_name'] == 'Head Office'
    assert rows['2']['category_name'] == 'Travel'
    assert rows['1']['reference_no'] == 'REF-1'
    assert rows['1']['notes'] == 'Monthly rent'
    assert rows['1']['created_by'] == '10'
    assert sum(Decimal(row['amount']) for row in rows.values()) == Decimal('1325')


def test_foreign_or_missing_lookup_records_cannot_leak_names_or_drop_expenses(expenses):
    _, client = expenses
    _, rows = export(client)
    assert set(rows) == {'1','2','4','5','6'}
    assert 'Foreign' not in str(rows) and 'Other Institute' not in str(rows)
    for expense_id in ('4','5','6'):
        assert rows[expense_id]['branch_name'] == ''
        assert rows[expense_id]['category_name'] == ''
        assert rows[expense_id]['institute_name'] == 'Global IT Education'


def test_export_uses_the_selected_institutes_names_only(expenses, monkeypatch):
    _, client = expenses
    monkeypatch.setattr(routes, 'get_current_institute_id', lambda **kwargs:16)
    with client.session_transaction() as state:
        state['institute_id'] = 16
    _, rows = export(client)
    assert set(rows) == {'3'}
    assert rows['3']['branch_name'] == 'Foreign branch'
    assert rows['3']['category_name'] == 'Foreign category'
    assert rows['3']['institute_name'] == 'Other Institute'


def test_unicode_and_quoted_names_are_preserved_in_excel_csv(expenses, connect):
    conn = connect()
    name = 'Global IT, "ಶಿಕ್ಷಣ"'
    conn.execute('UPDATE institutes SET name=? WHERE id=7', (name,))
    conn.commit(); conn.close()
    _, client = expenses
    _, rows = export(client)
    assert rows['1']['institute_name'] == name


def test_expense_names_are_csv_text_and_amounts_stay_numeric(expenses, connect):
    conn = connect()
    conn.execute("UPDATE institutes SET name='=2+3' WHERE id=7")
    conn.execute("UPDATE expense_categories SET category_name='@SUM(1,2)' WHERE id=7")
    conn.execute("UPDATE branches SET branch_name='+command' WHERE id=7")
    conn.execute('UPDATE expenses SET amount=-299 WHERE id=1')
    conn.commit(); conn.close()
    _, client = expenses
    _, rows = export(client)
    assert rows['1']['institute_name'] == "'=2+3"
    assert rows['1']['category_name'] == "'@SUM(1,2)"
    assert rows['1']['branch_name'] == "'+command"
    assert Decimal(rows['1']['amount']) == Decimal('-299')


def test_other_table_exports_keep_their_existing_columns(expenses):
    _, client = expenses
    response = client.get('/reports/export/branches')
    assert response.status_code == 200
    reader = csv.DictReader(io.StringIO(response.data.decode()))
    assert reader.fieldnames == ['id','institute_id','branch_name']
    assert {row['id'] for row in reader} == {'7','8'}


@pytest.mark.parametrize('logged_in,role,location', [(False,None,'/login'),(True,'staff','/dashboard')])
def test_expense_export_still_requires_admin(expenses, logged_in, role, location):
    _, client = expenses
    with client.session_transaction() as state:
        state.clear()
        if logged_in:
            state.update(user_id=10,institute_id=7,role=role)
    response = client.get('/reports/export/expenses')
    assert response.status_code == 302
    assert response.location.endswith(location)
