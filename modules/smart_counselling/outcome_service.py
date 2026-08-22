"""Phase 8 counselling outcome, CRM follow-up, completion, and handoff service."""

import json
from datetime import date, datetime

from db import get_conn, log_activity

from .authorization import authorize_session
from .errors import SmartCounsellingError, validation_error
from .outcome_policy import NEXT_ACTION_LABELS, OUTCOME_POLICIES, policy_dto
from .repository import get_session, insert_event


def _now(): return datetime.now().isoformat(timespec="seconds")


def _context(conn, actor, session_id):
    session = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
    if not session.get("lead_id"):
        raise SmartCounsellingError("lead_required", "Identify a prospect before recording an outcome.", 409)
    lead = conn.execute("SELECT * FROM leads WHERE id=? AND institute_id=? AND is_deleted=0", (session["lead_id"], actor.institute_id)).fetchone()
    if not lead: raise SmartCounsellingError("not_found", "The linked lead was not found.", 404)
    run = conn.execute("SELECT * FROM recommendation_runs WHERE institute_id=? AND counselling_session_id=? AND status='COMPLETED' ORDER BY id DESC LIMIT 1", (actor.institute_id, session_id)).fetchone()
    if not run: raise SmartCounsellingError("recommendations_required", "Generate course recommendations first.", 409)
    return session, dict(lead), dict(run)


def _interests(conn, actor, session_id, run_id):
    rows = conn.execute("""SELECT i.course_id,i.interest_level,i.is_primary,i.updated_at,c.course_name
      FROM counselling_course_interests i JOIN courses c ON c.id=i.course_id AND c.institute_id=i.institute_id
      WHERE i.institute_id=? AND i.counselling_session_id=? AND i.recommendation_run_id=? ORDER BY i.is_primary DESC,i.updated_at DESC""", (actor.institute_id, session_id, run_id)).fetchall()
    return [{"courseId": int(x["course_id"]), "courseName": x["course_name"], "interestLevel": x["interest_level"], "primary": bool(x["is_primary"])} for x in rows]


def _converted_student(conn, actor, lead_id):
    row = conn.execute("SELECT id,student_code,full_name FROM students WHERE lead_id=? AND institute_id=? ORDER BY id LIMIT 1", (lead_id, actor.institute_id)).fetchone()
    return {"id": int(row["id"]), "studentCode": row["student_code"], "name": row["full_name"], "viewUrl": f"/billing/student/{row['id']}"} if row else None


def _snapshot(conn, actor, session, lead, run):
    interests = _interests(conn, actor, session["id"], run["id"])
    top = conn.execute("""SELECT rr.course_id,rr.normalized_score,rr.match_label,c.course_name FROM recommendation_results rr
      JOIN courses c ON c.id=rr.course_id AND c.institute_id=rr.institute_id
      WHERE rr.institute_id=? AND rr.recommendation_run_id=? ORDER BY rr.result_rank LIMIT 1""", (actor.institute_id, run["id"])).fetchone()
    answers = {}
    assessment = conn.execute("SELECT id,status FROM counselling_assessments WHERE institute_id=? AND counselling_session_id=?", (actor.institute_id, session["id"])).fetchone()
    if assessment:
        for row in conn.execute("SELECT question_key,answer_value FROM counselling_assessment_answers WHERE assessment_id=?", (assessment["id"],)).fetchall():
            try: answers[row["question_key"]] = json.loads(row["answer_value"])
            except (TypeError, json.JSONDecodeError): answers[row["question_key"]] = row["answer_value"]
    primary = next((x for x in interests if x["primary"]), None)
    student = _converted_student(conn, actor, lead["id"])
    return {"sessionId": int(session["id"]), "status": session["status"], "completedAt": session.get("completed_at"),
      "prospect": {"id": int(lead["id"]), "name": lead["name"], "verificationStatus": "VERIFIED" if session.get("mobile_verified") else "OVERRIDDEN" if session.get("verification_method") == "OVERRIDE" else "NOT_VERIFIED", "qualification": answers.get("qualification") or lead.get("education_status"), "primaryGoal": answers.get("primary_goal") or lead.get("career_goal"), "viewUrl": f"/leads/{lead['id']}"},
      "topRecommendation": {"courseId": int(top["course_id"]), "courseName": top["course_name"], "score": int(top["normalized_score"]), "matchLabel": top["match_label"]} if top else None,
      "primaryInterest": primary, "otherInterests": [x for x in interests if not x["primary"] and x["interestLevel"] != "NOT_INTERESTED"],
      "outcome": session.get("outcome"), "outcomeReason": session.get("outcome_reason"), "nextAction": session.get("next_action"), "nextFollowupDate": session.get("next_followup_date"), "staffNotes": session.get("staff_notes"),
      "counsellor": {"id": int(session["counsellor_user_id"]), "name": session["counsellor_name"]},
      "followupId": session.get("completion_followup_id"), "admissionHandoffAvailable": session.get("status") == "COMPLETED" and session.get("outcome") == "READY_FOR_ADMISSION" and not student and lead.get("status") != "converted",
      "admissionUrl": f"/billing/student/new?from_lead={lead['id']}", "student": student,
      "alreadyRegistered": bool(student or lead.get("status") == "converted"),
    }


