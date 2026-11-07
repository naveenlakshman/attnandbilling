import json

import pytest

from modules.smart_counselling import course_intelligence
from test_smart_counselling_phase2 import connect, phase2, sign_in


@pytest.fixture()
def phase5(phase2, monkeypatch):
    app, database = phase2
    conn = connect(database)
    additions = [
        "ALTER TABLE courses ADD COLUMN duration TEXT", "ALTER TABLE courses ADD COLUMN duration_hours INTEGER",
        "ALTER TABLE courses ADD COLUMN fee REAL DEFAULT 0", "ALTER TABLE courses ADD COLUMN course_type TEXT DEFAULT 'standard'",
        "ALTER TABLE courses ADD COLUMN course_domain TEXT", "ALTER TABLE courses ADD COLUMN course_category TEXT",
        "ALTER TABLE courses ADD COLUMN is_active INTEGER DEFAULT 1", "ALTER TABLE courses ADD COLUMN show_on_website INTEGER DEFAULT 0",
    ]
    for statement in additions: conn.execute(statement)
    conn.executescript("""
        CREATE TABLE lms_programs (id INTEGER PRIMARY KEY, program_name TEXT, created_by INTEGER, course_id INTEGER);
        CREATE TABLE lms_course_program_map (id INTEGER PRIMARY KEY, course_id INTEGER, program_id INTEGER, display_order INTEGER);
        CREATE TABLE batches (id INTEGER PRIMARY KEY, course_id INTEGER, branch_id INTEGER, status TEXT);
        INSERT INTO courses (id,institute_id,course_name,duration,duration_hours,fee,course_type,course_domain,course_category,is_active,show_on_website)
        VALUES (1,1,'Tally Prime','3 Months',120,12000,'standard','Accounting','Certificate Course',1,1),
               (2,2,'Other Tenant Course','2 Months',80,9000,'standard','Office Tools','Short Term',1,0);
        INSERT INTO lms_programs VALUES (10,'Tally Program',101,1),(20,'Foreign Program',200,2);
        INSERT INTO lms_course_program_map VALUES (1,1,10,1),(2,1,20,2);
        INSERT INTO batches VALUES (1,1,10,'active'),(2,1,10,'completed'),(3,2,20,'active');
    """)
    conn.commit(); conn.close()
    monkeypatch.setattr(course_intelligence, "get_conn", lambda: connect(database))
    return app, database


def csrf(client): return client.get("/test-csrf").get_json()["token"]


def put(client, course_id, payload):
    return client.put(f"/api/smart-counselling/course-profiles/{course_id}", json=payload, headers={"X-CSRFToken": csrf(client)})


def complete_payload(**overrides):
    payload = {
        "coursePurpose": "Prepare learners for practical accounting work.", "shortDescription": "Practical accounting.",
        "detailedDescription": "Business-approved course profile.", "minimumEducationLevel": "PUC_2",
        "preferredBackground": "Commerce is helpful but not required.", "targetAudience": "Accounting job seekers",
        "hardEligibilityText": "PUC completion required.", "startingSkillLevel": "BEGINNER",
        "certificationTitle": "Tally Certificate", "certificationIssuingBody": "Institute",
        "certificationIncluded": True, "externalExamRequired": False, "certificationDetails": "Included after completion.",
        "recommendationEnabled": True,
        "goals": [{"code":"GET_JOB","matchStrength":"PRIMARY","isPrimary":True}],
        "interests": [{"code":"ACCOUNTING","matchStrength":"STRONG","isPrimary":True}],
        "educationSuitability": [{"code":"BCOM","type":"PREFERRED"},{"code":"COMMERCE","type":"PREFERRED"}],
        "prerequisites": [{"dimension":x,"minimumLevel":"NONE"} for x in ("COMPUTER","ACCOUNTING","EXCEL","ENGLISH","PROGRAMMING")],
        "skillsTaught": [{"code":"ACCOUNTING","isPrimary":True},{"code":"TALLY_PRIME"}],
        "learningOutcomes": ["Record accounting transactions"], "careerOutcomes": ["Entry-level accounting role"],
        "jobRoles": ["Accounts Assistant"],
    }
    payload.update(overrides); return payload


