import sqlite3
import uuid

import pymysql
import pytest
from flask import Blueprint, Flask
from flask_wtf.csrf import generate_csrf

from db import MySQLConnectionWrapper
from extensions import csrf
from modules.billing import routes
from mysql_fixture import mysql_server


def application(connect,monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='expense-category-regression')
    csrf.init_app(app)
    bp = Blueprint('billing',__name__)
    bp.add_url_rule('/expense-category/new',view_func=routes.expense_category_new,methods=['GET','POST'])
    bp.add_url_rule('/expense-categories',view_func=routes.expense_categories)
    bp.add_url_rule('/expense/new',view_func=routes.expense_new,methods=['GET','POST'])
    bp.add_url_rule('/expenses',endpoint='expenses',view_func=lambda:'expenses')
    app.register_blueprint(bp,url_prefix='/billing')
    app.add_url_rule('/login',endpoint='core.login',view_func=lambda:'login')
    app.add_url_rule('/token',view_func=generate_csrf)
    audit = []
    monkeypatch.setattr(routes,'get_conn',connect)
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kwargs:7)
    monkeypatch.setattr(routes,'log_activity',lambda **values:audit.append(values))
    monkeypatch.setattr(routes,'render_template',lambda template,**context:{
        'template':template,**{key:[dict(row) for row in value] if isinstance(value,list) else value
                              for key,value in context.items()}})
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=10,institute_id=7,role='admin',branch_id=7)
    token = client.get('/token').text
    return app,client,token,audit


@pytest.fixture()
def expense_app(tmp_path,monkeypatch):
    path = tmp_path/'expense.db'
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    conn = connect()
    conn.executescript('''
        CREATE TABLE expense_categories (id INTEGER PRIMARY KEY,institute_id INTEGER NOT NULL,
            category_name TEXT NOT NULL UNIQUE,is_active INTEGER NOT NULL,created_at TEXT NOT NULL);
        INSERT INTO expense_categories VALUES (1,1,'Legacy tenant category',1,'2026-10-31'),
            (7,7,'Own active category',1,'2026-10-31'),(8,7,'Own inactive category',0,'2026-10-31'),
            (16,16,'Other tenant category',1,'2026-10-31');
        CREATE TABLE branches (id INTEGER PRIMARY KEY,institute_id INTEGER,branch_name TEXT,is_active INTEGER);
        INSERT INTO branches VALUES (1,1,'Other branch',1),(7,7,'Own branch',1);
        CREATE TABLE expenses (id INTEGER PRIMARY KEY,institute_id INTEGER NOT NULL,
            expense_date TEXT,branch_id INTEGER,category_id INTEGER,title TEXT,amount NUMERIC,
            payment_mode TEXT,reference_no TEXT,notes TEXT,created_by INTEGER,created_at TEXT,updated_at TEXT,
            FOREIGN KEY(category_id) REFERENCES expense_categories(id));
    ''')
    conn.commit();conn.close()
    return (*application(connect,monkeypatch),connect)


def post(client,token,path,data):
    return client.post(path,data=data,headers={'X-CSRFToken':token})


@pytest.mark.parametrize('tenant',[1,7])
def test_category_create_explicitly_sets_resolved_institute(expense_app,monkeypatch,tenant):
    app,client,token,audit,connect = expense_app
    monkeypatch.setattr(routes,'get_current_institute_id',lambda **kwargs:tenant)
    response = post(client,token,'/billing/expense-category/new',
                    {'category_name':'  New category  ','institute_id':'999'})
    assert response.location.endswith('/billing/expense-categories')
    conn = connect()
    row = conn.execute("SELECT * FROM expense_categories WHERE category_name='New category'").fetchone()
    conn.close()
    assert row['institute_id'] == tenant and row['is_active'] == 1
    assert audit[0]['institute_id'] == tenant and audit[0]['conn'] is not None


def test_category_list_and_expense_dropdown_only_show_own_institute(expense_app):
    app,client,token,audit,connect = expense_app
    listing = client.get('/billing/expense-categories').json['categories']
    assert {row['id'] for row in listing} == {7,8}
    form = client.get('/billing/expense/new').json
    assert {row['id'] for row in form['categories']} == {7}
    assert {row['id'] for row in form['branches']} == {7}


