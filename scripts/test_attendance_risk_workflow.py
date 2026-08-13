"""Regression checks for tenant-safe attendance risk and append-only follow-ups."""

import sqlite3
import sys
from pathlib import Path

from flask import Flask, session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.attendance import routes


class TestConnection(sqlite3.Connection):
    def close(self):
        """Routes own production connections; keep this shared test connection open."""


def database():
    conn = sqlite3.connect(':memory:', factory=TestConnection)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE branches (id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT, is_active INTEGER);
        CREATE TABLE users (id INTEGER PRIMARY KEY, institute_id INTEGER, full_name TEXT, role TEXT, branch_id INTEGER, can_view_all_branches INTEGER, is_active INTEGER);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, course_name TEXT);
        CREATE TABLE batches (id INTEGER PRIMARY KEY, batch_name TEXT, course_id INTEGER, branch_id INTEGER, trainer_id INTEGER, status TEXT);
        CREATE TABLE students (id INTEGER PRIMARY KEY, institute_id INTEGER, student_code TEXT, full_name TEXT, phone TEXT, status TEXT, branch_id INTEGER);
        CREATE TABLE student_batches (student_id INTEGER, batch_id INTEGER, status TEXT);
        CREATE TABLE attendance_records (id INTEGER PRIMARY KEY, attendance_date TEXT, student_id INTEGER, batch_id INTEGER, branch_id INTEGER, status TEXT);
        CREATE TABLE attendance_followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER, student_id INTEGER,
            branch_id INTEGER, batch_id INTEGER, followup_date TEXT, followup_status TEXT,
            last_followup_date TEXT, remarks TEXT, created_by INTEGER, contact_channel TEXT,
            contact_person TEXT, next_followup_date TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institute_id INTEGER, user_id INTEGER,
            branch_id INTEGER, action_type TEXT, module_name TEXT, record_id INTEGER,
            description TEXT, created_at TEXT
        );

        INSERT INTO branches VALUES (1, 1, 'Tenant One', 1), (2, 2, 'Tenant Two', 1);
        INSERT INTO users VALUES (10, 1, 'Trainer One', 'staff', 1, 0, 1), (20, 2, 'Trainer Two', 'staff', 2, 0, 1);
        INSERT INTO courses VALUES (1, 'Accounting'), (2, 'Other Tenant Course');
        INSERT INTO batches VALUES (11, 'Morning', 1, 1, 10, 'active'), (22, 'Foreign', 2, 2, 20, 'active');
        INSERT INTO students VALUES
            (101, 1, 'T1-101', 'Risk Student', '9000000001', 'active', 1),
            (102, 1, 'T1-102', 'No Data Student', '9000000002', 'active', 1),
            (201, 2, 'T2-201', 'Foreign Student', '9000000003', 'active', 2);
        INSERT INTO student_batches VALUES (101, 11, 'active'), (102, 11, 'active'), (201, 22, 'active');
        INSERT INTO attendance_records VALUES
            (1, '2026-08-01', 101, 11, 1, 'present'),
            (2, '2026-08-02', 101, 11, 1, 'late'),
            (3, '2026-08-03', 101, 11, 1, 'absent'),
            (4, '2026-08-04', 101, 11, 1, 'absent'),
            (5, '2026-08-05', 101, 11, 1, 'leave'),
            (6, '2026-08-01', 201, 22, 2, 'absent'),
            (7, '2026-08-02', 201, 22, 2, 'absent'),
            (8, '2026-08-03', 201, 22, 2, 'absent');
    """)
    return conn


def filters():
    return {
        'date_from': '2026-08-01', 'date_to': '2026-08-31', 'threshold': 75.0,
        'min_sessions': 3, 'branch_id': None, 'batch_id': None, 'trainer_id': None,
        'student_status': 'active', 'followup_status': 'all',
    }


def test_calculation_and_tenant_scope():
    conn = database()
    rows = routes._attendance_risk_rows(conn.cursor(), 1, filters())
    assert len(rows) == 1
    assert rows[0]['student_id'] == 101
    assert rows[0]['eligible_sessions'] == 4
    assert rows[0]['leave_count'] == 1
    assert rows[0]['attendance_percentage'] == 50.0
    sqlite3.Connection.close(conn)


def test_followups_are_append_only():
    conn = database()
    app = Flask(__name__)
    app.secret_key = 'attendance-risk-test'
    original_conn = routes.get_conn
    original_tenant = routes.get_current_institute_id
    try:
        routes.get_conn = lambda: conn
        routes.get_current_institute_id = lambda default=None: 1
        for status in ('contacted', 'resolved'):
            with app.test_request_context('/attendance/defaulters/101/add-followup', method='POST', data={
                'batch_id': '11', 'followup_date': '2026-08-13', 'followup_status': status,
                'contact_channel': 'phone', 'contact_person': 'Student',
                'remarks': 'Attendance plan agreed.',
            }):
                session['user_id'] = 10
                response, code = routes.add_followup.__wrapped__(101)
                assert code == 200, response.get_json()
        assert conn.execute('SELECT COUNT(*) FROM attendance_followups').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM activity_logs').fetchone()[0] == 2
    finally:
        routes.get_conn = original_conn
        routes.get_current_institute_id = original_tenant
        sqlite3.Connection.close(conn)


if __name__ == '__main__':
    test_calculation_and_tenant_scope()
    test_followups_are_append_only()
    print('PASS: attendance risk calculation, tenant scope, and append-only follow-ups.')
