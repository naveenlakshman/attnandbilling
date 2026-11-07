"""Run both container dashboard checks and reject inconsistent/unknown owners."""
import importlib.util
import sqlite3
import re
import uuid
from pathlib import Path

import pytest
import pymysql
from flask import Flask

from dashboard_schema import FINANCE_TABLES, insert_financial
from db import MySQLConnectionWrapper
from mysql_fixture import mysql_server


ROOT = Path(__file__).resolve().parents[1]


def fixture_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scratch' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mysql_copy(path, options):
    """Translate SQLite fixture types, retaining canonical ownership columns.

    Minimal parent-table fixtures have no relational FK declarations. Ownership
    attacks are deliberate data corruption; the application must reject them.
    """
    source = sqlite3.connect(path)
    source.row_factory = sqlite3.Row
    database = 'dashboard_ownership_' + uuid.uuid4().hex[:12]
    raw = pymysql.connect(**options, cursorclass=pymysql.cursors.DictCursor)
    with raw.cursor() as cur:
        cur.execute('CREATE DATABASE ' + database)
        cur.execute('USE ' + database)
        for row in source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name<>'sqlite_sequence'"):
            ddl = row['sql'].replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'INTEGER PRIMARY KEY AUTO_INCREMENT')
            ddl = ddl.replace('TEXT', 'VARCHAR(255)').replace('REAL', 'DECIMAL(14,2)')
            ddl = '\n'.join(line for line in ddl.splitlines() if not line.strip().startswith('FOREIGN KEY'))
            ddl = re.sub(r',\s*\)', ')', ddl)
            cur.execute(ddl)
            values = source.execute('SELECT * FROM ' + row['name']).fetchall()
            if values:
                columns = list(values[0].keys())
                cur.executemany('INSERT INTO ' + row['name'] + ' (' + ','.join(columns) + ') VALUES (' +
                                ','.join(['%s'] * len(columns)) + ')', [tuple(v) for v in values])
    raw.commit()
    raw.close()
    source.close()
    return database


@pytest.mark.parametrize('name', ['test_dashboard_tenant_isolation', 'test_billing_dashboard_tenant_isolation'])
def test_container_smoke_is_collected_by_full_suite(name):
    fixture_module(name).main()


@pytest.mark.parametrize('name', ['test_dashboard_tenant_isolation', 'test_billing_dashboard_tenant_isolation'])
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('accuracy', [False, True])
@pytest.mark.parametrize('backend', ['sqlite', 'mysql'])
def test_dashboard_rejects_cross_tenant_and_unknown_financial_owners(tmp_path, name, legacy, accuracy, backend, request, monkeypatch):
    module = fixture_module(name)
    path = str(tmp_path / 'dashboard.db')
    module.seed(path, legacy=legacy, accuracy=accuracy)
    app = Flask(name)
    app.secret_key = 'isolated-ownership-regression'
    before = {i: module.dashboard_for(app, i, path) for i in [1, 7]}
    conn = module.connect(path)
    # Same invoice ID is not sufficient: every explicitly owned record and its
    # invoice/student or branch must agree. Test both directions, including 1.
    for ident, owner, parent in [(100, 1, 7), (101, 7, 1)]:
        insert_financial(conn, 'receipts', id=ident, institute_id=owner, invoice_id=parent, amount_received=99001)
        insert_financial(conn, 'bad_debt_writeoffs', id=ident, institute_id=owner, invoice_id=parent, amount_written_off=99002)
        insert_financial(conn, 'expenses', id=ident, institute_id=owner, branch_id=parent, amount=99003)
        insert_financial(conn, 'invoices', id=ident, institute_id=owner, student_id=parent, branch_id=owner, total_amount=99004)
        insert_financial(conn, 'receipts', id=ident+10, institute_id=owner, invoice_id=ident, amount_received=99005)
        insert_financial(conn, 'bad_debt_writeoffs', id=ident+10, institute_id=owner, invoice_id=ident, amount_written_off=10)
        insert_financial(conn, 'installment_plans', id=ident, invoice_id=ident, amount_due=99004)
    for table in FINANCE_TABLES - {'installment_plans'}:
        column = next(r for r in conn.execute(f'PRAGMA table_info({table})') if r['name'] == 'institute_id')
        assert bool(column['notnull']) is not legacy
    if legacy:
        insert_financial(conn, 'receipts', id=200, institute_id=None, invoice_id=7, amount_received=88001)
        insert_financial(conn, 'expenses', id=200, institute_id=None, branch_id=7, amount=88002)
        insert_financial(conn, 'bad_debt_writeoffs', id=200, institute_id=None, invoice_id=7, amount_written_off=88003)
        insert_financial(conn, 'invoices', id=200, institute_id=None, student_id=7, total_amount=88004)
        insert_financial(conn, 'installment_plans', id=200, invoice_id=200, amount_due=88004)
        insert_financial(conn, 'receipts', id=201, institute_id=7, invoice_id=200, amount_received=88005)
    else:
        with pytest.raises(sqlite3.IntegrityError):
            insert_financial(conn, 'receipts', id=200, institute_id=None, invoice_id=7, amount_received=1)
    conn.commit()
    conn.close()
    if backend == 'mysql':
        from config import Config
        options = request.getfixturevalue('mysql_server')
        database = mysql_copy(path, options)
        monkeypatch.setattr(Config, 'DB_TYPE', 'mysql')
        monkeypatch.setattr(module, 'connect', lambda _: MySQLConnectionWrapper(
            pymysql.connect(**options, database=database, cursorclass=pymysql.cursors.DictCursor)))
    for institute in [1, 7]:
        after = module.dashboard_for(app, institute, path)
        fields = (['revenue_this_month', 'expenses_this_month', 'total_bad_debt',
                   'total_past_due', 'total_today_due', 'total_next7_due']
                  if name == 'test_dashboard_tenant_isolation' else
                  ['total_invoices', 'total_sales', 'total_receipts', 'total_expenses',
                   'total_receivables', 'sales_data', 'receipts_data', 'expenses_data'])
        for key in fields:
            if isinstance(before[institute][key], (float, int)):
                assert after[key] == pytest.approx(before[institute][key]), key
            else:
                assert after[key] == before[institute][key], key
    # Reads did not attribute unresolved historical data or change stored rows.
    if legacy:
        conn = module.connect(path)
        for table in FINANCE_TABLES - {'installment_plans'}:
            assert conn.execute(f'SELECT institute_id FROM {table} WHERE id=200').fetchone()['institute_id'] is None
        conn.close()