def test_admin_creates_complete_ready_profile_with_lms_and_batch_summary(phase5):
    app, database = phase5; client=app.test_client(); sign_in(client,101,role="admin",all_branches=True)
    response=put(client,1,complete_payload()); assert response.status_code==200
    data=response.get_json()["data"]
    assert data["profileComplete"] is True and data["recommendationReady"] is True
    assert data["lms"]["status"]=="LMS_MAPPED" and [x["id"] for x in data["lms"]["programs"]]==[10]
    assert data["batches"]=={"active":1,"total":2}
    conn=connect(database); event=conn.execute("SELECT event_type,changed_fields_json FROM course_profile_events").fetchone(); conn.close()
    assert event["event_type"]=="course_profile_created" and "coursePurpose" not in event["changed_fields_json"]


@pytest.mark.parametrize("field,value", [("goals",[{"code":"FAKE"}]),("interests",[{"code":"FAKE"}]),("prerequisites",[{"dimension":"COMPUTER","minimumLevel":"EXPERT"}])])
def test_invalid_taxonomy_rolls_back_without_profile(phase5,field,value):
    app,database=phase5; client=app.test_client(); sign_in(client,101,role="admin",all_branches=True)
    response=put(client,1,complete_payload(**{field:value})); assert response.status_code==400
    conn=connect(database); assert conn.execute("SELECT COUNT(*) FROM course_profiles").fetchone()[0]==0; conn.close()


def test_non_admin_denied_and_cross_tenant_course_hidden(phase5):
    app,_=phase5; staff=app.test_client(); sign_in(staff,100,role="staff")
    assert put(staff,1,complete_payload()).status_code==403
    admin=app.test_client(); sign_in(admin,101,role="admin",all_branches=True)
    assert put(admin,2,complete_payload()).status_code==404
    assert admin.get("/api/smart-counselling/course-profiles/2").status_code==404


def test_readiness_rules_and_recommendation_toggle(phase5):
    app,database=phase5; client=app.test_client(); sign_in(client,101,role="admin",all_branches=True)
    incomplete=put(client,1,complete_payload(goals=[])).get_json()["data"]
    assert incomplete["profileComplete"] is False and incomplete["recommendationReady"] is False
    disabled=put(client,1,complete_payload(recommendationEnabled=False)).get_json()["data"]
    assert disabled["profileComplete"] is True and disabled["recommendationReady"] is False
    enabled=put(client,1,complete_payload()).get_json()["data"]
    assert enabled["recommendationReady"] is True
    conn=connect(database); events=[r[0] for r in conn.execute("SELECT event_type FROM course_profile_events ORDER BY id")]; conn.close()
    assert "recommendation_enabled" in events


def test_update_replaces_mappings_without_duplicates_and_returns_lookup_contract(phase5):
    app,database=phase5; client=app.test_client(); sign_in(client,101,role="admin",all_branches=True)
    assert put(client,1,complete_payload()).status_code==200
    updated=complete_payload(goals=[{"code":"CERTIFICATION","matchStrength":"PRIMARY","isPrimary":True}], learningOutcomes=["Issue reports","Record GST"])
    assert put(client,1,updated).status_code==200
    result=client.get("/api/smart-counselling/course-profiles/1").get_json()["data"]
    assert [x["goal_code"] for x in result["goals"]]==["CERTIFICATION"] and result["learningOutcomes"]==["Issue reports","Record GST"]
    conn=connect(database); assert conn.execute("SELECT COUNT(*) FROM course_supported_goals").fetchone()[0]==1; conn.close()


def test_partial_update_preserves_unspecified_profile_and_mappings(phase5):
    app,_=phase5; client=app.test_client(); sign_in(client,101,role="admin",all_branches=True)
    assert put(client,1,complete_payload()).status_code==200
    result=put(client,1,{"targetAudience":"Small business owners"}).get_json()["data"]
    assert result["profile"]["course_purpose"].startswith("Prepare learners")
    assert result["profile"]["target_audience"]=="Small business owners" and len(result["goals"])==1


def test_list_and_taxonomy_are_read_only_for_staff(phase5):
    app,_=phase5; client=app.test_client(); sign_in(client,100,role="staff")
    assert client.get("/api/smart-counselling/course-profiles").status_code==200
    tax=client.get("/api/smart-counselling/course-profile-taxonomy").get_json()["data"]
    assert any(x["code"]=="GET_JOB" for x in tax["goals"]) and "TALLY_PRIME" in tax["skillCodes"]
