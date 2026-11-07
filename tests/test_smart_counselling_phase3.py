import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from extensions import limiter
from modules.smart_counselling import identity_resolution_service, otp_service
from modules.smart_counselling.phone import normalize_indian_mobile
from modules.smart_counselling.sms_transport import GatewaySmsTransport, SmsDeliveryError, SmsDeliveryReceipt
from test_smart_counselling_phase2 import phase2


class FakeSmsTransport:
    def __init__(self, failure=None):
        self.deliveries = []
        self.failure = failure

    def send(self, mobile, message):
        if self.failure:
            raise SmsDeliveryError(self.failure)
        match = re.search(r"OTP is ([0-9]{6})", message)
        assert match
        self.deliveries.append({"mobile": mobile, "message": message, "otp": match.group(1)})
        return SmsDeliveryReceipt(message_id=f"fake-{len(self.deliveries)}")


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sign_in(client, user_id=100, institute_id=1):
    with client.session_transaction() as flask_session:
        flask_session.update({"user_id": user_id, "institute_id": institute_id})


def csrf_token(client):
    return client.get("/test-csrf").get_json()["token"]


def post(client, path, payload=None, csrf=True):
    headers = {"X-CSRFToken": csrf_token(client)} if csrf else {}
    return client.post(path, json=payload or {}, headers=headers)


def create_session(client):
    response = post(client, "/api/smart-counselling/sessions")
    assert response.status_code == 201
    return response.get_json()["data"]["session"]["id"]


def send(client, session_id, mobile="9876543210"):
    return post(client, f"/api/smart-counselling/sessions/{session_id}/otp/send", {"mobile": mobile})


def verify(client, session_id, challenge_id, otp):
    return post(
        client,
        f"/api/smart-counselling/sessions/{session_id}/otp/verify",
        {"challengeId": challenge_id, "otp": otp},
    )


@pytest.fixture()
def phase3(phase2, monkeypatch):
    app, database = phase2
    conn = connect(database)
    for statement in (
        "ALTER TABLE leads ADD COLUMN phone TEXT",
        "ALTER TABLE leads ADD COLUMN whatsapp TEXT",
        "ALTER TABLE leads ADD COLUMN stage TEXT",
        "ALTER TABLE leads ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE leads ADD COLUMN branch_id INTEGER",
        "ALTER TABLE leads ADD COLUMN created_at TEXT",
    ):
        conn.execute(statement)
    conn.execute("""
        CREATE TABLE students (
            id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL, lead_id INTEGER,
            student_code TEXT, full_name TEXT, phone TEXT
        )
    """)
    conn.execute("UPDATE institute_subscriptions SET plan_id = 1 WHERE institute_id = 2")
    conn.commit()
    conn.close()

    def connection_factory():
        return connect(database)

    monkeypatch.setattr(otp_service, "get_conn", connection_factory)
    monkeypatch.setattr(identity_resolution_service, "get_conn", connection_factory)
    monkeypatch.setattr(otp_service, "get_company_profile", lambda _institute_id: {"company_name": "Institute One"})
    transport = FakeSmsTransport()
    app.config.update(
        SMART_COUNSELLING_SMS_TRANSPORT=transport,
        SMART_COUNSELLING_OTP_SECRET="phase-3-test-otp-secret",
        SMART_COUNSELLING_OTP_TTL_SECONDS=300,
        SMART_COUNSELLING_OTP_MAX_ATTEMPTS=5,
        SMART_COUNSELLING_OTP_RESEND_COOLDOWN_SECONDS=45,
        SMART_COUNSELLING_OTP_MOBILE_HOURLY_LIMIT=5,
        SMART_COUNSELLING_OTP_USER_HOURLY_LIMIT=30,
        SMART_COUNSELLING_OTP_SESSION_HOURLY_LIMIT=8,
        SMART_COUNSELLING_OTP_SEND_IP_LIMIT="1000 per minute",
        SMART_COUNSELLING_OTP_VERIFY_IP_LIMIT="1000 per minute",
    )
    limiter.init_app(app)
    return app, database, transport


