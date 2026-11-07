"""Dashboard finance fixtures use db.py DDL, including ownership constraints.

Legacy mode mirrors init_db's additive SQLite compatibility step. It never
backfills ownership; pre-existing rows therefore remain explicitly unknown.
"""
import ast
import re
from datetime import date
from pathlib import Path

from db import add_column_if_not_exists


FINANCE_TABLES = {'invoices', 'receipts', 'expenses', 'bad_debt_writeoffs', 'installment_plans'}


def create_financial_schema(conn, *, legacy=False):
    remaining = FINANCE_TABLES | {'attendance_records'}
    source = Path(__file__).resolve().parents[1] / 'db.py'
    for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        match = re.match(r'\s*CREATE TABLE IF NOT EXISTS (\w+)\s*\(', node.value)
        if not match or match[1] not in remaining:
            continue
        ddl = node.value
        if legacy:
            ddl = re.sub(r'^\s*institute_id INTEGER NOT NULL,\n', '', ddl, flags=re.M)
        conn.execute(ddl)
        remaining.remove(match[1])
    assert not remaining, remaining
    if legacy:
        for table in FINANCE_TABLES - {'installment_plans'}:
            add_column_if_not_exists(conn.cursor(), table, 'institute_id', 'INTEGER')


def insert_financial(conn, table, **values):
    today = date.today().isoformat()
    defaults = dict(created_at=today, created_by=1)
    if table == 'invoices':
        defaults.update(invoice_date=today, invoice_no=f"FIXTURE-{values['id']}")
    elif table == 'receipts':
        defaults.update(receipt_date=today, receipt_no=f"FIXTURE-R-{values['id']}")
    elif table == 'expenses':
        defaults.update(expense_date=today, category_id=1, title='Fixture expense', payment_mode='cash')
    elif table == 'bad_debt_writeoffs':
        defaults.update(writeoff_date=today, reason='Fixture waiver')
        defaults.pop('created_by')
    elif table == 'installment_plans':
        defaults.update(installment_no=1, due_date=today)
        defaults.pop('created_by')
    else:
        raise ValueError(table)
    defaults.update(values)
    conn.execute(f"INSERT INTO {table} ({','.join(defaults)}) VALUES ({','.join('?' for _ in defaults)})",
                 list(defaults.values()))