def test_duplicate_category_is_not_inserted_or_audited(expense_app):
    app,client,token,audit,connect = expense_app
    response = post(client,token,'/billing/expense-category/new',{'category_name':'Own active category'})
    assert response.location.endswith('/billing/expense-category/new')
    assert not audit
    with client.session_transaction() as state:
        assert any(message=='Category already exists.' for category,message in state['_flashes'])


@pytest.mark.parametrize('name',['   ','x'*256])
def test_invalid_category_name_does_not_write(expense_app,name):
    app,client,token,audit,connect = expense_app
    response = post(client,token,'/billing/expense-category/new',{'category_name':name})
    assert response.location.endswith('/billing/expense-category/new') and not audit


@pytest.mark.parametrize('branch,category',[(7,1),(1,7),(7,8),(7,999)])
def test_expense_post_rejects_foreign_inactive_or_missing_category_and_branch(expense_app,branch,category):
    app,client,token,audit,connect = expense_app
    response = post(client,token,'/billing/expense/new',dict(branch_id=branch,category_id=category,
        expense_date='2026-10-31',title='Expense',amount='25',payment_mode='cash'))
    assert response.location.endswith('/billing/expense/new')
    conn = connect()
    assert conn.execute('SELECT COUNT(*) FROM expenses').fetchone()[0] == 0
    conn.close()
    assert not audit


def test_expense_accepts_own_active_category(expense_app):
    app,client,token,audit,connect = expense_app
    response = post(client,token,'/billing/expense/new',dict(branch_id=7,category_id=7,
        expense_date='2026-10-31',title='Expense',amount='25',payment_mode='cash'))
    assert response.location.endswith('/billing/expenses')
    conn = connect()
    assert conn.execute('SELECT institute_id,category_id FROM expenses').fetchone()['institute_id'] == 7
    conn.close()


def test_category_post_requires_csrf_and_login(expense_app):
    app,client,token,audit,connect = expense_app
    assert client.post('/billing/expense-category/new',data={'category_name':'Example'}).status_code == 400
    with client.session_transaction() as state:
        state.pop('user_id')
    response = post(client,token,'/billing/expense-category/new',{'category_name':'Example'})
    assert response.location.endswith('/login') and not audit


def test_mysql_strict_category_insert_and_global_name_conflict(mysql_server,monkeypatch):
    database = 'expense_test_'+uuid.uuid4().hex
    admin = pymysql.connect(**mysql_server)
    with admin.cursor() as cursor:
        cursor.execute('CREATE DATABASE `'+database+'`')
    admin.close()
    def connect():
        return MySQLConnectionWrapper(pymysql.connect(**mysql_server,database=database))
    conn = connect()
    conn._conn.cursor().execute('''CREATE TABLE expense_categories (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,institute_id BIGINT NOT NULL,
        category_name VARCHAR(255) NOT NULL UNIQUE,is_active INT NOT NULL,created_at VARCHAR(32) NOT NULL)''')
    with pytest.raises(pymysql.err.OperationalError) as error:
        conn.execute("INSERT INTO expense_categories (category_name,is_active,created_at) VALUES ('Old insert',1,'2026-10-31')")
    assert error.value.args[0] == 1364
    conn.rollback()
    app,client,token,audit = application(connect,monkeypatch)
    response = post(client,token,'/billing/expense-category/new',{'category_name':'MySQL category'})
    assert response.location.endswith('/billing/expense-categories')
    assert conn.execute('SELECT institute_id FROM expense_categories').fetchone()['institute_id'] == 7
    conn.rollback()
    conn.execute("INSERT INTO expense_categories (institute_id,category_name,is_active,created_at) VALUES (1,'Existing global name',1,'2026-10-31')")
    conn.commit()
    conflict = post(client,token,'/billing/expense-category/new',{'category_name':'Existing global name'})
    assert conflict.location.endswith('/billing/expense-category/new')
    with client.session_transaction() as state:
        assert any('Category name is already in use.' in message for category,message in state['_flashes'])
    conn.close()
