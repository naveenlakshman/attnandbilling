"""Phase 9 latest lead insight and immutable counselling history services."""

import json

from db import get_conn
from modules.leads.helpers import can_access_lead

from .errors import SmartCounsellingError


USEFUL_EVENTS = {
    "course_detail_viewed": "Course viewed", "syllabus_viewed": "Syllabus viewed",
    "comparison_opened": "Courses compared", "course_interest_changed": "Course interest changed",
    "primary_course_interest_changed": "Primary course changed", "recommendation_recalculated": "Recommendation recalculated",
}


def _json(value, fallback=None):
    try: return json.loads(value) if value is not None else fallback
    except (TypeError, json.JSONDecodeError): return fallback


def _answer_value(value):
    parsed = _json(value, value)
    return parsed


def _authorized_lead(conn, actor, lead_id):
    row = conn.execute("SELECT * FROM leads WHERE id=? AND institute_id=? AND is_deleted=0", (lead_id, actor.institute_id)).fetchone()
    if not row: raise SmartCounsellingError("not_found", "Lead was not found.", 404)
    lead = dict(row)
    if not actor.can_view_all_branches and int(lead.get("branch_id") or 0) != int(actor.branch_id or 0):
        raise SmartCounsellingError("forbidden", "You do not have access to this lead's branch.", 403)
    if not can_access_lead(actor.id, actor.role, lead.get("assigned_to_id")):
        raise SmartCounsellingError("forbidden", "You do not have access to this lead.", 403)
    return lead


def get_latest_counselling_insight(conn, institute_id, lead_id):
    """Focused CRM-card query; never constructs or preloads full history."""
    count = conn.execute("SELECT COUNT(*) AS n FROM counselling_sessions WHERE institute_id=? AND lead_id=?", (institute_id, lead_id)).fetchone()["n"]
    session = conn.execute("""SELECT cs.*,u.full_name AS counsellor_name FROM counselling_sessions cs
      JOIN users u ON u.id=cs.counsellor_user_id AND u.institute_id=cs.institute_id
      WHERE cs.institute_id=? AND cs.lead_id=? ORDER BY COALESCE(cs.completed_at,cs.updated_at) DESC,cs.id DESC LIMIT 1""", (institute_id, lead_id)).fetchone()
    if not session: return None
    s = dict(session)
    assessment = conn.execute("SELECT id,status FROM counselling_assessments WHERE institute_id=? AND counselling_session_id=?", (institute_id, s["id"])).fetchone()
    answers = {}
    if assessment:
        for row in conn.execute("SELECT question_key,answer_value FROM counselling_assessment_answers WHERE assessment_id=? AND question_key IN ('qualification','current_situation','primary_goal')", (assessment["id"],)).fetchall(): answers[row["question_key"]] = _answer_value(row["answer_value"])
    run = conn.execute("SELECT id FROM recommendation_runs WHERE institute_id=? AND counselling_session_id=? AND status='COMPLETED' ORDER BY id DESC LIMIT 1", (institute_id, s["id"])).fetchone()
    top = None; primary = None
    if run:
        top_row = conn.execute("""SELECT rr.course_id,rr.normalized_score,rr.match_label,rr.course_name_snapshot FROM recommendation_results rr
          WHERE rr.institute_id=? AND rr.recommendation_run_id=? ORDER BY rr.result_rank LIMIT 1""", (institute_id, run["id"])).fetchone()
        if top_row: top = {"courseId": int(top_row["course_id"]), "courseName": top_row["course_name_snapshot"] or f"Course #{top_row['course_id']}", "score": int(top_row["normalized_score"]), "matchLabel": top_row["match_label"]}
        p = conn.execute("""SELECT i.course_id,i.interest_level,c.course_name FROM counselling_course_interests i LEFT JOIN courses c ON c.id=i.course_id AND c.institute_id=i.institute_id
          WHERE i.institute_id=? AND i.counselling_session_id=? AND i.is_primary=1 ORDER BY i.updated_at DESC LIMIT 1""", (institute_id, s["id"])).fetchone()
        if p: primary = {"courseId": int(p["course_id"]), "courseName": p["course_name"] or f"Course #{p['course_id']}", "interestLevel": p["interest_level"]}
    return {"sessionId": int(s["id"]), "status": s["status"], "lastCounsellingDate": s.get("completed_at") or s.get("updated_at"), "counsellor": s["counsellor_name"],
      "verificationStatus": "VERIFIED" if s.get("mobile_verified") else "OVERRIDDEN" if s.get("verification_method") == "OVERRIDE" else "NOT_VERIFIED",
      "qualification": answers.get("qualification"), "currentSituation": answers.get("current_situation"), "primaryGoal": answers.get("primary_goal"),
      "topRecommendation": top, "primaryInterest": primary, "outcome": s.get("outcome"), "nextAction": s.get("next_action"), "nextFollowupDate": s.get("next_followup_date"),
      "sessionCount": int(count), "historyUrl": f"/smart-counselling/history/{lead_id}"}