@pytest.mark.parametrize("raw", [
    "9876543210", "+91 9876543210", "91 9876543210", "09876543210", "98765 43210",
])
def test_phone_normalization_supported_conventions(raw):
    assert normalize_indian_mobile(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["", "123", "abc9876543210", "5876543210", "+44 9876543210"])
def test_phone_normalization_rejects_invalid_values(raw):
    with pytest.raises(Exception):
        normalize_indian_mobile(raw)


def test_send_requires_authentication_and_csrf(phase3):
    app, _, _ = phase3
    client = app.test_client()
    assert send(client, 1).status_code == 401
    sign_in(client)
    session_id = create_session(client)
    response = post(client, f"/api/smart-counselling/sessions/{session_id}/otp/send", {"mobile": "9876543210"}, csrf=False)
    assert response.status_code == 400


def test_send_rechecks_feature_session_owner_and_branch(phase3):
    app, database, _ = phase3
    client = app.test_client(); sign_in(client)
    owned_session = create_session(client)

    sign_in(client, user_id=102)
    assert send(client, owned_session).status_code == 403

    sign_in(client, user_id=101)
    branch_session_response = post(client, "/api/smart-counselling/sessions", {"branchId": 11})
    branch_session = branch_session_response.get_json()["data"]["session"]["id"]
    sign_in(client, user_id=100)
    assert send(client, branch_session).status_code == 403

    conn = connect(database)
    conn.execute("UPDATE institute_subscriptions SET plan_id = 2 WHERE institute_id = 1")
    conn.commit(); conn.close()
    disabled = send(client, owned_session)
    assert disabled.status_code == 403
    assert disabled.get_json()["error"]["code"] == "feature_disabled"


def test_send_stores_only_hash_and_returns_safe_response(phase3):
    app, database, transport = phase3
    client = app.test_client(); sign_in(client)
    session_id = create_session(client)
    response = send(client, session_id)
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert set(data) == {"challengeId", "mobileMasked", "expiresInSeconds", "resendAvailableInSeconds"}
    otp = transport.deliveries[-1]["otp"]
    conn = connect(database)
    row = dict(conn.execute("SELECT * FROM counselling_otp_challenges WHERE id = ?", (data["challengeId"],)).fetchone())
    event_dump = " ".join(r[0] or "" for r in conn.execute("SELECT metadata_json FROM counselling_events"))
    conn.close()
    assert row["otp_hash"] != otp and len(row["otp_hash"]) == 64
    assert otp not in event_dump


def test_no_lead_is_revealed_before_verification(phase3):
    app, database, _ = phase3
    conn = connect(database)
    conn.execute("UPDATE leads SET phone = '9876543210', stage = 'Interested', status = 'active', branch_id = 10, created_at = '2026-01-01' WHERE id = 500")
    conn.commit(); conn.close()
    client = app.test_client(); sign_in(client)
    response = send(client, create_session(client))
    body = str(response.get_json())
    assert "Assigned Lead" not in body and "EXISTING" not in body


def test_correct_otp_identifies_new_prospect_and_survives_reload(phase3):
    app, database, transport = phase3
    client = app.test_client(); sign_in(client)
    session_id = create_session(client)
    challenge = send(client, session_id).get_json()["data"]
    result = verify(client, session_id, challenge["challengeId"], transport.deliveries[-1]["otp"])
    assert result.status_code == 200
    assert result.get_json()["data"]["prospect"]["status"] == "NEW"
    detail = client.get(f"/api/smart-counselling/sessions/{session_id}").get_json()["data"]["session"]
    assert detail["status"] == "IDENTIFIED"
    assert detail["mobileVerified"] is True
    assert detail["identificationStatus"] == "NEW"
    conn = connect(database)
    assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
    conn.close()


