import json
import sqlite3
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, session
from flask_wtf.csrf import CSRFProtect, generate_csrf

from modules.smart_counselling import auth, routes, session_service
from modules.smart_counselling.authorization import authorize_session
from modules.smart_counselling.errors import SmartCounsellingError
from modules.smart_counselling.schema import ensure_smart_counselling_schema
from modules.smart_counselling.state_machine import (
    COMPLETED,
    IDENTIFICATION_PENDING,
    IDENTIFIED,
    OUTCOME_PENDING,
    require_transition,
)


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_foundation(path):
    conn = connect(path)
    conn.executescript("""
        CREATE TABLE institutes (id INTEGER PRIMARY KEY, name TEXT, short_name TEXT);
        CREATE TABLE branches (
            id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL,
            branch_name TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(institute_id) REFERENCES institutes(id)
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL,
            username TEXT NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL,
            branch_id INTEGER, can_view_all_branches INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL, name TEXT NOT NULL,
            assigned_to_id INTEGER, is_deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE courses (id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL, course_name TEXT);
        CREATE TABLE subscription_plans (
            id INTEGER PRIMARY KEY, code TEXT, name TEXT, branch_limit INTEGER,
            staff_limit INTEGER, student_limit INTEGER, storage_limit_bytes INTEGER,
            features_json TEXT
        );
        CREATE TABLE institute_subscriptions (
            id INTEGER PRIMARY KEY, institute_id INTEGER, plan_id INTEGER, status TEXT,
            trial_ends_at TEXT, grace_ends_at TEXT, branch_limit_override INTEGER,
            staff_limit_override INTEGER, student_limit_override INTEGER,
            storage_limit_bytes_override INTEGER, feature_overrides_json TEXT
        );
        INSERT INTO institutes VALUES (1, 'Institute One', 'I1'), (2, 'Institute Two', 'I2');
        INSERT INTO branches VALUES (10, 1, 'Main Branch', 1), (11, 1, 'Second Branch', 1), (20, 2, 'Other Branch', 1);
        INSERT INTO users VALUES
            (100, 1, 'staff1', 'Staff One', 'staff', 10, 0, 1),
            (101, 1, 'admin1', 'Admin One', 'admin', 10, 1, 1),
            (102, 1, 'staff2', 'Staff Two', 'staff', 10, 0, 1),
            (200, 2, 'staff3', 'Staff Three', 'staff', 20, 0, 1);
        INSERT INTO leads VALUES (500, 1, 'Assigned Lead', 102, 0);
        INSERT INTO subscription_plans VALUES
            (1, 'enabled', 'Enabled', 10, 10, 100, 1000000, '{"smart_counselling": true}'),
            (2, 'disabled', 'Disabled', 10, 10, 100, 1000000, '{"smart_counselling": false}');
        INSERT INTO institute_subscriptions VALUES
            (1, 1, 1, 'active', NULL, NULL, NULL, NULL, NULL, NULL, NULL),
            (2, 2, 2, 'active', NULL, NULL, NULL, NULL, NULL, NULL, NULL);
    """)
    ensure_smart_counselling_schema(conn)
    conn.commit()
    conn.close()


@pytest.fixture()
def phase2(tmp_path, monkeypatch):
    database = tmp_path / "smart-counselling.db"
    create_foundation(database)

    def connection_factory():
        return connect(database)

    def current_tenant():
        institute_id = int(session.get("institute_id") or 1)
        return SimpleNamespace(
            institute_id=institute_id,
            name=f"Institute {institute_id}",
            short_name=f"I{institute_id}",
        )

    monkeypatch.setattr(auth, "get_conn", connection_factory)
    monkeypatch.setattr(auth, "require_tenant", current_tenant)
    monkeypatch.setattr(routes, "get_conn", connection_factory)
    monkeypatch.setattr(routes, "require_tenant", current_tenant)
    monkeypatch.setattr(session_service, "get_conn", connection_factory)
    monkeypatch.setattr(routes, "get_company_profile", lambda institute_id: {
        "company_name": f"Institute {institute_id}",
        "company_short_name": f"I{institute_id}",
        "primary_color": "#4a5bdb",
    })

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="phase-2-test", WTF_CSRF_ENABLED=True)
    CSRFProtect(app)
    app.register_blueprint(routes.smart_counselling_bp)

    @app.get("/test-csrf")
    def test_csrf():
        return jsonify({"token": generate_csrf()})

    return app, database


def sign_in(client, user_id=100, institute_id=1, role="staff", branch_id=10, all_branches=False):
    with client.session_transaction() as flask_session:
        flask_session.update({
            "user_id": user_id, "institute_id": institute_id, "role": role,
            "branch_id": branch_id, "can_view_all_branches": all_branches,
            "username": f"user{user_id}", "full_name": f"User {user_id}",
        })


