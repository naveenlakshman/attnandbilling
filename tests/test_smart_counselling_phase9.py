import json

import pytest

from modules.smart_counselling import analytics_service, insights_service
from modules.smart_counselling.insights_service import get_latest_counselling_insight
from test_smart_counselling_phase2 import phase2
from test_smart_counselling_phase3 import phase3, sign_in
from test_smart_counselling_phase4 import connect, phase4
from test_smart_counselling_phase6_api import generate, phase6
from test_smart_counselling_phase7 import interest, phase7
from test_smart_counselling_phase8 import complete, phase8


@pytest.fixture()
def phase9(phase8, monkeypatch):
    app,database=phase8; factory=lambda:connect(database)
    monkeypatch.setattr(insights_service,'get_conn',factory);monkeypatch.setattr(analytics_service,'get_conn',factory)
    return app,database


def owner(app): client=app.test_client();sign_in(client,100);return client


def test_latest_insight_keeps_top_recommendation_and_primary_choice_distinct(phase9):
    app,database=phase9;client=owner(app);generate(client);interest(client,2,'HIGHLY_INTERESTED',True);complete(client,{'outcome':'READY_FOR_ADMISSION','nextAction':'PROCEED_TO_ADMISSION'})
    conn=connect(database);data=get_latest_counselling_insight(conn,1,700);conn.close()
    assert data['topRecommendation']['courseId']==1 and data['primaryInterest']['courseId']==2
    assert data['topRecommendation']['score']!=None and data['sessionCount']==1 and data['outcome']=='READY_FOR_ADMISSION'


def test_history_is_chronological_safe_and_preserves_multiple_persisted_runs(phase9):
    app,database=phase9;client=owner(app);first=generate(client).get_json()['data']['run']['id'];conn=connect(database);conn.execute('UPDATE recommendation_results SET normalized_score=61 WHERE recommendation_run_id=? AND course_id=1',(first,));conn.commit();conn.close();second=generate(client).get_json()['data']['run']['id'];interest(client,2,'INTERESTED',True)
    conn=connect(database);conn.execute("INSERT INTO counselling_sessions(id,institute_id,branch_id,lead_id,counsellor_user_id,status,mobile_verified,verification_method,started_at,created_at,updated_at) VALUES(901,1,10,700,100,'ABANDONED',1,'OTP','2026-08-23','2026-08-23','2026-08-23')");conn.commit();conn.close()
    data=client.get('/api/smart-counselling/leads/700/history').get_json()['data']
    assert [x['id'] for x in data['sessions']]==[901,900] and data['sessions'][0]['status']=='ABANDONED'
    old=next(x for x in data['sessions'][1]['recommendationRuns'] if x['id']==first);assert old['recommendations'][0]['score']==61
    assert len(data['sessions'][1]['recommendationRuns'])==2 and data['sessions'][1]['primaryInterest']['courseId']==2
    raw=json.dumps(data).lower();assert 'otp_hash' not in raw and 'mobile_normalized' not in raw and 'metadata_json' not in raw


def test_history_uses_persisted_course_name_snapshot(phase9):
    app,database=phase9;client=owner(app);generate(client)
    conn=connect(database);snapshot=conn.execute("SELECT course_name_snapshot FROM recommendation_results WHERE recommendation_run_id=(SELECT MAX(id) FROM recommendation_runs) AND result_rank=1").fetchone()[0];conn.execute("UPDATE courses SET course_name='Renamed after counselling' WHERE id=1");conn.commit();conn.close()
    data=client.get('/api/smart-counselling/leads/700/history').get_json()['data']
    assert data['sessions'][0]['recommendationRuns'][0]['recommendations'][0]['courseName']==snapshot


def test_history_authorization_and_empty_cross_tenant_behavior(phase9):
    app,_=phase9;client=owner(app);generate(client)
    other=app.test_client();sign_in(other,102);assert other.get('/api/smart-counselling/leads/700/history').status_code==403
    foreign=app.test_client();sign_in(foreign,200,2);assert foreign.get('/api/smart-counselling/leads/700/history').status_code==404


def test_analytics_funnel_unique_lead_conversion_and_course_choice_difference(phase9):
    app,database=phase9;client=owner(app);generate(client);interest(client,2,'HIGHLY_INTERESTED',True);complete(client,{'outcome':'READY_FOR_ADMISSION','nextAction':'PROCEED_TO_ADMISSION'})
    conn=connect(database);conn.execute("INSERT INTO counselling_sessions(id,institute_id,branch_id,lead_id,counsellor_user_id,status,mobile_verified,verification_method,started_at,created_at,updated_at) VALUES(901,1,10,700,100,'IN_PROGRESS',1,'OTP','2026-08-22','2026-08-22','2026-08-22'),(902,1,10,700,100,'ABANDONED',1,'OTP','2026-08-22','2026-08-22','2026-08-22')");conn.execute("INSERT INTO students(id,institute_id,lead_id,student_code,full_name,phone) VALUES(88,1,700,'S88','Golden Prospect','9876543210')");conn.commit();conn.close()
    data=client.get('/api/smart-counselling/analytics?date_from=2026-08-22&date_to=2026-08-22').get_json()['data']
    assert data['overview']['sessions']==3 and data['overview']['uniqueProspects']==1 and data['overview']['convertedLeads']==1
    assert next(x for x in data['funnel'] if x['code']=='STARTED')['count']==3 and next(x for x in data['funnel'] if x['code']=='CONVERTED')['count']==1
    assert data['courses']['recommended'][0]['courseId']==1 and data['courses']['primarySelected'][0]['courseId']==2 and data['courses']['alignment']['differentChoice']==1


def test_analytics_outcome_filters_staff_scope_and_no_suitable_dimensions(phase9):
    app,database=phase9;client=owner(app);generate(client);complete(client,{'outcome':'NO_SUITABLE_COURSE','nextAction':'NO_FURTHER_ACTION'})
    data=client.get('/api/smart-counselling/analytics?date_from=2026-08-22&date_to=2026-08-22&branch_id=10&counsellor_id=100').get_json()['data']
    assert data['outcomes']==[{'code':'NO_SUITABLE_COURSE','count':1}] and data['noSuitableCourse']['count']==1
    assert any(x['dimension']=='qualification' and x['value']=='BCOM' for x in data['noSuitableCourse']['dimensions'])
    assert client.get('/api/smart-counselling/analytics?date_from=bad').status_code==400
    other=app.test_client();sign_in(other,102);assert other.get('/api/smart-counselling/analytics?counsellor_id=100').status_code==403
