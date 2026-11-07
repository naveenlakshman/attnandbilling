import json

import pytest

from modules.smart_counselling import course_intelligence, recommendation_service
from test_smart_counselling_phase4 import connect, phase4
from test_smart_counselling_phase3 import phase3, sign_in
from test_smart_counselling_phase2 import phase2
from test_smart_counselling_phase5 import complete_payload


@pytest.fixture()
def phase6(phase4, monkeypatch):
    app,database,_=phase4; conn=connect(database)
    for statement in (
        "ALTER TABLE courses ADD COLUMN duration TEXT", "ALTER TABLE courses ADD COLUMN duration_hours INTEGER",
        "ALTER TABLE courses ADD COLUMN fee REAL DEFAULT 0", "ALTER TABLE courses ADD COLUMN course_type TEXT DEFAULT 'standard'",
        "ALTER TABLE courses ADD COLUMN course_domain TEXT", "ALTER TABLE courses ADD COLUMN course_category TEXT",
        "ALTER TABLE courses ADD COLUMN is_active INTEGER DEFAULT 1", "ALTER TABLE courses ADD COLUMN show_on_website INTEGER DEFAULT 0",
    ): conn.execute(statement)
    conn.executescript("""
      CREATE TABLE lms_programs(id INTEGER PRIMARY KEY,program_name TEXT,created_by INTEGER,course_id INTEGER);
      CREATE TABLE lms_course_program_map(id INTEGER PRIMARY KEY,course_id INTEGER,program_id INTEGER,display_order INTEGER);
      CREATE TABLE batches(id INTEGER PRIMARY KEY,course_id INTEGER,branch_id INTEGER,status TEXT);
      INSERT INTO courses(id,institute_id,course_name,duration,duration_hours,fee,course_type,course_domain,course_category,is_active,show_on_website) VALUES
        (1,1,'DFA','6 Months',240,18000,'standard','Accounting','Diploma',1,0),
        (2,1,'Tally Prime','3 Months',120,12000,'standard','Accounting','Certificate',1,0),
        (3,2,'Foreign Course','3 Months',100,10000,'standard','Accounting','Certificate',1,0);
      INSERT INTO leads(id,institute_id,name,assigned_to_id,is_deleted,phone,whatsapp,stage,status,branch_id,created_at,email,gender,age,education_status,stream,institute_name,career_goal,start_timeframe,lead_source,decision_maker,lead_score,updated_at)
        VALUES(700,1,'Golden Prospect',100,0,'9876543210',NULL,'Interested','active',10,'2026-08-22','x@example.com','Male',21,'Degree Student','Commerce','College','Job','Immediately','Walk-in','Self',77,'2026-08-22');
      INSERT INTO counselling_sessions(id,institute_id,branch_id,lead_id,counsellor_user_id,status,mobile_verified,verification_method,started_at,created_at,updated_at)
        VALUES(900,1,10,700,100,'IN_PROGRESS',1,'OTP','2026-08-22','2026-08-22','2026-08-22');
      INSERT INTO counselling_assessments(id,institute_id,counselling_session_id,lead_id,assessment_version,status,started_at,completed_at,created_at,updated_at)
        VALUES(901,1,900,700,'SMART_COUNSELLING_V1','COMPLETED','2026-08-22','2026-08-22','2026-08-22','2026-08-22');
    """)
    answers={"education_status_code":"DEGREE","qualification":"BCOM","stream_code":"COMMERCE","current_situation":"JOB_SEEKER","primary_goal":"GET_JOB","interests":["ACCOUNTING","TALLY"],"computer_skill":"BASIC","accounting_skill":"BASIC","excel_skill":"BASIC","english_skill":"AVERAGE","programming_experience":"NONE","start_timeframe":"IMMEDIATELY","preferred_duration":"MEDIUM","preferred_timing":"MORNING","preferred_learning_mode":"OFFLINE","preferred_language":"ENGLISH"}
    for key,value in answers.items(): conn.execute("INSERT INTO counselling_assessment_answers(assessment_id,question_key,answer_value,created_at,updated_at) VALUES(901,?,?,?,?)",(key,json.dumps(value),'2026-08-22','2026-08-22'))
    conn.commit(); conn.close()
    factory=lambda:connect(database)
    monkeypatch.setattr(course_intelligence,"get_conn",factory); monkeypatch.setattr(recommendation_service,"get_conn",factory)
    admin=app.test_client(); sign_in(admin,101)
    token=admin.get('/test-csrf').get_json()['token']
    for course_id,strength in ((1,'PRIMARY'),(2,'STRONG')):
        payload=complete_payload(goals=[{"code":"GET_JOB","matchStrength":strength,"isPrimary":True}],interests=[{"code":"ACCOUNTING","matchStrength":strength,"isPrimary":True}])
        response=admin.put(f'/api/smart-counselling/course-profiles/{course_id}',json=payload,headers={'X-CSRFToken':token}); assert response.status_code==200,response.get_json()
    return app,database


