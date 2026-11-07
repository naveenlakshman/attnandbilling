import sqlite3

import pytest

from modules.smart_counselling import assessment_service
from test_smart_counselling_phase2 import phase2
from test_smart_counselling_phase3 import create_session, phase3, post, send, sign_in, verify


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def phase4(phase3, monkeypatch):
    app, database, transport = phase3
    conn = connect(database)
    for statement in (
        "ALTER TABLE leads ADD COLUMN email TEXT", "ALTER TABLE leads ADD COLUMN gender TEXT",
        "ALTER TABLE leads ADD COLUMN age INTEGER", "ALTER TABLE leads ADD COLUMN education_status TEXT",
        "ALTER TABLE leads ADD COLUMN stream TEXT", "ALTER TABLE leads ADD COLUMN institute_name TEXT",
        "ALTER TABLE leads ADD COLUMN career_goal TEXT", "ALTER TABLE leads ADD COLUMN start_timeframe TEXT",
        "ALTER TABLE leads ADD COLUMN lead_source TEXT", "ALTER TABLE leads ADD COLUMN decision_maker TEXT",
        "ALTER TABLE leads ADD COLUMN lead_score INTEGER DEFAULT 0", "ALTER TABLE leads ADD COLUMN updated_at TEXT",
    ):
        conn.execute(statement)
    conn.commit(); conn.close()

    def connection_factory(): return connect(database)
    monkeypatch.setattr(assessment_service, "get_conn", connection_factory)
    return app, database, transport


def identify_new(client, transport):
    session_id = create_session(client)
    challenge = send(client, session_id).get_json()["data"]
    response = verify(client, session_id, challenge["challengeId"], transport.deliveries[-1]["otp"])
    assert response.get_json()["data"]["prospect"]["status"] == "NEW"
    return session_id


def profile_payload(**changes):
    value = {
        "name": "Kiran Kumar", "age": 21, "educationStatus": "DEGREE",
        "qualification": "BCOM", "qualificationOther": None, "stream": "COMMERCE",
        "institution": "City College", "currentYear": "2nd Year",
        "currentSituation": "STUDENT", "email": "kiran@example.com",
        "whatsapp": None, "whatsappSameAsMobile": True, "gender": "MALE",
        "confirmedFields": [],
    }
    value.update(changes)
    return value


def save_profile(client, session_id, payload=None):
    return client.put(
        f"/api/smart-counselling/sessions/{session_id}/profile",
        json=payload or profile_payload(), headers={"X-CSRFToken": client.get('/test-csrf').get_json()['token']},
    )


def save_assessment(client, session_id, answers, complete=False):
    return client.put(
        f"/api/smart-counselling/sessions/{session_id}/assessment",
        json={"answers": answers, "complete": complete},
        headers={"X-CSRFToken": client.get('/test-csrf').get_json()['token']},
    )


def test_questionnaire_returns_stable_codes_without_recommendations(phase4):
    app, _, _ = phase4; client = app.test_client(); sign_in(client)
    data = client.get("/api/smart-counselling/questionnaire").get_json()["data"]
    assert data["assessmentVersion"] == "SMART_COUNSELLING_V1"
    assert {item["code"] for item in data["careerGoals"]} >= {"GET_JOB", "LEARN_ACCOUNTING"}
    assert {item["code"] for item in data["interests"]} >= {"PROGRAMMING", "TALLY"}
    assert "weights" not in str(data).lower() and "courses" not in data