def test_incorrect_otp_locks_after_max_attempts_and_cannot_be_reused(phase3):
    app, _, _ = phase3
    client = app.test_client(); sign_in(client)
    session_id = create_session(client)
    challenge_id = send(client, session_id).get_json()["data"]["challengeId"]
    for attempt in range(5):
        response = verify(client, session_id, challenge_id, "000000")
        assert response.status_code in {400, 409}
    assert response.get_json()["error"]["code"] == "otp_locked"
    assert verify(client, session_id, challenge_id, "000000").get_json()["error"]["code"] == "otp_locked"


def test_expired_wrong_session_wrong_tenant_and_invalidated_challenges_fail(phase3):
    app, database, transport = phase3
    client = app.test_client(); sign_in(client)
    first = create_session(client); second = create_session(client)
    challenge = send(client, first).get_json()["data"]
    otp = transport.deliveries[-1]["otp"]
    wrong_session = verify(client, second, challenge["challengeId"], otp)
    assert wrong_session.status_code == 404

    conn = connect(database)
    expired = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE counselling_otp_challenges SET expires_at = ? WHERE id = ?", (expired, challenge["challengeId"]))
    conn.commit(); conn.close()
    assert verify(client, first, challenge["challengeId"], otp).get_json()["error"]["code"] == "otp_expired"

    challenge2 = send(client, first).get_json()["data"]
    post(client, f"/api/smart-counselling/sessions/{first}/otp/change-mobile")
    assert verify(client, first, challenge2["challengeId"], transport.deliveries[-1]["otp"]).get_json()["error"]["code"] == "otp_not_active"

    sign_in(client, user_id=200, institute_id=2)
    cross_tenant = verify(client, first, challenge2["challengeId"], "123456")
    assert cross_tenant.status_code == 404


def test_resend_cooldown_and_old_otp_invalidation(phase3):
    app, database, transport = phase3
    client = app.test_client(); sign_in(client)
    session_id = create_session(client)
    first = send(client, session_id).get_json()["data"]
    old_otp = transport.deliveries[-1]["otp"]
    blocked = send(client, session_id)
    assert blocked.status_code == 429 and blocked.get_json()["error"]["code"] == "resend_cooldown"
    conn = connect(database)
    conn.execute("UPDATE counselling_otp_challenges SET resend_available_at = '2000-01-01 00:00:00' WHERE id = ?", (first["challengeId"],))
    conn.commit(); conn.close()
    second = send(client, session_id).get_json()["data"]
    new_otp = transport.deliveries[-1]["otp"]
    assert verify(client, session_id, first["challengeId"], old_otp).get_json()["error"]["code"] == "otp_not_active"
    assert verify(client, session_id, second["challengeId"], new_otp).status_code == 200


def test_database_rate_limit_applies_to_mobile(phase3):
    app, database, _ = phase3
    app.config["SMART_COUNSELLING_OTP_MOBILE_HOURLY_LIMIT"] = 1
    client = app.test_client(); sign_in(client)
    first = create_session(client)
    assert send(client, first).status_code == 201
    second = create_session(client)
    response = send(client, second)
    assert response.status_code == 429 and response.get_json()["error"]["code"] == "rate_limited"


def add_lead(database, lead_id, *, phone, assigned_to=100, status="active", deleted=0, name="Kiran Kumar"):
    conn = connect(database)
    conn.execute(
        """
        INSERT INTO leads (id, institute_id, name, assigned_to_id, is_deleted, phone, whatsapp, stage, status, branch_id, created_at)
        VALUES (?, 1, ?, ?, ?, ?, NULL, 'Interested', ?, 10, '2026-08-01 10:00:00')
        """,
        (lead_id, name, assigned_to, deleted, phone, status),
    )
    conn.commit(); conn.close()


def identify(phase3, mobile="9876543210"):
    app, _, transport = phase3
    client = app.test_client(); sign_in(client)
    session_id = create_session(client)
    challenge = send(client, session_id, mobile).get_json()["data"]
    response = verify(client, session_id, challenge["challengeId"], transport.deliveries[-1]["otp"])
    return client, session_id, response