def csrf(client): return client.get('/test-csrf').get_json()['token']
def generate(client,session_id=900): return client.post(f'/api/smart-counselling/sessions/{session_id}/recommendations',json={},headers={'X-CSRFToken':csrf(client)})


def test_generate_persists_ranked_snapshot_without_touching_crm_lead_score(phase6):
    app,database=phase6; client=app.test_client(); sign_in(client,100)
    response=generate(client); assert response.status_code==201,response.get_json()
    data=response.get_json()['data']; assert data['status']=='MATCHES_FOUND'
    assert [x['courseName'] for x in data['recommendations']]==['DFA','Tally Prime']
    assert data['recommendations'][0]['score'] > data['recommendations'][1]['score']
    conn=connect(database)
    assert conn.execute('SELECT lead_score FROM leads WHERE id=700').fetchone()[0]==77
    assert conn.execute("SELECT COUNT(*) FROM recommendation_runs WHERE status='COMPLETED'").fetchone()[0]==1
    assert conn.execute('SELECT COUNT(*) FROM recommendation_results').fetchone()[0]==2
    assert conn.execute('SELECT COUNT(*) FROM recommendation_results WHERE course_id=3').fetchone()[0]==0
    conn.close()


def test_refresh_loads_latest_and_recalculation_preserves_history(phase6):
    app,database=phase6; client=app.test_client(); sign_in(client,100)
    first=generate(client).get_json()['data']; second=generate(client).get_json()['data']
    assert second['run']['id'] > first['run']['id']
    loaded=client.get('/api/smart-counselling/sessions/900/recommendations').get_json()['data']
    assert loaded['run']['id']==second['run']['id'] and loaded['recommendations']==second['recommendations']
    conn=connect(database); assert conn.execute('SELECT COUNT(*) FROM recommendation_runs').fetchone()[0]==2
    events=[x[0] for x in conn.execute("SELECT event_type FROM counselling_events WHERE counselling_session_id=900")]; conn.close()
    assert 'recommendation_recalculated' in events and events.count('recommendation_completed')==2


def test_incomplete_assessment_and_other_counsellor_are_denied(phase6):
    app,database=phase6; conn=connect(database); conn.execute("UPDATE counselling_assessments SET status='IN_PROGRESS' WHERE id=901"); conn.commit(); conn.close()
    owner=app.test_client(); sign_in(owner,100); response=generate(owner)
    assert response.status_code==409 and response.get_json()['error']['code']=='assessment_incomplete'
    conn=connect(database); conn.execute("UPDATE counselling_assessments SET status='COMPLETED' WHERE id=901"); conn.commit(); conn.close()
    other=app.test_client(); sign_in(other,102); assert generate(other).status_code==403
    assert other.get('/api/smart-counselling/sessions/900/recommendations').status_code==403


def test_atomic_rollback_when_event_persistence_fails(phase6,monkeypatch):
    app,database=phase6; client=app.test_client(); sign_in(client,100)
    monkeypatch.setattr(recommendation_service,'insert_event',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('audit failed')))
    with pytest.raises(RuntimeError): generate(client)
    conn=connect(database); assert conn.execute('SELECT COUNT(*) FROM recommendation_runs').fetchone()[0]==0; assert conn.execute('SELECT COUNT(*) FROM recommendation_results').fetchone()[0]==0; conn.close()


def test_empty_state_before_generation(phase6):
    app,_=phase6; client=app.test_client(); sign_in(client,100)
    data=client.get('/api/smart-counselling/sessions/900/recommendations').get_json()['data']
    assert data['status']=='NOT_GENERATED' and data['run'] is None
