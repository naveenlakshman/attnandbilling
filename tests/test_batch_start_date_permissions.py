import sqlite3
from pathlib import Path

from flask import Flask

from modules.attendance import routes


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _build_app(tmp_path, monkeypatch, role):
    database = tmp_path / f'batch-start-{role}.db'
    conn = _connection(database)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, institute_id INTEGER, branch_id INTEGER,
            can_view_all_branches INTEGER, role TEXT, is_active INTEGER,
            full_name TEXT
        );
        CREATE TABLE branches (
            id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT,
            opening_time TEXT, closing_time TEXT, is_active INTEGER
        );
        CREATE TABLE courses (
            id INTEGER PRIMARY KEY, institute_id INTEGER, course_name TEXT,
            is_active INTEGER
        );
        CREATE TABLE batches (
            id INTEGER PRIMARY KEY, batch_name TEXT, course_id INTEGER,
            branch_id INTEGER, start_date TEXT, end_date TEXT,
            start_time TEXT, end_time TEXT, trainer_id INTEGER,
            status TEXT, updated_at TEXT
        );
        INSERT INTO users VALUES (3, 7, 2, 1, 'staff', 1, 'Trainer');
        INSERT INTO users VALUES (4, 7, 2, 1, 'admin', 1, 'Administrator');
        INSERT INTO branches VALUES (2, 7, 'Hoskote', '08:00', '20:00', 1);
        INSERT INTO courses VALUES (43, 7, 'DFA', 1);
        INSERT INTO batches VALUES (
            148, 'DFA Batch', 43, 2, '2026-11-01', '2027-04-10',
            '12:00', '14:00', 3, 'active', NULL
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(routes, 'get_conn', lambda: _connection(database))
    monkeypatch.setattr(routes, 'log_activity', lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, 'get_current_institute_id', lambda default=1: 7)

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='batch-start-permissions')
    app.register_blueprint(routes.attendance_bp, url_prefix='/attendance')
    user_id = 4 if role == 'admin' else 3
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=user_id, institute_id=7, branch_id=2, role=role)
    return client, database


def _post_edit(client, start_date):
    return client.post(
        '/attendance/batches/148/edit',
        data={
            'batch_name': 'DFA Batch',
            'course_id': '43',
            'start_date': start_date,
            'end_date': '2027-04-10',
            'start_time': '12:00',
            'end_time': '14:00',
            'trainer_id': '3',
            'status': 'active',
        },
    )


def test_staff_cannot_change_batch_start_date_with_crafted_post(tmp_path, monkeypatch):
    client, database = _build_app(tmp_path, monkeypatch, 'staff')
    response = _post_edit(client, '2026-12-15')
    assert response.status_code == 302
    conn = _connection(database)
    start_date = conn.execute('SELECT start_date FROM batches WHERE id = 148').fetchone()['start_date']
    conn.close()
    assert start_date == '2026-11-01'


def test_admin_can_change_batch_start_date(tmp_path, monkeypatch):
    client, database = _build_app(tmp_path, monkeypatch, 'admin')
    response = _post_edit(client, '2026-12-15')
    assert response.status_code == 302
    conn = _connection(database)
    start_date = conn.execute('SELECT start_date FROM batches WHERE id = 148').fetchone()['start_date']
    conn.close()
    assert start_date == '2026-12-15'


def test_staff_edit_form_marks_start_date_as_disabled():
    template = Path('templates/attendance/batch_form.html').read_text(encoding='utf-8')
    assert 'edit and not can_edit_start_date' in template
    assert 'Only an administrator can change a batch start date.' in template