def test_authorized_existing_and_lost_leads_link_without_rewriting_history(phase3):
    _, database, _ = phase3
    add_lead(database, 501, phone="+91 98765 43210", status="lost")
    _, session_id, response = identify(phase3)
    data = response.get_json()["data"]
    assert data["prospect"]["status"] == "EXISTING_LEAD" and data["prospect"]["lead"]["id"] == 501
    conn = connect(database)
    row = conn.execute("SELECT lead_id FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()
    lead = conn.execute("SELECT status FROM leads WHERE id = 501").fetchone()
    conn.close()
    assert row["lead_id"] == 501 and lead["status"] == "lost"


def test_cross_counsellor_match_is_restricted_without_details_or_link(phase3):
    _, database, _ = phase3
    add_lead(database, 501, phone="9876543210", assigned_to=102)
    _, session_id, response = identify(phase3)
    data = response.get_json()["data"]
    assert data["prospect"] == {"status": "EXISTING_LEAD_RESTRICTED", "lead": None, "matches": []}
    assert response.get_json()["data"]["nextStep"] == "RESOLUTION"
    conn = connect(database)
    assert conn.execute("SELECT lead_id FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()[0] is None
    conn.close()


def test_multiple_matches_are_not_automatically_selected(phase3):
    _, database, _ = phase3
    add_lead(database, 501, phone="9876543210")
    add_lead(database, 502, phone="+919876543210", name="Second Match")
    _, session_id, response = identify(phase3)
    data = response.get_json()["data"]
    assert data["prospect"]["status"] == "MULTIPLE_MATCHES"
    assert len(data["prospect"]["matches"]) == 2
    conn = connect(database)
    assert conn.execute("SELECT lead_id FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()[0] is None
    conn.close()


def test_whatsapp_number_is_contact_only_and_never_establishes_identity(phase3):
    _, database, _ = phase3
    add_lead(database, 501, phone="9123456789")
    conn = connect(database)
    conn.execute("UPDATE leads SET whatsapp = '9876543210' WHERE id = 501")
    conn.commit(); conn.close()
    _, session_id, response = identify(phase3, "9876543210")
    assert response.get_json()["data"]["prospect"]["status"] == "NEW"
    conn = connect(database)
    assert conn.execute("SELECT lead_id FROM counselling_sessions WHERE id=?", (session_id,)).fetchone()[0] is None
    assert conn.execute("SELECT whatsapp FROM leads WHERE id=501").fetchone()[0] == "9876543210"
    conn.close()


def test_converted_student_is_recognized_without_creating_records(phase3):
    _, database, _ = phase3
    add_lead(database, 501, phone="9876543210", status="converted")
    conn = connect(database)
    conn.execute("INSERT INTO students VALUES (900, 1, 501, 'STU-900', 'Kiran Kumar', '9876543210')")
    conn.commit(); conn.close()
    _, _, response = identify(phase3)
    data = response.get_json()["data"]
    assert data["prospect"]["status"] == "EXISTING_STUDENT"
    assert data["prospect"]["lead"]["studentCode"] == "STU-900"


def test_soft_deleted_match_is_not_restored(phase3):
    _, database, _ = phase3
    add_lead(database, 501, phone="9876543210", deleted=1)
    _, _, response = identify(phase3)
    assert response.get_json()["data"]["prospect"]["status"] == "SOFT_DELETED_MATCH"
    conn = connect(database)
    assert conn.execute("SELECT is_deleted FROM leads WHERE id = 501").fetchone()[0] == 1
    conn.close()


def test_override_is_admin_only_requires_reason_and_remains_unverified(phase3):
    app, database, _ = phase3
    client = app.test_client(); sign_in(client)
    session_id = create_session(client)
    path = f"/api/smart-counselling/sessions/{session_id}/otp/override"
    assert post(client, path, {"mobile": "9876543210", "reason": "NETWORK_ISSUE"}).status_code == 403

    sign_in(client, user_id=101)
    assert post(client, path, {"mobile": "9876543210"}).status_code == 400
    assert post(client, path, {"mobile": "9876543210", "reason": "OTHER"}).status_code == 400
    response = post(client, path, {"mobile": "9876543210", "reason": "OTHER", "note": "Prospect requested in-person handling"})
    assert response.status_code == 200
    assert response.get_json()["data"]["verification"]["verified"] is False
    conn = connect(database)
    row = conn.execute("SELECT mobile_verified, verification_method, verified_mobile_normalized FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    assert tuple(row) == (0, "OVERRIDE", None)


def test_admin_can_review_and_confirm_override_identity_match(phase3):
    app, database, _ = phase3
    add_lead(database, 501, phone="9876543210", status="active")
    client = app.test_client(); sign_in(client, user_id=101)
    session_id = create_session(client)
    overridden = post(
        client,
        f"/api/smart-counselling/sessions/{session_id}/otp/override",
        {"mobile": "9876543210", "reason": "NETWORK_ISSUE"},
    )
    assert overridden.get_json()["data"]["prospect"]["status"] == "UNVERIFIED_MATCH_REQUIRES_CONFIRMATION"

    path = f"/api/smart-counselling/sessions/{session_id}/identity-resolution"
    review = client.get(path)
    assert review.status_code == 200
    candidates = review.get_json()["data"]["candidates"]
    assert len(candidates) == 1
    assert candidates[0] == {
        **candidates[0],
        "id": 501,
        "name": "Kiran Kumar",
        "stage": "Interested",
        "status": "active",
        "branch": "Main Branch",
        "assignedCounsellor": "Staff One",
        "studentCode": None,
        "archived": False,
        "viewUrl": "/leads/501",
    }
    assert candidates[0]["mobileMasked"].endswith("10")

    confirmed = post(client, path, {"leadId": 501})
    assert confirmed.status_code == 200
    data = confirmed.get_json()["data"]
    assert data["prospect"]["status"] == "EXISTING_LEAD"
    assert data["prospect"]["lead"]["id"] == 501
    assert data["nextStep"] == "PROFILE"

    conn = connect(database)
    session_row = conn.execute(
        "SELECT lead_id, status, identification_status, mobile_verified FROM counselling_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    events = [row[0] for row in conn.execute(
        "SELECT event_type FROM counselling_events WHERE counselling_session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()]
    conn.close()
    assert tuple(session_row) == (501, "IDENTIFIED", "EXISTING_LEAD", 0)
    assert events[-2:] == ["identity_match_confirmed", "lead_linked"]


def test_identity_resolution_is_admin_only(phase3):
    app, database, _ = phase3
    add_lead(database, 501, phone="9876543210", status="active")
    admin = app.test_client(); sign_in(admin, user_id=101)
    session_id = create_session(admin)
    post(admin, f"/api/smart-counselling/sessions/{session_id}/otp/override", {
        "mobile": "9876543210", "reason": "NETWORK_ISSUE",
    })

    staff = app.test_client(); sign_in(staff, user_id=100)
    response = staff.get(f"/api/smart-counselling/sessions/{session_id}/identity-resolution")
    assert response.status_code == 403


def test_sms_failure_is_safe_and_challenge_is_not_presented_as_sent(phase3):
    app, database, _ = phase3
    app.config["SMART_COUNSELLING_SMS_TRANSPORT"] = FakeSmsTransport("provider rejection")
    client = app.test_client(); sign_in(client)
    response = send(client, create_session(client))
    assert response.status_code == 503 and response.get_json()["error"]["code"] == "sms_delivery_failed"
    conn = connect(database)
    row = conn.execute("SELECT status, delivery_status FROM counselling_otp_challenges ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert tuple(row) == ("INVALIDATED", "FAILED")


@pytest.mark.parametrize("provider_result", [
    {"success": False, "error": "timeout"},
    {"success": False, "error": "provider rejection"},
])
def test_gateway_transport_maps_provider_failures(monkeypatch, provider_result):
    monkeypatch.setattr("modules.smart_counselling.sms_transport.send_sms", lambda *_args: provider_result)
    with pytest.raises(SmsDeliveryError):
        GatewaySmsTransport().send("+919876543210", "safe message")
