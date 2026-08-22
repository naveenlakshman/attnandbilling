import pytest

from modules.smart_counselling import course_experience
from test_smart_counselling_phase2 import phase2
from test_smart_counselling_phase3 import phase3,sign_in
from test_smart_counselling_phase4 import phase4,connect
from test_smart_counselling_phase6_api import phase6,generate


@pytest.fixture()
def phase7(phase6,monkeypatch):
    app,database=phase6; conn=connect(database)
    for sql in ("ALTER TABLE lms_programs ADD COLUMN institute_id INTEGER","ALTER TABLE lms_programs ADD COLUMN is_active INTEGER DEFAULT 1","ALTER TABLE lms_programs ADD COLUMN is_deleted INTEGER DEFAULT 0","ALTER TABLE lms_programs ADD COLUMN is_published INTEGER DEFAULT 1","ALTER TABLE batches ADD COLUMN batch_name TEXT","ALTER TABLE batches ADD COLUMN start_date TEXT","ALTER TABLE batches ADD COLUMN end_date TEXT","ALTER TABLE batches ADD COLUMN start_time TEXT","ALTER TABLE batches ADD COLUMN end_time TEXT"):
        conn.execute(sql)
    conn.executescript("""
      CREATE TABLE lms_master_chapters(id INTEGER PRIMARY KEY,title TEXT,description TEXT,status TEXT,created_by INTEGER,created_at TEXT,updated_at TEXT);
      CREATE TABLE lms_master_topics(id INTEGER PRIMARY KEY,master_chapter_id INTEGER,title TEXT,short_description TEXT,topic_order INTEGER,status TEXT,created_at TEXT,updated_at TEXT);
      CREATE TABLE lms_program_chapters(id INTEGER PRIMARY KEY,program_id INTEGER,master_chapter_id INTEGER,chapter_order INTEGER,custom_title TEXT,is_visible INTEGER,created_at TEXT);
      CREATE TABLE lms_chapters(id INTEGER PRIMARY KEY,program_id INTEGER,chapter_title TEXT,chapter_order INTEGER,description TEXT,is_active INTEGER,created_at TEXT,updated_at TEXT);
      CREATE TABLE lms_topics(id INTEGER PRIMARY KEY,chapter_id INTEGER,topic_title TEXT,topic_order INTEGER,short_description TEXT,estimated_minutes INTEGER,content_type TEXT,is_preview INTEGER,is_active INTEGER,is_required INTEGER,created_at TEXT,updated_at TEXT);
      UPDATE batches SET batch_name='Morning Batch',start_date='2026-09-01',start_time='09:00',end_time='11:00' WHERE id IS NULL;
      INSERT INTO batches(id,course_id,branch_id,status,batch_name,start_date,start_time,end_time) VALUES(50,1,10,'active','September Morning','2026-09-01','09:00','11:00');
      INSERT INTO lms_programs(id,program_name,created_by,course_id,institute_id,is_active,is_deleted,is_published) VALUES(10,'DFA Current Syllabus',101,1,1,1,0,1),(11,'Secondary Program',101,1,1,1,0,1),(20,'Foreign Program',200,2,2,1,0,1);
      INSERT INTO lms_course_program_map(id,course_id,program_id,display_order) VALUES(10,1,11,2),(11,1,10,1),(20,1,20,0);
      INSERT INTO lms_master_chapters VALUES(100,'Accounting Fundamentals','private chapter description','active',101,'2026-08-22',NULL),(101,'GST','private','active',101,'2026-08-22',NULL);
      INSERT INTO lms_program_chapters VALUES(1,10,101,2,NULL,1,'2026-08-22'),(2,10,100,1,NULL,1,'2026-08-22');
      INSERT INTO lms_master_topics VALUES(1000,100,'Introduction to Accounting','private topic description',2,'active','2026-08-22',NULL),(1001,100,'Types of Accounts','private',1,'active','2026-08-22',NULL),(1002,101,'GST Basics','private',1,'active','2026-08-22',NULL);
    """)
    conn.commit();conn.close();monkeypatch.setattr(course_experience,'get_conn',lambda:connect(database));return app,database


def csrf(client):return client.get('/test-csrf').get_json()['token']
def interest(client,course_id,level='INTERESTED',primary=False):return client.put(f'/api/smart-counselling/sessions/900/course-interests/{course_id}',json={'interestLevel':level,'primary':primary},headers={'X-CSRFToken':csrf(client)})
def ready_client(app):
    client=app.test_client();sign_in(client,100);assert generate(client).status_code==201;return client


