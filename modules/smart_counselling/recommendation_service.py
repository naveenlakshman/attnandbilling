"""Authorization, persistence, and DTO boundary for recommendation engine V1."""

import json
from datetime import datetime

from db import get_conn

from .assessment_service import _answers, _get_assessment
from .authorization import authorize_session, require_session_mutable
from .course_intelligence import _dto
from .errors import SmartCounsellingError
from .recommendation_engine import (
    BEST_MATCH_THRESHOLD, DISPLAY_THRESHOLD, ENGINE_VERSION, TOP_LIMIT, rank_courses,
)
from .repository import get_session, insert_event


def _now(): return datetime.now().isoformat(timespec="seconds")


def _prospect(answers):
    return {
        "education_status_code": answers.get("education_status_code"),
        "qualification": answers.get("qualification"), "stream_code": answers.get("stream_code"),
        "current_situation": answers.get("current_situation"), "primary_goal": answers.get("primary_goal"),
        "interests": answers.get("interests") or [], "computer_skill": answers.get("computer_skill"),
        "accounting_skill": answers.get("accounting_skill"), "excel_skill": answers.get("excel_skill"),
        "english_skill": answers.get("english_skill"), "programming_experience": answers.get("programming_experience"),
        "start_timeframe": answers.get("start_timeframe"), "preferred_duration": answers.get("preferred_duration"),
        "preferred_learning_mode": answers.get("preferred_learning_mode"),
    }


def _ready_courses(conn, actor):
    ids = conn.execute("SELECT id FROM courses WHERE institute_id=? AND is_active=1 ORDER BY id", (actor.institute_id,)).fetchall()
    return [item for item in (_dto(conn, actor, int(row["id"])) for row in ids) if item["recommendationReady"]]


def _result_dto(row):
    return {
        "courseId": int(row["course_id"]), "courseName": row["course_name_snapshot"],
        "courseCategory": row["course_category_snapshot"], "rank": int(row["result_rank"]) if row["result_rank"] is not None else None,
        "score": int(row["normalized_score"]) if row["normalized_score"] is not None else None,
        "matchLabel": row["match_label"], "eligibilityStatus": row["eligibility_status"],
        "whyRecommended": [x["message"] for x in json.loads(row["matched_factors_json"] or "[]")],
        "considerations": [x["message"] for x in json.loads(row["unmatched_factors_json"] or "[]")],
        "skillChips": json.loads(row["skill_chips_json"] or "[]"),
        "bestMatch": bool(row["result_rank"] == 1 and (row["normalized_score"] or 0) >= BEST_MATCH_THRESHOLD),
        "actions": {"courseDetails": "PHASE_7", "syllabus": "PHASE_7", "comparison": "PHASE_7"},
    }


def _run_dto(conn, run):
    rows = conn.execute(
        """SELECT * FROM recommendation_results WHERE recommendation_run_id=? AND institute_id=?
           ORDER BY CASE WHEN result_rank IS NULL THEN 1 ELSE 0 END, result_rank, course_id""",
        (run["id"], run["institute_id"]),
    ).fetchall()
    eligible = [_result_dto(row) for row in rows if row["eligibility_status"] == "ELIGIBLE"]
    return {
        "run": {"id": int(run["id"]), "engineVersion": run["engine_version"], "assessmentVersion": run["assessment_version"], "createdAt": run["created_at"]},
        "status": run["outcome_status"],
        "recommendations": [x for x in eligible if x["score"] >= DISPLAY_THRESHOLD][:TOP_LIMIT],
        "otherSuitableCourses": [x for x in eligible if x["score"] < DISPLAY_THRESHOLD][:5],
        "decisionSupportNote": "Recommendations support counsellor judgment and do not automatically determine admission.",
    }


