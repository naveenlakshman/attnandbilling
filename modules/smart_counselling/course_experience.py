"""Phase 7 counselling-safe course details, syllabus, comparison, and interest."""

import json
from datetime import datetime

from db import get_conn

from .authorization import authorize_session
from .course_intelligence import _dto
from .errors import SmartCounsellingError, validation_error
from .repository import get_session, insert_event

INTEREST_LEVELS = {"INTERESTED", "HIGHLY_INTERESTED", "NOT_INTERESTED"}


def _now(): return datetime.now().isoformat(timespec="seconds")


def _context(conn, actor, session_id, course_id=None):
    session = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
    run = conn.execute("""SELECT * FROM recommendation_runs WHERE institute_id=? AND counselling_session_id=? AND status='COMPLETED' ORDER BY id DESC LIMIT 1""",(actor.institute_id,session_id)).fetchone()
    if not run:
        raise SmartCounsellingError("recommendations_required","Generate course recommendations first.",409)
    result=None
    if course_id is not None:
        result=conn.execute("""SELECT rr.* FROM recommendation_results rr JOIN courses c ON c.id=rr.course_id AND c.institute_id=rr.institute_id WHERE rr.recommendation_run_id=? AND rr.institute_id=? AND rr.course_id=? LIMIT 1""",(run["id"],actor.institute_id,course_id)).fetchone()
        if not result: raise SmartCounsellingError("not_found","Course is not available in the current recommendation context.",404)
    return session,dict(run),dict(result) if result else None


def _interest_row(conn, actor, session_id, course_id):
    row=conn.execute("""SELECT interest_level,is_primary,updated_at FROM counselling_course_interests WHERE institute_id=? AND counselling_session_id=? AND course_id=?""",(actor.institute_id,session_id,course_id)).fetchone()
    return {"interestLevel":row["interest_level"],"primary":bool(row["is_primary"]),"updatedAt":row["updated_at"]} if row else {"interestLevel":None,"primary":False,"updatedAt":None}


def _snapshot(result):
    matched=json.loads(result.get("matched_factors_json") or "[]"); unmatched=json.loads(result.get("unmatched_factors_json") or "[]")
    return {"runId":int(result["recommendation_run_id"]),"rank":int(result["result_rank"]) if result.get("result_rank") is not None else None,"score":int(result["normalized_score"]) if result.get("normalized_score") is not None else None,"matchLabel":result.get("match_label"),"eligibilityStatus":result["eligibility_status"],"whyRecommended":[x["message"] for x in matched],"considerations":[x["message"] for x in unmatched]}


def _current_course(conn, actor, course_id):
    return _dto(conn,actor,course_id)


def _batches(conn, actor, course_id):
    rows=conn.execute("""SELECT b.id,b.batch_name,b.start_date,b.end_date,b.start_time,b.end_time,b.status,br.branch_name FROM batches b JOIN branches br ON br.id=b.branch_id AND br.institute_id=? WHERE b.course_id=? AND b.status='active' ORDER BY CASE WHEN b.start_date IS NULL THEN 1 ELSE 0 END,b.start_date,b.start_time,b.id""",(actor.institute_id,course_id)).fetchall()
    return [{"id":int(x["id"]),"name":x["batch_name"],"branch":x["branch_name"],"startDate":x["start_date"],"endDate":x["end_date"],"startTime":x["start_time"],"endTime":x["end_time"],"status":x["status"]} for x in rows]


def _program(conn, actor, course_id):
    row=conn.execute("""SELECT lp.id,lp.program_name,m.display_order FROM lms_course_program_map m JOIN lms_programs lp ON lp.id=m.program_id AND lp.institute_id=? WHERE m.course_id=? AND lp.is_active=1 AND lp.is_deleted=0 AND lp.is_published=1 ORDER BY m.display_order,lp.id LIMIT 1""",(actor.institute_id,course_id)).fetchone()
    return dict(row) if row else None