def _validate(payload, interests, *, complete):
    outcome = str(payload.get("outcome") or "").strip().upper()
    if not outcome:
        if complete: raise validation_error("Choose a counselling outcome.", {"outcome": "Required."})
        return {"valid": False, "missing": ["outcome"]}
    policy = OUTCOME_POLICIES.get(outcome)
    if not policy: raise validation_error("Choose a valid counselling outcome.", {"outcome": "Invalid code."})
    reason = str(payload.get("outcomeReason") or "").strip().upper() or None
    if reason and reason not in policy["reasons"]: raise validation_error("Choose a valid outcome reason.", {"outcomeReason": "Invalid code."})
    if policy["reasons"] and complete and not reason: raise validation_error("Choose an outcome reason.", {"outcomeReason": "Required."})
    action = str(payload.get("nextAction") or "").strip().upper() or None
    if action and action not in policy["actions"]: raise validation_error("Choose a next action allowed for this outcome.", {"nextAction": "Invalid for outcome."})
    if complete and not action: raise validation_error("Choose the next action.", {"nextAction": "Required."})
    primary = next((x for x in interests if x["primary"]), None)
    interested = [x for x in interests if x["interestLevel"] in {"INTERESTED", "HIGHLY_INTERESTED"}]
    if complete and policy["primary"] and not primary: raise validation_error("Choose a primary interested course.", {"primaryCourse": "Required."})
    if complete and policy["interested"] and not interested: raise validation_error("Record an interested course for this outcome.", {"courseInterest": "Required."})
    followup_required = policy["followup"] or (outcome == "NOT_INTERESTED" and action not in {None, "NO_FURTHER_ACTION"})
    followup_date = str(payload.get("nextFollowupDate") or "").strip() or None
    if followup_date:
        try: parsed = datetime.strptime(followup_date, "%Y-%m-%d").date()
        except ValueError: raise validation_error("Choose a valid follow-up date.", {"nextFollowupDate": "Invalid date."})
        if parsed < date.today(): raise validation_error("Follow-up date cannot be in the past.", {"nextFollowupDate": "Past date."})
    if complete and followup_required and not followup_date: raise validation_error("Choose the next follow-up date.", {"nextFollowupDate": "Required."})
    notes = str(payload.get("staffNotes") or "").strip() or None
    if complete and (reason == "OTHER" or action == "OTHER") and not notes: raise validation_error("Add a short clarification for Other.", {"staffNotes": "Required for Other."})
    return {"valid": bool(outcome and (not policy["reasons"] or reason) and action and (not policy["primary"] or primary) and (not policy["interested"] or interested) and (not followup_required or followup_date)), "missing": [], "outcome": outcome, "reason": reason, "action": action, "followupDate": followup_date, "notes": notes, "followupRequired": followup_required, "primary": primary}


def get_outcome(actor, session_id):
    conn = get_conn()
    try:
        session, lead, run = _context(conn, actor, session_id); interests = _interests(conn, actor, session_id, run["id"])
        current = {"outcome": session.get("outcome"), "outcomeReason": session.get("outcome_reason"), "nextAction": session.get("next_action"), "nextFollowupDate": session.get("next_followup_date"), "staffNotes": session.get("staff_notes")}
        validation = _validate(current, interests, complete=False)
        return {"policies": policy_dto(), "current": current, "interests": interests, "primaryInterest": next((x for x in interests if x["primary"]), None), "validation": validation, "summary": _snapshot(conn, actor, session, lead, run)}
    finally: conn.close()


def save_outcome(actor, session_id, payload):
    conn = get_conn(); now = _now()
    try:
        session, lead, run = _context(conn, actor, session_id)
        if session["status"] in {"COMPLETED", "ABANDONED"}: raise SmartCounsellingError("session_completed", "A completed counselling session cannot be changed.", 409)
        values = _validate(payload, _interests(conn, actor, session_id, run["id"]), complete=False)
        conn.execute("""UPDATE counselling_sessions SET outcome=?,outcome_reason=?,next_action=?,next_followup_date=?,staff_notes=?,status='OUTCOME_PENDING',updated_at=? WHERE id=? AND institute_id=?""", (values.get("outcome"), values.get("reason"), values.get("action"), values.get("followupDate"), values.get("notes"), now, session_id, actor.institute_id))
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead["id"], actor_user_id=actor.id, event_type="outcome_draft_saved", metadata={"outcome": values.get("outcome"), "nextAction": values.get("action")}, now=now)
        conn.commit(); return get_outcome(actor, session_id)
    except Exception: conn.rollback(); raise
    finally: conn.close()