def csrf_token(client):
    return client.get("/test-csrf").get_json()["token"]


def post(client, path, payload=None):
    return client.post(path, json=payload or {}, headers={"X-CSRFToken": csrf_token(client)})


def create_session(client, branch_id=None):
    payload = {} if branch_id is None else {"branchId": branch_id}
    response = post(client, "/api/smart-counselling/sessions", payload)
    assert response.status_code == 201
    return response.get_json()["data"]["session"]


def test_unauthenticated_creation_is_rejected(phase2):
    app, _ = phase2
    client = app.test_client()
    response = post(client, "/api/smart-counselling/sessions")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_feature_disabled_institute_is_denied(phase2):
    app, _ = phase2
    client = app.test_client()
    sign_in(client, 200, 2, branch_id=20)
    response = post(client, "/api/smart-counselling/sessions")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "feature_disabled"


def test_creation_is_transactional_and_records_safe_event(phase2):
    app, database = phase2
    client = app.test_client()
    sign_in(client)
    created = create_session(client)
    assert created["status"] == "IDENTIFICATION_PENDING"
    assert created["prospect"] is None
    conn = connect(database)
    row = conn.execute("SELECT * FROM counselling_sessions WHERE id = ?", (created["id"],)).fetchone()
    event = conn.execute("SELECT * FROM counselling_events WHERE counselling_session_id = ?", (created["id"],)).fetchone()
    conn.close()
    assert (row["institute_id"], row["branch_id"], row["counsellor_user_id"]) == (1, 10, 100)
    assert event["event_type"] == "session_started"
    assert set(json.loads(event["metadata_json"])) == {"initialStatus"}