def _syllabus(conn, actor, course_id):
    program=_program(conn,actor,course_id)
    if not program: return {"status":"NOT_AVAILABLE","message":"Syllabus preview is not available for this course yet.","program":None,"chapters":[]}
    master=conn.execute("""SELECT pc.master_chapter_id AS id,COALESCE(NULLIF(pc.custom_title,''),mc.title) AS title,pc.chapter_order FROM lms_program_chapters pc JOIN lms_master_chapters mc ON mc.id=pc.master_chapter_id AND mc.status='active' WHERE pc.program_id=? AND pc.is_visible=1 ORDER BY pc.chapter_order,pc.id""",(program["id"],)).fetchall()
    chapters=[]
    if master:
        for chapter in master:
            topics=conn.execute("""SELECT id,title,topic_order FROM lms_master_topics WHERE master_chapter_id=? AND status='active' ORDER BY topic_order,id""",(chapter["id"],)).fetchall()
            chapters.append({"id":int(chapter["id"]),"title":chapter["title"],"order":int(chapter["chapter_order"] or 0),"topics":[{"id":int(t["id"]),"title":t["title"],"order":int(t["topic_order"] or 0),"estimatedTime":None} for t in topics]})
    else:
        legacy=conn.execute("""SELECT id,chapter_title,chapter_order FROM lms_chapters WHERE program_id=? AND is_active=1 ORDER BY chapter_order,id""",(program["id"],)).fetchall()
        for chapter in legacy:
            topics=conn.execute("""SELECT id,topic_title,topic_order,estimated_minutes FROM lms_topics WHERE chapter_id=? AND is_active=1 ORDER BY topic_order,id""",(chapter["id"],)).fetchall()
            chapters.append({"id":int(chapter["id"]),"title":chapter["chapter_title"],"order":int(chapter["chapter_order"] or 0),"topics":[{"id":int(t["id"]),"title":t["topic_title"],"order":int(t["topic_order"] or 0),"estimatedTime":int(t["estimated_minutes"]) if t["estimated_minutes"] is not None else None} for t in topics]})
    return {"status":"AVAILABLE" if chapters else "NOT_AVAILABLE","message":None if chapters else "Syllabus preview is not available for this course yet.","program":{"id":int(program["id"]),"title":program["program_name"]},"chapters":chapters}


def _detail_dto(conn,actor,session_id,course_id,include_syllabus=True):
    _session,run,result=_context(conn,actor,session_id,course_id); current=_current_course(conn,actor,course_id); core=current["course"]; p=current.get("profile") or {}
    return {"course":{"id":int(core["id"]),"name":core["course_name"],"domain":core.get("course_domain"),"category":core.get("course_category"),"fee":float(core.get("fee") or 0),"duration":core.get("duration"),"hours":core.get("duration_hours"),"active":bool(core.get("is_active")),"availability":"AVAILABLE" if core.get("is_active") else "CURRENTLY_UNAVAILABLE"},"recommendation":_snapshot(result),"intelligence":{"purpose":p.get("course_purpose"),"shortDescription":p.get("short_description"),"detailedDescription":p.get("detailed_description"),"targetAudience":p.get("target_audience"),"minimumEducation":p.get("minimum_education_level"),"preferredBackground":p.get("preferred_background"),"hardEligibility":p.get("hard_eligibility_text"),"startingSkillLevel":p.get("starting_skill_level"),"certification":{"title":p.get("certification_title"),"issuingBody":p.get("certification_issuing_body"),"included":bool(p.get("certification_included")),"externalExamRequired":bool(p.get("external_exam_required")),"details":p.get("certification_details")},"prerequisites":current["prerequisites"],"skillsTaught":[x["skill_code"] for x in current["skillsTaught"]],"learningOutcomes":current["learningOutcomes"],"careerOutcomes":current["careerOutcomes"],"jobRoles":current["jobRoles"]},"syllabus":_syllabus(conn,actor,course_id) if include_syllabus else {"status":"AVAILABLE" if _program(conn,actor,course_id) else "NOT_AVAILABLE"},"batches":_batches(conn,actor,course_id),"interest":_interest_row(conn,actor,session_id,course_id)}


def get_course_details(actor,session_id,course_id):
    conn=get_conn(); now=_now()
    try:
        data=_detail_dto(conn,actor,session_id,course_id)
        session=get_session(conn,actor.institute_id,session_id); insert_event(conn,institute_id=actor.institute_id,session_id=session_id,lead_id=session["lead_id"],actor_user_id=actor.id,event_type="course_detail_viewed",metadata={"courseId":course_id,"runId":data["recommendation"]["runId"]},now=now); conn.commit(); return data
    finally: conn.close()


def get_course_syllabus(actor,session_id,course_id):
    conn=get_conn(); now=_now()
    try:
        session,run,_result=_context(conn,actor,session_id,course_id); data=_syllabus(conn,actor,course_id)
        insert_event(conn,institute_id=actor.institute_id,session_id=session_id,lead_id=session["lead_id"],actor_user_id=actor.id,event_type="syllabus_viewed",metadata={"courseId":course_id,"runId":run["id"],"status":data["status"]},now=now); conn.commit(); return data
    finally: conn.close()