def generate_recommendations(actor, session_id):
    conn = get_conn(); now = _now()
    try:
        session = require_session_mutable(authorize_session(actor, get_session(conn, actor.institute_id, session_id)))
        assessment = _get_assessment(conn, actor.institute_id, session_id)
        if not assessment or assessment["status"] != "COMPLETED":
            raise SmartCounsellingError("assessment_incomplete", "Complete the prospect profile and assessment before generating recommendations.", 409, {"nextStep": "SKILLS"})
        answers = _answers(conn, assessment["id"])
        prospect = _prospect(answers)
        courses = _ready_courses(conn, actor)
        calculated = rank_courses(prospect, courses)
        previous = conn.execute("SELECT id FROM recommendation_runs WHERE institute_id=? AND counselling_session_id=? AND status='COMPLETED' LIMIT 1", (actor.institute_id, session_id)).fetchone()
        cursor = conn.execute(
            """INSERT INTO recommendation_runs (institute_id,counselling_session_id,lead_id,assessment_id,assessment_version,engine_version,status,outcome_status,prospect_snapshot_json,created_by_user_id,created_at,completed_at)
               VALUES (?,?,?,?,?,?,'PENDING',?,?,?, ?,NULL)""",
            (actor.institute_id, session_id, session["lead_id"], assessment["id"], assessment["assessment_version"], ENGINE_VERSION, calculated["status"], json.dumps(prospect, sort_keys=True), actor.id, now),
        )
        run_id = int(cursor.lastrowid)
        event = "recommendation_recalculated" if previous else "recommendation_started"
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=session["lead_id"], actor_user_id=actor.id, event_type=event, metadata={"runId":run_id,"engineVersion":ENGINE_VERSION}, now=now)
        rank_by_course = {int(x["course"]["course"]["id"]): x["rank"] for x in calculated["top"] + calculated["other"]}
        # Eligible courses above the first five secondary entries still retain
        # their deterministic rank from the engine's complete eligible list.
        for x in calculated["all"]:
            if x["eligibilityStatus"] == "ELIGIBLE": rank_by_course[int(x["course"]["course"]["id"])] = x.get("rank")
        for result in calculated["all"]:
            course = result["course"]; core = course["course"]; profile = course.get("profile") or {}
            chips = [x["skill_code"] for x in course.get("skillsTaught", [])][:6]
            explanation = result["matchedFactors"][0]["message"] if result["matchedFactors"] else (result["ineligibilityReasons"][0]["message"] if result["ineligibilityReasons"] else None)
            conn.execute(
                """INSERT INTO recommendation_results (recommendation_run_id,institute_id,course_id,course_name_snapshot,course_category_snapshot,course_profile_updated_at,result_rank,raw_score,normalized_score,match_label,eligibility_status,matched_factors_json,unmatched_factors_json,ineligibility_reasons_json,skill_chips_json,explanation,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id,actor.institute_id,core["id"],core["course_name"],core.get("course_category"),profile.get("updated_at"),rank_by_course.get(int(core["id"])),result["rawScore"],result["score"],result["matchLabel"],result["eligibilityStatus"],json.dumps(result["matchedFactors"]),json.dumps(result["unmatchedFactors"]),json.dumps(result["ineligibilityReasons"]),json.dumps(chips),explanation,now),
            )
        conn.execute("UPDATE recommendation_runs SET status='COMPLETED', completed_at=? WHERE id=? AND institute_id=?", (now,run_id,actor.institute_id))
        final_event = "recommendation_completed" if calculated["status"] == "MATCHES_FOUND" else "recommendation_no_match"
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=session["lead_id"], actor_user_id=actor.id, event_type=final_event, metadata={"runId":run_id,"engineVersion":ENGINE_VERSION,"resultCount":len(calculated["top"])}, now=now)
        conn.commit()
        run = conn.execute("SELECT * FROM recommendation_runs WHERE id=? AND institute_id=?", (run_id,actor.institute_id)).fetchone()
        return _run_dto(conn, run)
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def get_current_recommendations(actor, session_id):
    conn = get_conn()
    try:
        authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        run = conn.execute("""SELECT * FROM recommendation_runs WHERE institute_id=? AND counselling_session_id=? AND status='COMPLETED' ORDER BY id DESC LIMIT 1""", (actor.institute_id,session_id)).fetchone()
        if not run:
            return {"run":None,"status":"NOT_GENERATED","recommendations":[],"otherSuitableCourses":[],"decisionSupportNote":"Recommendations support counsellor judgment and do not automatically determine admission."}
        return _run_dto(conn, run)
    finally:
        conn.close()