def complete_session(actor, session_id, payload):
    conn = get_conn(); now = _now(); today = date.today().isoformat()
    try:
        session, lead, run = _context(conn, actor, session_id)
        conn.execute("UPDATE counselling_sessions SET updated_at=updated_at WHERE id=? AND institute_id=?", (session_id, actor.institute_id))
        session = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        if session["status"] == "COMPLETED": return _snapshot(conn, actor, session, lead, run)
        if session["status"] == "ABANDONED": raise SmartCounsellingError("invalid_transition", "An abandoned session cannot be completed.", 409)
        merged = {"outcome": payload.get("outcome", session.get("outcome")), "outcomeReason": payload.get("outcomeReason", session.get("outcome_reason")), "nextAction": payload.get("nextAction", session.get("next_action")), "nextFollowupDate": payload.get("nextFollowupDate", session.get("next_followup_date")), "staffNotes": payload.get("staffNotes", session.get("staff_notes"))}
        valid = _validate(merged, _interests(conn, actor, session_id, run["id"]), complete=True)
        followup_id = session.get("completion_followup_id")
        if valid["followupRequired"] and not followup_id:
            note = "Smart Counselling follow-up" + (f": {valid['notes']}" if valid["notes"] else "")
            cursor = conn.execute("""INSERT INTO followups(institute_id,lead_id,user_id,method,outcome,note,next_followup_date,created_at) VALUES(?,?,?,?,?,?,?,?)""", (actor.institute_id, lead["id"], actor.id, "Smart Counselling", valid["outcome"], note, valid["followupDate"], now))
            followup_id = int(cursor.lastrowid)
            insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead["id"], actor_user_id=actor.id, event_type="followup_created", metadata={"followupId": followup_id, "outcome": valid["outcome"], "courseId": valid["primary"]["courseId"] if valid["primary"] else None}, now=now)
        stage = lead.get("stage")
        if lead.get("status") not in {"converted", "lost"}:
            stage = "Follow-up" if followup_id else "Counseling Done"
        parent = lead.get("parent_discussion_status")
        if valid["outcome"] == "PARENT_DISCUSSION_REQUIRED" and parent in {None, "", "Pending", "Not Required"}: parent = "Scheduled"
        conn.execute("""UPDATE leads SET stage=?,last_contact_date=?,next_followup_date=CASE WHEN ? IS NOT NULL THEN ? ELSE next_followup_date END,followup_count=followup_count+?,parent_discussion_status=?,updated_at=? WHERE id=? AND institute_id=?""", (stage, today, followup_id, valid["followupDate"], 1 if followup_id else 0, parent, now, lead["id"], actor.institute_id))
        conn.execute("""UPDATE counselling_sessions SET outcome=?,outcome_reason=?,next_action=?,next_followup_date=?,staff_notes=?,primary_interested_course_id=?,completion_followup_id=?,status='COMPLETED',completed_at=?,updated_at=? WHERE id=? AND institute_id=?""", (valid["outcome"], valid["reason"], valid["action"], valid["followupDate"], valid["notes"], valid["primary"]["courseId"] if valid["primary"] else None, followup_id, now, now, session_id, actor.institute_id))
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead["id"], actor_user_id=actor.id, event_type="outcome_selected", metadata={"outcome": valid["outcome"]}, now=now)
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead["id"], actor_user_id=actor.id, event_type="next_action_selected", metadata={"nextAction": valid["action"]}, now=now)
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead["id"], actor_user_id=actor.id, event_type="counselling_completed", metadata={"outcome": valid["outcome"], "nextAction": valid["action"], "courseId": valid["primary"]["courseId"] if valid["primary"] else None, "followupId": followup_id}, now=now)
        log_activity(user_id=actor.id, branch_id=session["branch_id"], action_type="smart_counselling_completed", module_name="leads", record_id=lead["id"], description=f"Smart Counselling completed - Outcome: {valid['outcome']}", conn=conn, institute_id=actor.institute_id)
        conn.commit()
        completed = authorize_session(actor, get_session(conn, actor.institute_id, session_id)); return _snapshot(conn, actor, completed, {**lead, "stage": stage, "parent_discussion_status": parent}, run)
    except Exception: conn.rollback(); raise
    finally: conn.close()


def get_summary(actor, session_id):
    conn = get_conn()
    try:
        session, lead, run = _context(conn, actor, session_id)
        if session["status"] != "COMPLETED": raise SmartCounsellingError("outcome_pending", "Complete counselling before opening the final summary.", 409)
        return _snapshot(conn, actor, session, lead, run)
    finally: conn.close()


def open_admission_handoff(actor, session_id):
    conn = get_conn(); now = _now()
    try:
        session, lead, run = _context(conn, actor, session_id)
        if session["status"] != "COMPLETED" or session.get("outcome") != "READY_FOR_ADMISSION": raise SmartCounsellingError("handoff_unavailable", "Admission handoff is not available for this session.", 409)
        student = _converted_student(conn, actor, lead["id"])
        if student or lead.get("status") == "converted": return {"available": False, "alreadyRegistered": True, "student": student, "message": "Prospect is already registered as a student."}
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead["id"], actor_user_id=actor.id, event_type="admission_handoff_opened", metadata={"courseId": session.get("primary_interested_course_id")}, now=now)
        conn.commit(); return {"available": True, "alreadyRegistered": False, "url": f"/billing/student/new?from_lead={lead['id']}"}
    finally: conn.close()