def compare_courses(actor,session_id,course_ids):
    if len(course_ids) not in {2,3} or len(set(course_ids))!=len(course_ids): raise validation_error("Choose two or three different recommended courses.",{"course_ids":"Two or three unique course IDs are required."})
    conn=get_conn(); now=_now()
    try:
        session,run,_=_context(conn,actor,session_id); items=[_detail_dto(conn,actor,session_id,x,False) for x in course_ids]
        insert_event(conn,institute_id=actor.institute_id,session_id=session_id,lead_id=session["lead_id"],actor_user_id=actor.id,event_type="comparison_opened",metadata={"courseIds":course_ids,"runId":run["id"]},now=now); conn.commit(); return {"runId":int(run["id"]),"courses":items}
    finally: conn.close()


def list_course_interests(actor,session_id):
    conn=get_conn()
    try:
        _session,run,_=_context(conn,actor,session_id); rows=conn.execute("""SELECT course_id,interest_level,is_primary,updated_at FROM counselling_course_interests WHERE institute_id=? AND counselling_session_id=? AND recommendation_run_id=? ORDER BY course_id""",(actor.institute_id,session_id,run["id"])).fetchall()
        return {"runId":int(run["id"]),"interests":[{"courseId":int(x["course_id"]),"interestLevel":x["interest_level"],"primary":bool(x["is_primary"]),"updatedAt":x["updated_at"]} for x in rows]}
    finally: conn.close()


def set_course_interest(actor,session_id,course_id,payload):
    level=str(payload.get("interestLevel") or "").strip().upper(); primary=bool(payload.get("primary"))
    if level not in INTEREST_LEVELS: raise validation_error("Choose a valid interest level.",{"interestLevel":"Invalid code."})
    if primary and level=="NOT_INTERESTED": raise validation_error("A course marked not interested cannot be the primary choice.",{"primary":"Choose an interested course."})
    conn=get_conn(); now=_now()
    try:
        session,run,_result=_context(conn,actor,session_id,course_id)
        if session["status"] in {"COMPLETED","ABANDONED"}: raise SmartCounsellingError("session_completed","A completed counselling session cannot be changed.",409)
        conn.execute("UPDATE counselling_sessions SET updated_at=updated_at WHERE id=? AND institute_id=?",(session_id,actor.institute_id))
        existing=conn.execute("SELECT id,interest_level,is_primary FROM counselling_course_interests WHERE institute_id=? AND counselling_session_id=? AND course_id=?",(actor.institute_id,session_id,course_id)).fetchone()
        old_primary=conn.execute("SELECT course_id FROM counselling_course_interests WHERE institute_id=? AND counselling_session_id=? AND is_primary=1",(actor.institute_id,session_id)).fetchone()
        if primary: conn.execute("UPDATE counselling_course_interests SET is_primary=0,updated_by_user_id=?,updated_at=? WHERE institute_id=? AND counselling_session_id=? AND is_primary=1",(actor.id,now,actor.institute_id,session_id))
        if existing:
            conn.execute("UPDATE counselling_course_interests SET recommendation_run_id=?,interest_level=?,is_primary=?,updated_by_user_id=?,updated_at=? WHERE id=? AND institute_id=?",(run["id"],level,int(primary),actor.id,now,existing["id"],actor.institute_id)); event="course_interest_changed" if existing["interest_level"]!=level or bool(existing["is_primary"])!=primary else "course_interest_set"
        else:
            conn.execute("""INSERT INTO counselling_course_interests(institute_id,counselling_session_id,lead_id,recommendation_run_id,course_id,interest_level,is_primary,created_by_user_id,updated_by_user_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(actor.institute_id,session_id,session["lead_id"],run["id"],course_id,level,int(primary),actor.id,actor.id,now,now)); event="course_interest_set"
        insert_event(conn,institute_id=actor.institute_id,session_id=session_id,lead_id=session["lead_id"],actor_user_id=actor.id,event_type=event,metadata={"courseId":course_id,"interestLevel":level,"primary":primary,"runId":run["id"]},now=now)
        if primary and (not old_primary or int(old_primary["course_id"])!=course_id): insert_event(conn,institute_id=actor.institute_id,session_id=session_id,lead_id=session["lead_id"],actor_user_id=actor.id,event_type="primary_course_interest_changed",metadata={"fromCourseId":int(old_primary["course_id"]) if old_primary else None,"toCourseId":course_id,"runId":run["id"]},now=now)
        conn.commit(); return {"courseId":course_id,"interestLevel":level,"primary":primary,"updatedAt":now}
    except Exception: conn.rollback(); raise
    finally: conn.close()