def test_course_details_preserve_snapshot_but_use_current_fee_batches_and_inactive_status(phase7):
    app,database=phase7;client=ready_client(app);conn=connect(database);conn.execute("UPDATE courses SET fee=19999,is_active=0 WHERE id=1");conn.execute("UPDATE recommendation_results SET matched_factors_json='[{\"code\":\"snapshot\",\"message\":\"Historical explanation.\"}]' WHERE course_id=1");conn.commit();conn.close()
    data=client.get('/api/smart-counselling/sessions/900/courses/1').get_json()['data']
    assert data['course']['fee']==19999 and data['course']['availability']=='CURRENTLY_UNAVAILABLE'
    assert data['recommendation']['whyRecommended']==['Historical explanation.'] and data['batches'][0]['name']=='September Morning'


def test_syllabus_uses_first_ordered_same_tenant_program_and_leaks_no_private_content(phase7):
    app,_=phase7;client=ready_client(app);data=client.get('/api/smart-counselling/sessions/900/courses/1/syllabus').get_json()['data']
    assert data['program']=={'id':10,'title':'DFA Current Syllabus'}
    assert [x['title'] for x in data['chapters']]==['Accounting Fundamentals','GST']
    assert [x['title'] for x in data['chapters'][0]['topics']]==['Types of Accounts','Introduction to Accounting']
    raw=str(data).lower();assert 'description' not in raw and 'content' not in raw and 'student' not in raw and 'trainer' not in raw


def test_missing_mapping_is_graceful_and_missing_current_profile_does_not_erase_snapshot(phase7):
    app,database=phase7;client=ready_client(app);conn=connect(database);conn.execute('DELETE FROM course_profiles WHERE course_id=2');conn.commit();conn.close()
    detail=client.get('/api/smart-counselling/sessions/900/courses/2').get_json()['data']
    assert detail['recommendation']['score'] is not None and detail['intelligence']['purpose'] is None
    assert detail['syllabus']['status']=='NOT_AVAILABLE'


@pytest.mark.parametrize('ids,status', [('1,2',200),('1,2,1',400),('1',400),('1,2,3,4',400),('1,99',404)])
def test_comparison_validates_context_cardinality_and_duplicates(phase7,ids,status):
    app,_=phase7;client=ready_client(app);response=client.get('/api/smart-counselling/sessions/900/compare?course_ids='+ids);assert response.status_code==status
    if status==200:
        data=response.get_json()['data'];assert [x['course']['id'] for x in data['courses']]==[1,2];assert all(x['recommendation']['score'] is not None for x in data['courses'])


def test_interest_levels_idempotency_primary_switch_refresh_and_score_immutability(phase7):
    app,database=phase7;client=ready_client(app)
    assert interest(client,1,'INTERESTED',True).status_code==200
    assert interest(client,1,'HIGHLY_INTERESTED',True).status_code==200
    assert interest(client,2,'INTERESTED',True).status_code==200
    data=client.get('/api/smart-counselling/sessions/900/course-interests').get_json()['data']['interests']
    assert len(data)==2 and next(x for x in data if x['courseId']==1)['primary'] is False and next(x for x in data if x['courseId']==2)['primary'] is True
    before=client.get('/api/smart-counselling/sessions/900/recommendations').get_json()['data']['recommendations']
    assert interest(client,1,'NOT_INTERESTED').status_code==200
    after=client.get('/api/smart-counselling/sessions/900/recommendations').get_json()['data']['recommendations'];assert [(x['courseId'],x['score']) for x in before]==[(x['courseId'],x['score']) for x in after]
    conn=connect(database);assert conn.execute('SELECT COUNT(*) FROM counselling_course_interests WHERE counselling_session_id=900 AND course_id=1').fetchone()[0]==1;assert conn.execute('SELECT COUNT(*) FROM counselling_course_interests WHERE is_primary=1').fetchone()[0]==1;conn.close()


def test_interest_validation_authorization_context_csrf_and_atomic_event_rollback(phase7,monkeypatch):
    app,database=phase7;client=ready_client(app)
    assert interest(client,1,'INVALID').status_code==400 and interest(client,1,'NOT_INTERESTED',True).status_code==400
    assert interest(client,99).status_code==404
    assert client.put('/api/smart-counselling/sessions/900/course-interests/1',json={'interestLevel':'INTERESTED'}).status_code==400
    other=app.test_client();sign_in(other,102);assert interest(other,1).status_code==403
    monkeypatch.setattr(course_experience,'insert_event',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('audit failed')))
    with pytest.raises(RuntimeError):interest(client,1)
    conn=connect(database);assert conn.execute('SELECT COUNT(*) FROM counselling_course_interests').fetchone()[0]==0;conn.close()
