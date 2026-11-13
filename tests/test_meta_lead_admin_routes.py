import os
import sqlite3

import pytest
from flask import Flask, jsonify, session

os.environ.setdefault("SECRET_KEY", "meta-routing-isolated-test-only")

from modules.meta_leads import routes
from services import meta_lead_routes


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    path = tmp_path / "erp.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE courses(id INTEGER PRIMARY KEY,institute_id INTEGER,course_name TEXT,
            duration_hours INTEGER,is_active INTEGER);
        CREATE TABLE branches(id INTEGER PRIMARY KEY,institute_id INTEGER,branch_name TEXT,is_active INTEGER);
        CREATE TABLE batches(id INTEGER PRIMARY KEY,batch_name TEXT,course_id INTEGER,branch_id INTEGER,
            start_date TEXT,end_date TEXT,start_time TEXT,end_time TEXT,status TEXT);
        CREATE TABLE users(id INTEGER PRIMARY KEY,institute_id INTEGER,full_name TEXT,branch_id INTEGER,
            can_view_all_branches INTEGER,is_active INTEGER,role TEXT);
        CREATE TABLE institute_memberships(user_id INTEGER,institute_id INTEGER,is_active INTEGER);
        INSERT INTO courses VALUES(44,1,'DFA with AI - 225 Hours',225,1),(90,2,'Foreign',225,1);
        INSERT INTO branches VALUES(2,1,'Hoskote Branch',1),(9,2,'Foreign',1);
        INSERT INTO batches VALUES(55,'DFA 18 Nov 2026',44,2,'2026-11-18','2027-04-10','12:00','14:00','active');
        INSERT INTO users VALUES(2,1,'Chaithra',1,1,1,'staff');
        INSERT INTO institute_memberships VALUES(2,1,1);
    """)
    conn.commit(); conn.close()

    def get_conn():
        value = sqlite3.connect(path)
        value.row_factory = sqlite3.Row
        return value

    saved = []
    monkeypatch.setattr(routes, "get_conn", get_conn)
    monkeypatch.setattr(routes, "get_current_institute_id", lambda default=None: session.get("institute_id", default))
    monkeypatch.setattr(routes, "save_route", lambda **values: saved.append(values) or 7)
    monkeypatch.setattr(routes, "list_routes", lambda institute_id: ([], []))
    monkeypatch.setattr(routes, "log_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "render_template", lambda template, **values: jsonify(template=template))
    app = Flask("meta-route-admin")
    app.config.update(TESTING=True, SECRET_KEY="test-only")
    app.register_blueprint(routes.meta_leads_bp)
    app.add_url_rule("/login", endpoint="core.login", view_func=lambda: "login")
    app.add_url_rule("/dashboard", endpoint="core.dashboard", view_func=lambda: "dashboard")
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=10, role="admin", institute_id=1, branch_id=1)
    return client, saved


def mapping_form(**changes):
    values = {"page_id": "300480973645515", "form_id": "1806095097277660",
              "course_id": "44", "batch_id": "55", "branch_id": "2",
              "counsellor_user_id": "2", "is_active": "1"}
    values.update(changes)
    return values


def test_admin_can_save_consistent_cross_branch_mapping(app_client):
    client, saved = app_client
    response = client.post("/admin/meta-leads/mappings", data=mapping_form())
    assert response.status_code == 302
    assert saved == [{"institute_id": 1, "page_id": "300480973645515",
        "form_id": "1806095097277660", "course_id": 44, "batch_id": 55,
        "branch_id": 2, "counsellor_user_id": 2, "is_active": True,
        "actor_user_id": 10}]


def test_inconsistent_or_cross_tenant_mapping_is_rejected(app_client):
    client, saved = app_client
    response = client.post("/admin/meta-leads/mappings", data=mapping_form(course_id="90"))
    assert response.status_code == 200
    assert saved == []


def test_staff_cannot_open_mapping_screen(app_client):
    client, _ = app_client
    with client.session_transaction() as state:
        state["role"] = "staff"
    response = client.get("/admin/meta-leads/mappings")
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")


def test_admin_without_verified_tenant_is_denied(app_client, monkeypatch):
    client, saved = app_client
    monkeypatch.setattr(routes, "get_current_institute_id", lambda default=None: None)
    response = client.post("/admin/meta-leads/mappings", data=mapping_form())
    assert response.status_code == 403
    assert saved == []


def test_admin_with_cross_tenant_session_is_denied(app_client, monkeypatch):
    client, saved = app_client
    monkeypatch.setattr(routes, "get_current_institute_id", lambda default=None: 2)
    response = client.post("/admin/meta-leads/mappings", data=mapping_form())
    assert response.status_code == 403
    assert saved == []


def test_review_summary_query_is_tenant_scoped(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement, parameters):
            calls.append((statement, parameters))

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(meta_lead_routes, "connect", lambda: Connection())
    assert meta_lead_routes.list_routes(7) == ([], [])
    review_sql, review_parameters = calls[1]
    assert "n.institute_id=%s" in review_sql
    assert "owner.institute_id=%s" in review_sql
    assert "other.institute_id<>%s" in review_sql
    assert review_parameters == (7, 7, 7)
