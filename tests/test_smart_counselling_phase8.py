from datetime import date, timedelta

import pytest

from modules.smart_counselling import outcome_service
from test_smart_counselling_phase2 import phase2
from test_smart_counselling_phase3 import phase3, sign_in
from test_smart_counselling_phase4 import connect, phase4
from test_smart_counselling_phase6_api import generate, phase6
from test_smart_counselling_phase7 import phase7, interest


@pytest.fixture()
def phase8(phase7, monkeypatch):
    app, database = phase7
    conn = connect(database)
    for sql in (
        "ALTER TABLE leads ADD COLUMN last_contact_date TEXT",
        "ALTER TABLE leads ADD COLUMN next_followup_date TEXT",
        "ALTER TABLE leads ADD COLUMN followup_count INTEGER DEFAULT 0",
        "ALTER TABLE leads ADD COLUMN parent_discussion_status TEXT DEFAULT 'Pending'",
        "ALTER TABLE leads ADD COLUMN lost_reason TEXT",
        "ALTER TABLE leads ADD COLUMN conversion_date TEXT",
    ): conn.execute(sql)
    conn.execute("""CREATE TABLE followups(id INTEGER PRIMARY KEY AUTOINCREMENT,institute_id INTEGER NOT NULL,lead_id INTEGER NOT NULL,user_id INTEGER,method TEXT,outcome TEXT,note TEXT,next_followup_date TEXT,created_at TEXT)""")
    conn.commit(); conn.close()
    monkeypatch.setattr(outcome_service, "get_conn", lambda: connect(database))
    return app, database


def csrf(client): return client.get('/test-csrf').get_json()['token']
def owner(app):
    client = app.test_client(); sign_in(client, 100); assert generate(client).status_code == 201; return client
def future(days=2): return (date.today() + timedelta(days=days)).isoformat()
def complete(client, payload): return client.post('/api/smart-counselling/sessions/900/complete', json=payload, headers={'X-CSRFToken': csrf(client)})


def test_ready_for_admission_completes_without_creating_student_or_followup(phase8):
    app, database = phase8; client = owner(app); assert interest(client, 2, 'HIGHLY_INTERESTED', True).status_code == 200
    response = complete(client, {'outcome':'READY_FOR_ADMISSION','nextAction':'PROCEED_TO_ADMISSION'})
    assert response.status_code == 200
    data = response.get_json()['data']; assert data['status'] == 'COMPLETED' and data['primaryInterest']['courseId'] == 2 and data['admissionHandoffAvailable'] is True
    conn=connect(database); assert conn.execute('SELECT COUNT(*) FROM followups').fetchone()[0] == 0; assert conn.execute('SELECT COUNT(*) FROM students').fetchone()[0] == 0; assert conn.execute('SELECT lead_score FROM leads WHERE id=700').fetchone()[0] == 77; conn.close()


def test_parent_discussion_requires_date_creates_existing_crm_followup_and_updates_status(phase8):
    app,database=phase8; client=owner(app)
    assert complete(client,{'outcome':'PARENT_DISCUSSION_REQUIRED','nextAction':'PARENT_DISCUSSION_FOLLOWUP'}).status_code == 400
    response=complete(client,{'outcome':'PARENT_DISCUSSION_REQUIRED','nextAction':'PARENT_DISCUSSION_FOLLOWUP','nextFollowupDate':future(),'staffNotes':'Discuss after parent call.'})
    assert response.status_code==200
    conn=connect(database); followup=conn.execute('SELECT * FROM followups').fetchone(); lead=conn.execute('SELECT * FROM leads WHERE id=700').fetchone(); conn.close()
    assert followup['institute_id']==1 and followup['method']=='Smart Counselling' and lead['parent_discussion_status']=='Scheduled' and lead['stage']=='Follow-up' and lead['followup_count']==1