def test_session_creation_rolls_back_if_event_write_fails(phase2, monkeypatch):
    _, database = phase2
    actor = auth.SmartCounsellingActor(100, 1, "staff", 10, False, "staff1", "Staff One")

    def fail_event(*args, **kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(session_service, "insert_event", fail_event)
    with pytest.raises(RuntimeError):
        session_service.create_counselling_session(actor)
    conn = connect(database)
    count = conn.execute("SELECT COUNT(*) FROM counselling_sessions").fetchone()[0]
    conn.close()
    assert count == 0


def test_branch_restricted_staff_cannot_choose_or_load_other_branch(phase2):
    app, _ = phase2
    staff = app.test_client()
    sign_in(staff)
    denied = post(staff, "/api/smart-counselling/sessions", {"branchId": 11})
    assert denied.status_code == 403
    assert denied.get_json()["error"]["code"] == "branch_forbidden"

    admin = app.test_client()
    sign_in(admin, 101, 1, "admin", 10, True)
    other_branch_session = create_session(admin, 11)
    load = staff.get(f"/api/smart-counselling/sessions/{other_branch_session['id']}")
    assert load.status_code == 403
    assert load.get_json()["error"]["code"] == "branch_forbidden"


def test_all_branch_admin_without_default_branch_can_choose_active_tenant_branch(phase2):
    app, database = phase2
    conn = connect(database)
    conn.execute("UPDATE users SET branch_id = NULL WHERE id = 101")
    conn.commit()
    conn.close()

    admin = app.test_client()
    sign_in(admin, 101, 1, "admin", None, True)
    bootstrap_response = admin.get("/api/smart-counselling/bootstrap")
    assert bootstrap_response.status_code == 200
    assert bootstrap_response.get_json()["data"]["activeBranches"] == [
        {"id": 10, "name": "Main Branch"},
        {"id": 11, "name": "Second Branch"},
    ]

    created = create_session(admin, 11)
    assert created["branch"] == {"id": 11, "name": "Second Branch"}


def test_staff_cannot_open_another_counsellors_session(phase2):
    app, _ = phase2
    owner = app.test_client()
    sign_in(owner, 102, 1, branch_id=10)
    created = create_session(owner)
    other_staff = app.test_client()
    sign_in(other_staff, 100, 1, branch_id=10)
    response = other_staff.get(f"/api/smart-counselling/sessions/{created['id']}")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_cross_tenant_load_and_mutation_are_not_found(phase2):
    app, database = phase2
    owner = app.test_client()
    sign_in(owner)
    created = create_session(owner)
    conn = connect(database)
    conn.execute("UPDATE subscription_plans SET features_json = ? WHERE id = 2", ('{"smart_counselling": true}',))
    conn.commit()
    conn.close()

    other = app.test_client()
    sign_in(other, 200, 2, branch_id=20)
    load = other.get(f"/api/smart-counselling/sessions/{created['id']}")
    abandon = post(other, f"/api/smart-counselling/sessions/{created['id']}/abandon")
    assert load.status_code == 404
    assert abandon.status_code == 404


def test_resume_survives_new_client_and_records_event(phase2):
    app, database = phase2
    first = app.test_client()
    sign_in(first)
    created = create_session(first)

    refreshed = app.test_client()
    sign_in(refreshed)
    loaded = refreshed.get(f"/api/smart-counselling/sessions/{created['id']}")
    resumed = post(refreshed, f"/api/smart-counselling/sessions/{created['id']}/resume")
    assert loaded.status_code == 200
    assert resumed.status_code == 200
    conn = connect(database)
    events = [row[0] for row in conn.execute(
        "SELECT event_type FROM counselling_events WHERE counselling_session_id = ? ORDER BY id",
        (created["id"],),
    )]
    conn.close()
    assert events == ["session_started", "session_resumed"]


def test_abandonment_is_terminal_and_audited(phase2):
    app, database = phase2
    client = app.test_client()
    sign_in(client)
    created = create_session(client)
    abandoned = post(client, f"/api/smart-counselling/sessions/{created['id']}/abandon", {"reason": "Prospect left"})
    repeated = post(client, f"/api/smart-counselling/sessions/{created['id']}/abandon")
    assert abandoned.get_json()["data"]["session"]["status"] == "ABANDONED"
    assert repeated.status_code == 409
    conn = connect(database)
    event = conn.execute("SELECT metadata_json FROM counselling_events WHERE event_type = 'session_abandoned'").fetchone()
    conn.close()
    assert json.loads(event["metadata_json"])["reasonProvided"] is True
    assert "Prospect left" not in event["metadata_json"]


def test_state_machine_accepts_valid_and_rejects_invalid_transition():
    require_transition(IDENTIFICATION_PENDING, IDENTIFIED)
    with pytest.raises(SmartCounsellingError) as exc:
        require_transition(IDENTIFICATION_PENDING, "COMPLETED")
    assert exc.value.code == "invalid_transition"


def test_completion_foundation_is_server_controlled_and_terminal(phase2):
    _, database = phase2
    actor = auth.SmartCounsellingActor(100, 1, "staff", 10, False, "staff1", "Staff One")
    created = session_service.create_counselling_session(actor)
    conn = connect(database)
    conn.execute(
        "UPDATE counselling_sessions SET status = ? WHERE id = ? AND institute_id = 1",
        (OUTCOME_PENDING, created["id"]),
    )
    conn.commit()
    conn.close()
    completed = session_service.transition_counselling_session(actor, created["id"], COMPLETED)
    assert completed["status"] == COMPLETED
    assert completed["completedAt"] is not None
    with pytest.raises(SmartCounsellingError) as exc:
        session_service.transition_counselling_session(actor, created["id"], "ABANDONED")
    assert exc.value.code == "session_completed"


def test_linked_lead_ownership_uses_secure_default():
    actor = auth.SmartCounsellingActor(100, 1, "staff", 10, False, "staff1", "Staff One")
    row = {
        "institute_id": 1, "branch_id": 10, "counsellor_user_id": 100,
        "lead_id": 500, "lead_assigned_to_id": 102,
    }
    with pytest.raises(SmartCounsellingError) as exc:
        authorize_session(actor, row)
    assert exc.value.code == "forbidden"


def test_csrf_is_required_for_create_and_abandon(phase2):
    app, _ = phase2
    client = app.test_client()
    sign_in(client)
    missing_create = client.post("/api/smart-counselling/sessions", json={})
    assert missing_create.status_code == 400
    assert missing_create.get_json()["error"]["code"] == "validation_error"
    created = create_session(client)
    missing_abandon = client.post(f"/api/smart-counselling/sessions/{created['id']}/abandon", json={})
    assert missing_abandon.status_code == 400


def test_dashboard_uses_real_scoped_session_records(phase2):
    app, _ = phase2
    client = app.test_client()
    sign_in(client)
    first = create_session(client)
    create_session(client)
    post(client, f"/api/smart-counselling/sessions/{first['id']}/abandon")
    response = client.get("/api/smart-counselling/dashboard")
    metrics = response.get_json()["data"]["metrics"]
    recent = response.get_json()["data"]["recentSessions"]
    assert metrics["todaySessions"] == 2
    assert metrics["newUnlinkedSessions"] == 1
    assert metrics["openSessions"] == 1
    assert metrics["readyForAdmission"] is None
    assert len(recent) == 2
    assert any(row["prospect"] is None for row in recent)
