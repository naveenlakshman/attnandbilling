from types import SimpleNamespace

import pytest
from flask import Flask

from modules.smart_counselling import auth, routes


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((" ".join(query.split()), tuple(params)))
        if "FROM users" in query:
            return FakeResult({
                "id": 22, "username": "counsellor", "full_name": "Test Counsellor",
                "role": "staff", "branch_id": 3, "institute_id": 7,
                "can_view_all_branches": 0, "is_active": 1,
            })
        if "FROM branches" in query:
            return FakeResult([{"id": 3, "branch_name": "Main Branch"}])
        if "lead_source" in query:
            return FakeResult({"count": 4})
        if "next_followup_date" in query:
            return FakeResult({"count": 2})
        raise AssertionError(f"Unexpected query: {query}")

    def close(self):
        return None


class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


@pytest.fixture()
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="phase-1-test")
    app.register_blueprint(routes.smart_counselling_bp)
    connections = []

    def connection_factory():
        connection = FakeConnection()
        connections.append(connection)
        return connection

    tenant = SimpleNamespace(institute_id=7, display_name="Tenant Seven")
    monkeypatch.setattr(auth, "get_conn", connection_factory)
    monkeypatch.setattr(auth, "require_tenant", lambda: tenant)
    monkeypatch.setattr(auth, "assert_feature_enabled", lambda conn, institute_id, feature: None)
    monkeypatch.setattr(routes, "get_conn", connection_factory)
    monkeypatch.setattr(routes, "require_tenant", lambda: tenant)
    monkeypatch.setattr(routes, "get_company_profile", lambda institute_id: {
        "company_name": "Tenant Seven Institute",
        "company_short_name": "T7",
        "primary_color": "#3344aa",
    })
    return app.test_client(), connections


def sign_in(client, institute_id=7):
    with client.session_transaction() as flask_session:
        flask_session.update({
            "user_id": 22, "username": "counsellor", "full_name": "Test Counsellor",
            "role": "staff", "branch_id": 3, "can_view_all_branches": False,
            "institute_id": institute_id,
        })


def test_bootstrap_requires_existing_staff_session(client):
    test_client, _ = client
    response = test_client.get("/api/smart-counselling/bootstrap")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_bootstrap_rejects_session_tenant_mismatch(client):
    test_client, _ = client
    sign_in(test_client, institute_id=99)
    response = test_client.get("/api/smart-counselling/bootstrap")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_bootstrap_returns_intentional_tenant_staff_dto(client):
    test_client, _ = client
    sign_in(test_client)
    response = test_client.get("/api/smart-counselling/bootstrap")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["data"]["tenant"] == {
        "id": 7, "name": "Tenant Seven Institute", "shortName": "T7",
        "primaryColor": "#3344aa",
    }
    assert payload["data"]["staff"]["id"] == 22
    assert payload["data"]["activeBranches"] == [{"id": 3, "name": "Main Branch"}]
    assert payload["data"]["modulePhase"] == 9


def test_dashboard_returns_intentional_phase2_contract(client, monkeypatch):
    test_client, connections = client
    monkeypatch.setattr(routes, "counselling_dashboard", lambda actor, today: {
        "metrics": {
            "todaySessions": 4,
            "newUnlinkedSessions": 2,
            "completedSessions": 1,
            "openSessions": 3,
            "readyForAdmission": None,
        },
        "recentSessions": [],
    })
    sign_in(test_client)
    response = test_client.get("/api/smart-counselling/dashboard")
    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["metrics"]["todaySessions"] == 4
    assert payload["metrics"]["newUnlinkedSessions"] == 2
    assert payload["recentSessions"] == []