def test_fee_concern_requires_reason_primary_and_followup(phase8):
    app,_=phase8; client=owner(app)
    assert complete(client,{'outcome':'FEE_CONCERN','nextAction':'FEE_DISCUSSION','nextFollowupDate':future()}).status_code==400
    interest(client,1,'INTERESTED',True)
    assert complete(client,{'outcome':'FEE_CONCERN','outcomeReason':'NEEDS_INSTALLMENT','nextAction':'FEE_DISCUSSION','nextFollowupDate':future(),'staffNotes':'Needs installments.'}).status_code==200


@pytest.mark.parametrize('outcome,reason', [('NOT_INTERESTED','COURSE_NOT_RELEVANT'),('NO_SUITABLE_COURSE',None)])
def test_non_buying_outcomes_complete_without_primary_followup_or_lost_transition(phase8,outcome,reason):
    app,database=phase8; client=owner(app); payload={'outcome':outcome,'nextAction':'NO_FURTHER_ACTION'}
    if reason: payload['outcomeReason']=reason
    assert complete(client,payload).status_code==200
    conn=connect(database); lead=conn.execute('SELECT status,lost_reason FROM leads WHERE id=700').fetchone(); assert lead['status']=='active' and lead['lost_reason'] is None; assert conn.execute('SELECT COUNT(*) FROM followups').fetchone()[0]==0; conn.close()


def test_completion_is_idempotent_and_completed_interest_is_immutable(phase8):
    app,database=phase8;client=owner(app);interest(client,1,'INTERESTED',True);payload={'outcome':'PARENT_DISCUSSION_REQUIRED','nextAction':'CALL_BACK','nextFollowupDate':future()}
    first=complete(client,payload); second=complete(client,payload); assert first.status_code==second.status_code==200 and first.get_json()['data']['completedAt']==second.get_json()['data']['completedAt']
    assert interest(client,2).status_code==409
    assert generate(client).status_code==409
    conn=connect(database); assert conn.execute('SELECT COUNT(*) FROM followups').fetchone()[0]==1; assert conn.execute("SELECT COUNT(*) FROM counselling_events WHERE event_type='counselling_completed'").fetchone()[0]==1; conn.close()


def test_converted_race_returns_existing_student_and_disables_handoff(phase8):
    app,database=phase8;client=owner(app);interest(client,1,'HIGHLY_INTERESTED',True);conn=connect(database);conn.execute("INSERT INTO students(id,institute_id,lead_id,student_code,full_name,phone) VALUES(88,1,700,'S88','Golden Prospect','9876543210')");conn.execute("UPDATE leads SET status='converted',stage='Converted' WHERE id=700");conn.commit();conn.close()
    data=complete(client,{'outcome':'READY_FOR_ADMISSION','nextAction':'PROCEED_TO_ADMISSION'}).get_json()['data']
    assert data['admissionHandoffAvailable'] is False and data['student']['id']==88
    handoff=client.post('/api/smart-counselling/sessions/900/admission-handoff',json={},headers={'X-CSRFToken':csrf(client)}).get_json()['data'];assert handoff['alreadyRegistered'] is True


def test_draft_policy_summary_authorization_csrf_and_past_date_validation(phase8):
    app,_=phase8;client=owner(app)
    data=client.get('/api/smart-counselling/sessions/900/outcome').get_json()['data']; assert len(data['policies'])==10 and data['summary']['prospect']['name']=='Golden Prospect'
    assert client.put('/api/smart-counselling/sessions/900/outcome',json={'outcome':'NOT_READY'}).status_code==400
    saved=client.put('/api/smart-counselling/sessions/900/outcome',json={'outcome':'NOT_READY','nextAction':'CALL_BACK'},headers={'X-CSRFToken':csrf(client)}); assert saved.status_code==200
    assert complete(client,{'outcome':'NOT_READY','nextAction':'CALL_BACK','nextFollowupDate':'2020-01-01'}).status_code==400
    other=app.test_client();sign_in(other,102);assert other.get('/api/smart-counselling/sessions/900/outcome').status_code==403