def get_lead_history(actor, lead_id):
    conn = get_conn()
    try:
        lead = _authorized_lead(conn, actor, lead_id)
        sessions = [dict(x) for x in conn.execute("""SELECT cs.*,u.full_name AS counsellor_name,b.branch_name FROM counselling_sessions cs
          JOIN users u ON u.id=cs.counsellor_user_id AND u.institute_id=cs.institute_id JOIN branches b ON b.id=cs.branch_id AND b.institute_id=cs.institute_id
          WHERE cs.institute_id=? AND cs.lead_id=? ORDER BY cs.started_at DESC,cs.id DESC""", (actor.institute_id, lead_id)).fetchall()]
        student = conn.execute("SELECT id,student_code,full_name FROM students WHERE institute_id=? AND lead_id=? ORDER BY id LIMIT 1", (actor.institute_id, lead_id)).fetchone()
        if not sessions:
            return {"lead":{"id":int(lead["id"]),"name":lead["name"],"stage":lead.get("stage"),"status":lead.get("status")},"currentCrm":{"ownerId":lead.get("assigned_to_id"),"stage":lead.get("stage"),"nextFollowupDate":lead.get("next_followup_date"),"student":dict(student) if student else None},"sessions":[]}
        ids = [int(x["id"]) for x in sessions]; marks = ",".join("?" for _ in ids)
        assessments = [dict(x) for x in conn.execute(f"SELECT * FROM counselling_assessments WHERE institute_id=? AND counselling_session_id IN ({marks})", (actor.institute_id,*ids)).fetchall()]
        assessment_by_session = {int(x["counselling_session_id"]): x for x in assessments}; assessment_ids=[int(x["id"]) for x in assessments]
        answers_by_assessment = {}
        if assessment_ids:
            amarks=",".join("?" for _ in assessment_ids)
            for row in conn.execute(f"SELECT assessment_id,question_key,answer_value FROM counselling_assessment_answers WHERE assessment_id IN ({amarks})", tuple(assessment_ids)).fetchall(): answers_by_assessment.setdefault(int(row["assessment_id"]),{})[row["question_key"]]=_answer_value(row["answer_value"])
        runs=[dict(x) for x in conn.execute(f"SELECT * FROM recommendation_runs WHERE institute_id=? AND counselling_session_id IN ({marks}) AND status='COMPLETED' ORDER BY counselling_session_id,id DESC",(actor.institute_id,*ids)).fetchall()]
        run_ids=[int(x["id"]) for x in runs]; results_by_run={}
        if run_ids:
            rmarks=",".join("?" for _ in run_ids)
            rows=conn.execute(f"""SELECT rr.* FROM recommendation_results rr WHERE rr.institute_id=? AND rr.recommendation_run_id IN ({rmarks}) ORDER BY rr.recommendation_run_id,rr.result_rank""",(actor.institute_id,*run_ids)).fetchall()
            for x in rows:
                matched=_json(x["matched_factors_json"],[]) or []; unmatched=_json(x["unmatched_factors_json"],[]) or []
                results_by_run.setdefault(int(x["recommendation_run_id"]),[]).append({"courseId":int(x["course_id"]),"courseName":x["course_name_snapshot"] or f"Course #{x['course_id']}","rank":x["result_rank"],"score":int(x["normalized_score"]),"matchLabel":x["match_label"],"whyRecommended":[v.get("message") for v in matched if isinstance(v,dict) and v.get("message")],"considerations":[v.get("message") for v in unmatched if isinstance(v,dict) and v.get("message")]})
        runs_by_session={}
        for x in runs: runs_by_session.setdefault(int(x["counselling_session_id"]),[]).append({"id":int(x["id"]),"engineVersion":x["engine_version"],"assessmentVersion":x["assessment_version"],"createdAt":x["created_at"],"completedAt":x["completed_at"],"outcomeStatus":x["outcome_status"],"recommendations":results_by_run.get(int(x["id"]),[])})
        interests_by_session={}
        for x in conn.execute(f"""SELECT i.*,c.course_name FROM counselling_course_interests i LEFT JOIN courses c ON c.id=i.course_id AND c.institute_id=i.institute_id WHERE i.institute_id=? AND i.counselling_session_id IN ({marks}) ORDER BY i.counselling_session_id,i.is_primary DESC,i.updated_at DESC""",(actor.institute_id,*ids)).fetchall(): interests_by_session.setdefault(int(x["counselling_session_id"]),[]).append({"courseId":int(x["course_id"]),"courseName":x["course_name"] or f"Course #{x['course_id']}","interestLevel":x["interest_level"],"primary":bool(x["is_primary"]),"updatedAt":x["updated_at"]})
        events_by_session={}
        emarks=",".join("?" for _ in USEFUL_EVENTS)
        for x in conn.execute(f"SELECT counselling_session_id,event_type,created_at FROM counselling_events WHERE institute_id=? AND counselling_session_id IN ({marks}) AND event_type IN ({emarks}) ORDER BY created_at DESC",(actor.institute_id,*ids,*USEFUL_EVENTS.keys())).fetchall(): events_by_session.setdefault(int(x["counselling_session_id"]),[]).append({"type":x["event_type"],"label":USEFUL_EVENTS[x["event_type"]],"at":x["created_at"]})
        items=[]
        for s in sessions:
            sid=int(s["id"]); assessment=assessment_by_session.get(sid); answers=answers_by_assessment.get(int(assessment["id"]),{}) if assessment else {}; sruns=runs_by_session.get(sid,[]); interests=interests_by_session.get(sid,[])
            items.append({"id":sid,"status":s["status"],"startedAt":s["started_at"],"completedAt":s.get("completed_at"),"abandonedAt":s.get("abandoned_at"),"counsellor":{"id":int(s["counsellor_user_id"]),"name":s["counsellor_name"]},"branch":{"id":int(s["branch_id"]),"name":s["branch_name"]},"verificationStatus":"VERIFIED" if s.get("mobile_verified") else "OVERRIDDEN" if s.get("verification_method")=="OVERRIDE" else "NOT_VERIFIED","assessment":{"status":assessment["status"] if assessment else None,"version":assessment["assessment_version"] if assessment else None,"answers":answers},"recommendationRuns":sruns,"finalRecommendationRun":sruns[0] if sruns else None,"interests":interests,"primaryInterest":next((x for x in interests if x["primary"]),None),"outcome":{"code":s.get("outcome"),"reason":s.get("outcome_reason"),"nextAction":s.get("next_action"),"nextFollowupDate":s.get("next_followup_date"),"staffNotes":s.get("staff_notes")},"activities":events_by_session.get(sid,[])})
        return {"lead":{"id":int(lead["id"]),"name":lead["name"]},"currentCrm":{"ownerId":lead.get("assigned_to_id"),"stage":lead.get("stage"),"status":lead.get("status"),"nextFollowupDate":lead.get("next_followup_date"),"student":{"id":int(student["id"]),"studentCode":student["student_code"],"name":student["full_name"],"viewUrl":f"/billing/student/{student['id']}"} if student else None},"sessions":items}
    finally: conn.close()