def test_verified_new_profile_creates_exactly_one_tenant_scoped_lead_and_links_session(phase4):
    app, database, transport = phase4; client = app.test_client(); sign_in(client)
    session_id = identify_new(client, transport)
    response = save_profile(client, session_id)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["created"] is True and data["nextStep"] == "GOALS"
    conn = connect(database)
    lead = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (data["leadId"],)).fetchone())
    session_row = conn.execute("SELECT lead_id, status FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()
    assessment = conn.execute("SELECT assessment_version FROM counselling_assessments WHERE counselling_session_id = ?", (session_id,)).fetchone()
    event_types = {row[0] for row in conn.execute("SELECT event_type FROM counselling_events WHERE counselling_session_id = ?", (session_id,))}
    conn.close()
    assert (lead["institute_id"], lead["branch_id"], lead["assigned_to_id"]) == (1, 10, 100)
    assert lead["phone"] == "9876543210" and lead["lead_source"] == "Walk-in"
    assert tuple(session_row) == (data["leadId"], "IN_PROGRESS")
    assert assessment["assessment_version"] == "SMART_COUNSELLING_V1"
    assert {"new_lead_created", "assessment_started"} <= event_types


def test_profile_retry_is_idempotent(phase4):
    app, database, transport = phase4; client = app.test_client(); sign_in(client)
    session_id = identify_new(client, transport)
    first = save_profile(client, session_id).get_json()["data"]
    second_payload = profile_payload(confirmedFields=[])
    second = save_profile(client, session_id, second_payload)
    assert second.status_code == 200, second.get_json()
    conn = connect(database)
    assert conn.execute("SELECT COUNT(*) FROM leads WHERE institute_id = 1 AND phone = '9876543210'").fetchone()[0] == 1
    assert conn.execute("SELECT lead_id FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()[0] == first["leadId"]
    conn.close()


def test_new_lead_transaction_rolls_back_on_event_failure(phase4, monkeypatch):
    app, database, transport = phase4; client = app.test_client(); sign_in(client)
    session_id = identify_new(client, transport)
    monkeypatch.setattr(assessment_service, "insert_event", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")))
    with pytest.raises(RuntimeError):
        save_profile(client, session_id)
    conn = connect(database)
    assert conn.execute("SELECT COUNT(*) FROM leads WHERE phone = '9876543210'").fetchone()[0] == 0
    assert conn.execute("SELECT lead_id FROM counselling_sessions WHERE id = ?", (session_id,)).fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM counselling_lead_creation_requests WHERE counselling_session_id = ?", (session_id,)).fetchone()[0] == 0
    conn.close()


def test_profile_server_validation_and_csrf(phase4):
    app, _, transport = phase4; client = app.test_client(); sign_in(client)
    session_id = identify_new(client, transport)
    invalid = save_profile(client, session_id, profile_payload(name="12345"))
    assert invalid.status_code == 400
    invalid_enum = save_profile(client, session_id, profile_payload(educationStatus="MADE_UP"))
    assert invalid_enum.status_code == 400
    missing_stream = save_profile(client, session_id, profile_payload(stream=None))
    assert missing_stream.status_code == 400
    no_csrf = client.put(f"/api/smart-counselling/sessions/{session_id}/profile", json=profile_payload())
    assert no_csrf.status_code == 400


def add_existing_lead(database, *, status="active", assigned=100):
    conn = connect(database)
    conn.execute("""
        INSERT INTO leads (
            id, institute_id, name, assigned_to_id, is_deleted, phone, whatsapp, stage,
            status, branch_id, created_at, email, gender, age, education_status, stream,
            institute_name, lead_source, decision_maker, lead_score, updated_at
        ) VALUES (501, 1, 'Existing Kiran', ?, 0, '9876543210', '9876543210', 'Interested',
                  ?, 10, '2026-01-01', 'old@example.com', 'Male', 22, 'Degree Student',
                  'Commerce', 'Old College', 'Walk-in', 'Self', 0, '2026-01-01')
    """, (assigned, status))
    conn.commit(); conn.close()


def identify_existing(client, transport):
    session_id = create_session(client); challenge = send(client, session_id).get_json()["data"]
    response = verify(client, session_id, challenge["challengeId"], transport.deliveries[-1]["otp"])
    assert response.get_json()["data"]["prospect"]["status"] in {"EXISTING_LEAD", "EXISTING_STUDENT"}
    return session_id


def test_existing_lead_prefill_requires_explicit_change_confirmation_and_no_duplicate(phase4):
    app, database, transport = phase4; add_existing_lead(database, status="lost")
    client = app.test_client(); sign_in(client); session_id = identify_existing(client, transport)
    prefill = client.get(f"/api/smart-counselling/sessions/{session_id}/profile").get_json()["data"]
    assert prefill["profile"]["name"] == "Existing Kiran"
    changed = profile_payload(name="Kiran Updated", age=22, email="old@example.com", institution="Old College")
    denied = save_profile(client, session_id, changed)
    assert denied.status_code == 409 and denied.get_json()["error"]["code"] == "profile_conflict"
    changed["confirmedFields"] = ["name"]
    assert save_profile(client, session_id, changed).status_code == 200
    conn = connect(database)
    assert conn.execute("SELECT COUNT(*) FROM leads WHERE id = 501").fetchone()[0] == 1
    updated = conn.execute("SELECT name, status FROM leads WHERE id = 501").fetchone()
    assert tuple(updated) == ("Kiran Updated", "lost")
    conn.close()


def test_cross_counsellor_and_converted_student_profile_protection(phase4):
    app, database, transport = phase4; add_existing_lead(database, assigned=102)
    client = app.test_client(); sign_in(client)
    session_id = create_session(client); challenge = send(client, session_id).get_json()["data"]
    restricted = verify(client, session_id, challenge["challengeId"], transport.deliveries[-1]["otp"])
    assert restricted.get_json()["data"]["prospect"]["status"] == "EXISTING_LEAD_RESTRICTED"
    assert save_profile(client, session_id).status_code == 409


def test_converted_student_profile_remains_locked(phase4):
    app, database, transport = phase4; add_existing_lead(database, status="converted")
    conn = connect(database)
    conn.execute("INSERT INTO students VALUES (900, 1, 501, 'STU-900', 'Existing Kiran', '9876543210')")
    conn.commit(); conn.close()
    client = app.test_client(); sign_in(client); session_id = identify_existing(client, transport)
    profile = client.get(f"/api/smart-counselling/sessions/{session_id}/profile").get_json()["data"]
    assert profile["locked"] is True
    assert save_profile(client, session_id).status_code == 409


def test_override_new_profile_preserves_unverified_identity(phase4):
    app, database, _ = phase4; client = app.test_client(); sign_in(client, user_id=101)
    session_id = create_session(client)
    override = post(client, f"/api/smart-counselling/sessions/{session_id}/otp/override", {"mobile": "9876543210", "reason": "NETWORK_ISSUE"})
    assert override.get_json()["data"]["verification"]["verified"] is False
    assert override.get_json()["data"]["nextStep"] == "PROFILE"
    response = save_profile(client, session_id)
    assert response.status_code == 200
    conn = connect(database)
    row = conn.execute("SELECT cs.mobile_verified, cs.verification_method, l.phone FROM counselling_sessions cs JOIN leads l ON l.id=cs.lead_id WHERE cs.id=?", (session_id,)).fetchone()
    conn.close()
    assert tuple(row) == (0, "OVERRIDE", "9876543210")


def test_partial_assessment_resume_validation_and_completion(phase4):
    app, database, transport = phase4; client = app.test_client(); sign_in(client)
    session_id = identify_new(client, transport); assert save_profile(client, session_id).status_code == 200
    goals = {"primary_goal": "GET_JOB", "interests": ["PROGRAMMING", "AI_TOOLS"], "start_timeframe": "IMMEDIATELY"}
    partial = save_assessment(client, session_id, goals)
    assert partial.status_code == 200 and partial.get_json()["data"]["nextStep"] == "SKILLS"
    resumed = client.get(f"/api/smart-counselling/sessions/{session_id}/assessment").get_json()["data"]
    assert resumed["answers"]["interests"] == ["PROGRAMMING", "AI_TOOLS"]
    invalid = save_assessment(client, session_id, {"computer_skill": "EXPERT"})
    assert invalid.status_code == 400
    missing_programming = save_assessment(client, session_id, {"computer_skill": "BASIC", "accounting_skill": "NONE", "excel_skill": "BASIC", "english_skill": "AVERAGE"}, complete=True)
    assert missing_programming.status_code == 400
    complete = save_assessment(client, session_id, {"computer_skill": "BASIC", "accounting_skill": "NONE", "excel_skill": "BASIC", "english_skill": "AVERAGE", "programming_experience": "BASIC"}, complete=True)
    assert complete.status_code == 200 and complete.get_json()["data"]["assessmentComplete"] is True
    conn = connect(database)
    row = conn.execute("SELECT assessment_version, status FROM counselling_assessments WHERE counselling_session_id=?", (session_id,)).fetchone()
    events = {item[0] for item in conn.execute("SELECT event_type FROM counselling_events WHERE counselling_session_id=?", (session_id,))}
    conn.close(); assert tuple(row) == ("SMART_COUNSELLING_V1", "COMPLETED")
    assert {"goals_saved", "interests_saved", "skills_saved", "assessment_completed"} <= events


def test_assessment_cross_session_and_tenant_authorization(phase4):
    app, _, transport = phase4; client = app.test_client(); sign_in(client)
    session_id = identify_new(client, transport); save_profile(client, session_id)
    sign_in(client, user_id=102)
    assert client.get(f"/api/smart-counselling/sessions/{session_id}/assessment").status_code == 403
    sign_in(client, user_id=200, institute_id=2)
    assert client.get(f"/api/smart-counselling/sessions/{session_id}/assessment").status_code == 404
