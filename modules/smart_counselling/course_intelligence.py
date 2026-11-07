"""Tenant-safe Phase 5 course intelligence persistence and DTOs."""

import json
from datetime import datetime

from db import get_conn

from .errors import SmartCounsellingError, validation_error
from .questionnaire import CAREER_GOALS, EDUCATION_STATUSES, INTERESTS, QUALIFICATIONS, STREAMS


def _codes(items):
    return {item["code"] for item in items}


GOAL_CODES = _codes(CAREER_GOALS) - {"OTHER"}
INTEREST_CODES = _codes(INTERESTS) - {"OTHER"}
EDUCATION_CODES = _codes(EDUCATION_STATUSES)
QUALIFICATION_CODES = _codes(QUALIFICATIONS)
STREAM_CODES = _codes(STREAMS)
MATCH_STRENGTHS = {"PRIMARY", "STRONG", "SUPPORTED", "WEAK"}
STARTING_LEVELS = {"BEGINNER", "BEGINNER_TO_INTERMEDIATE", "INTERMEDIATE", "INTERMEDIATE_TO_ADVANCED", "ADVANCED"}
SKILL_DIMENSIONS = {"COMPUTER", "ACCOUNTING", "EXCEL", "ENGLISH", "PROGRAMMING"}
REQUIREMENT_LEVELS = {
    "COMPUTER": {"NONE", "BASIC", "INTERMEDIATE", "GOOD"},
    "ACCOUNTING": {"NONE", "BASIC", "INTERMEDIATE", "GOOD"},
    "EXCEL": {"NONE", "BASIC", "INTERMEDIATE", "GOOD"},
    "ENGLISH": {"NONE", "BEGINNER", "AVERAGE", "GOOD", "ADVANCED"},
    "PROGRAMMING": {"NONE", "BASIC", "SOME_EXPERIENCE", "COMFORTABLE"},
}
SKILL_CODES = {
    "ACCOUNTING", "TALLY_PRIME", "GST", "EXCEL", "MS_WORD", "POWERPOINT",
    "OFFICE_PRODUCTIVITY", "PROGRAMMING", "PYTHON", "C_PROGRAMMING", "AI_TOOLS",
    "COMMUNICATION", "SPOKEN_ENGLISH", "DIGITAL_MARKETING",
}


def taxonomy():
    return {
        "goals": CAREER_GOALS, "interests": INTERESTS,
        "educationLevels": EDUCATION_STATUSES, "qualifications": QUALIFICATIONS,
        "streams": STREAMS,
        "startingSkillLevels": sorted(STARTING_LEVELS),
        "matchStrengths": sorted(MATCH_STRENGTHS),
        "skillDimensions": sorted(SKILL_DIMENSIONS), "skillCodes": sorted(SKILL_CODES),
        "requirementLevels": {key: sorted(value) for key, value in REQUIREMENT_LEVELS.items()},
    }


def _course_or_404(conn, actor, course_id):
    row = conn.execute(
        """SELECT id, institute_id, course_name, duration, duration_hours, fee, course_type,
                  course_domain, course_category, is_active, show_on_website
           FROM courses WHERE id = ? AND institute_id = ? LIMIT 1""",
        (int(course_id), actor.institute_id),
    ).fetchone()
    if not row:
        raise SmartCounsellingError("not_found", "Course was not found.", 404)
    return dict(row)


def _admin(actor):
    if actor.role != "admin":
        raise SmartCounsellingError("forbidden", "Course intelligence is restricted to administrators.", 403)


def _rows(conn, institute_id, table, course_id, columns, order="id"):
    return [dict(row) for row in conn.execute(
        f"SELECT {columns} FROM {table} WHERE institute_id = ? AND course_id = ? ORDER BY {order}",
        (institute_id, course_id),
    ).fetchall()]


def _lms_summary(conn, institute_id, course_id):
    # Programs are tenant-owned; joining through both tenant keys prevents a
    # malformed cross-tenant mapping from leaking names.
    rows = conn.execute(
        """SELECT lp.id, lp.program_name, m.display_order
           FROM lms_course_program_map m
           JOIN lms_programs lp ON lp.id = m.program_id
           JOIN users owner ON owner.id = lp.created_by AND owner.institute_id = ?
           WHERE m.course_id = ? ORDER BY m.display_order, lp.id""",
        (institute_id, course_id),
    ).fetchall()
    programs = [{"id": int(r["id"]), "name": r["program_name"], "displayOrder": int(r["display_order"] or 0)} for r in rows]
    return {"mapped": bool(programs), "status": "LMS_MAPPED" if programs else "LMS_NOT_MAPPED", "programs": programs}


def _batch_summary(conn, institute_id, course_id):
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN b.status = 'active' THEN 1 ELSE 0 END) AS active
           FROM batches b JOIN branches br ON br.id = b.branch_id AND br.institute_id = ?
           WHERE b.course_id = ?""", (institute_id, course_id),
    ).fetchone()
    return {"total": int(row["total"] or 0), "active": int(row["active"] or 0)}


def _readiness(profile, goals, interests, requirements, skills, items, course):
    learning = [x for x in items if x["item_type"] == "LEARNING_OUTCOME"]
    checks = {
        "activeCourse": bool(course["is_active"]),
        "coursePurpose": bool(profile and (profile.get("course_purpose") or "").strip()),
        "recommendationEnabled": bool(profile and profile.get("recommendation_enabled")),
        "supportedGoals": bool(goals), "supportedInterests": bool(interests),
        "educationSuitability": bool(profile and profile.get("minimum_education_level")),
        "prerequisitesDefined": len(requirements) == len(SKILL_DIMENSIONS),
        "skillsTaught": bool(skills), "learningOutcomes": bool(learning),
    }
    profile_complete = all(value for key, value in checks.items() if key not in {"activeCourse", "recommendationEnabled"})
    ready = profile_complete and checks["activeCourse"] and checks["recommendationEnabled"]
    return {"checks": checks, "profileComplete": profile_complete, "recommendationReady": ready}


def _dto(conn, actor, course_id):
    course = _course_or_404(conn, actor, course_id)
    row = conn.execute("SELECT * FROM course_profiles WHERE institute_id=? AND course_id=?", (actor.institute_id, course_id)).fetchone()
    profile = dict(row) if row else None
    goals = _rows(conn, actor.institute_id, "course_supported_goals", course_id, "goal_code, match_strength, is_primary", "is_primary DESC, goal_code")
    interests = _rows(conn, actor.institute_id, "course_supported_interests", course_id, "interest_code, match_strength, is_primary", "is_primary DESC, interest_code")
    education = _rows(conn, actor.institute_id, "course_education_suitability", course_id, "education_code, suitability_type", "suitability_type, education_code")
    requirements = _rows(conn, actor.institute_id, "course_skill_requirements", course_id, "skill_dimension, minimum_level", "skill_dimension")
    skills = _rows(conn, actor.institute_id, "course_skills_taught", course_id, "skill_code, is_primary", "is_primary DESC, skill_code")
    items = _rows(conn, actor.institute_id, "course_profile_items", course_id, "item_type, item_text, display_order", "item_type, display_order, id")
    readiness = _readiness(profile, goals, interests, requirements, skills, items, course)
    if profile:
        profile = {key: value for key, value in profile.items() if key not in {"institute_id", "created_by_user_id", "updated_by_user_id"}}
        for key in ("certification_included", "external_exam_required", "recommendation_enabled"):
            profile[key] = bool(profile[key])
    return {
        "course": course, "profile": profile, "goals": goals, "interests": interests,
        "educationSuitability": education, "prerequisites": requirements, "skillsTaught": skills,
        "learningOutcomes": [x["item_text"] for x in items if x["item_type"] == "LEARNING_OUTCOME"],
        "careerOutcomes": [x["item_text"] for x in items if x["item_type"] == "CAREER_OUTCOME"],
        "jobRoles": [x["item_text"] for x in items if x["item_type"] == "JOB_ROLE"],
        **readiness, "lms": _lms_summary(conn, actor.institute_id, course_id),
        "batches": _batch_summary(conn, actor.institute_id, course_id),
    }


def get_course_profile(actor, course_id):
    conn = get_conn()
    try:
        return _dto(conn, actor, int(course_id))
    finally:
        conn.close()


def list_course_profiles(actor):
    conn = get_conn()
    try:
        courses = conn.execute("SELECT id FROM courses WHERE institute_id=? ORDER BY course_name", (actor.institute_id,)).fetchall()
        return [_dto(conn, actor, int(row["id"])) for row in courses]
    finally:
        conn.close()


def _normalized(payload):
    fields = {}
    text_fields = ("shortDescription", "detailedDescription", "coursePurpose", "minimumEducationLevel", "preferredBackground", "targetAudience", "hardEligibilityText", "startingSkillLevel", "certificationTitle", "certificationIssuingBody", "certificationDetails")
    for key in text_fields:
        value = payload.get(key)
        fields[key] = value.strip() if isinstance(value, str) and value.strip() else None
    if fields["minimumEducationLevel"] not in EDUCATION_CODES:
        raise validation_error("Choose a valid minimum education level.", {"minimumEducationLevel": "Invalid code."})
    if fields["startingSkillLevel"] and fields["startingSkillLevel"] not in STARTING_LEVELS:
        raise validation_error("Choose a valid starting skill level.", {"startingSkillLevel": "Invalid code."})
    fields.update({key: bool(payload.get(key)) for key in ("certificationIncluded", "externalExamRequired", "recommendationEnabled")})
    goals = payload.get("goals") or []
    interests = payload.get("interests") or []
    education = payload.get("educationSuitability") or []
    requirements = payload.get("prerequisites") or []
    skills = payload.get("skillsTaught") or []
    for item in goals:
        if item.get("code") not in GOAL_CODES or item.get("matchStrength", "SUPPORTED") not in MATCH_STRENGTHS:
            raise validation_error("A supported goal is invalid.", {"goals": "Invalid goal or strength."})
    for item in interests:
        if item.get("code") not in INTEREST_CODES or item.get("matchStrength", "SUPPORTED") not in MATCH_STRENGTHS:
            raise validation_error("A supported interest is invalid.", {"interests": "Invalid interest or strength."})
    for item in education:
        valid = item.get("type") in {"ALLOWED", "PREFERRED"} and item.get("code") in (QUALIFICATION_CODES | STREAM_CODES)
        if not valid: raise validation_error("Education suitability is invalid.", {"educationSuitability": "Invalid code or type."})
    for item in requirements:
        dimension = item.get("dimension"); level = item.get("minimumLevel")
        if dimension not in SKILL_DIMENSIONS or level not in REQUIREMENT_LEVELS.get(dimension, set()):
            raise validation_error("A prerequisite is invalid.", {"prerequisites": "Invalid dimension or level."})
    for item in skills:
        if item.get("code") not in SKILL_CODES:
            raise validation_error("A taught skill is invalid.", {"skillsTaught": "Invalid skill code."})
    def prose(name):
        values = payload.get(name) or []
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise validation_error("Outcome values must be non-empty text.", {name: "Invalid list."})
        return [v.strip() for v in values]
    return fields, goals, interests, education, requirements, skills, prose("learningOutcomes"), prose("careerOutcomes"), prose("jobRoles")


def save_course_profile(actor, course_id, payload):
    _admin(actor)
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        course = _course_or_404(conn, actor, course_id)
        before = _dto(conn, actor, course_id)
        if before["profile"]:
            p = before["profile"]
            current_payload = {
                "shortDescription": p.get("short_description"), "detailedDescription": p.get("detailed_description"),
                "coursePurpose": p.get("course_purpose"), "minimumEducationLevel": p.get("minimum_education_level"),
                "preferredBackground": p.get("preferred_background"), "targetAudience": p.get("target_audience"),
                "hardEligibilityText": p.get("hard_eligibility_text"), "startingSkillLevel": p.get("starting_skill_level"),
                "certificationTitle": p.get("certification_title"), "certificationIssuingBody": p.get("certification_issuing_body"),
                "certificationIncluded": p.get("certification_included"), "externalExamRequired": p.get("external_exam_required"),
                "certificationDetails": p.get("certification_details"), "recommendationEnabled": p.get("recommendation_enabled"),
                "goals": [{"code": x["goal_code"], "matchStrength": x["match_strength"], "isPrimary": bool(x["is_primary"])} for x in before["goals"]],
                "interests": [{"code": x["interest_code"], "matchStrength": x["match_strength"], "isPrimary": bool(x["is_primary"])} for x in before["interests"]],
                "educationSuitability": [{"code": x["education_code"], "type": x["suitability_type"]} for x in before["educationSuitability"]],
                "prerequisites": [{"dimension": x["skill_dimension"], "minimumLevel": x["minimum_level"]} for x in before["prerequisites"]],
                "skillsTaught": [{"code": x["skill_code"], "isPrimary": bool(x["is_primary"])} for x in before["skillsTaught"]],
                "learningOutcomes": before["learningOutcomes"], "careerOutcomes": before["careerOutcomes"], "jobRoles": before["jobRoles"],
            }
            current_payload.update(payload)
            payload = current_payload
        fields, goals, interests, education, requirements, skills, learning, career, roles = _normalized(payload)
        existing = before["profile"]
        db_fields = {
            "short_description": fields["shortDescription"], "detailed_description": fields["detailedDescription"],
            "course_purpose": fields["coursePurpose"], "minimum_education_level": fields["minimumEducationLevel"],
            "preferred_background": fields["preferredBackground"], "target_audience": fields["targetAudience"],
            "hard_eligibility_text": fields["hardEligibilityText"], "starting_skill_level": fields["startingSkillLevel"],
            "certification_title": fields["certificationTitle"], "certification_issuing_body": fields["certificationIssuingBody"],
            "certification_included": int(fields["certificationIncluded"]), "external_exam_required": int(fields["externalExamRequired"]),
            "certification_details": fields["certificationDetails"], "recommendation_enabled": int(fields["recommendationEnabled"]),
        }
        if existing:
            assignments = ", ".join(f"{key}=?" for key in db_fields)
            conn.execute(f"UPDATE course_profiles SET {assignments}, updated_by_user_id=?, updated_at=? WHERE institute_id=? AND course_id=?", (*db_fields.values(), actor.id, now, actor.institute_id, course_id))
        else:
            columns = ", ".join(db_fields); marks = ", ".join("?" for _ in db_fields)
            conn.execute(f"INSERT INTO course_profiles (institute_id, course_id, {columns}, created_by_user_id, updated_by_user_id, created_at, updated_at) VALUES (?, ?, {marks}, ?, ?, ?, ?)", (actor.institute_id, course_id, *db_fields.values(), actor.id, actor.id, now, now))
        for table in ("course_supported_goals", "course_supported_interests", "course_education_suitability", "course_skill_requirements", "course_skills_taught", "course_profile_items"):
            conn.execute(f"DELETE FROM {table} WHERE institute_id=? AND course_id=?", (actor.institute_id, course_id))
        conn.executemany("INSERT INTO course_supported_goals (institute_id,course_id,goal_code,match_strength,is_primary) VALUES (?,?,?,?,?)", [(actor.institute_id,course_id,x["code"],x.get("matchStrength","SUPPORTED"),int(bool(x.get("isPrimary")))) for x in goals])
        conn.executemany("INSERT INTO course_supported_interests (institute_id,course_id,interest_code,match_strength,is_primary) VALUES (?,?,?,?,?)", [(actor.institute_id,course_id,x["code"],x.get("matchStrength","SUPPORTED"),int(bool(x.get("isPrimary")))) for x in interests])
        conn.executemany("INSERT INTO course_education_suitability (institute_id,course_id,education_code,suitability_type) VALUES (?,?,?,?)", [(actor.institute_id,course_id,x["code"],x["type"]) for x in education])
        conn.executemany("INSERT INTO course_skill_requirements (institute_id,course_id,skill_dimension,minimum_level) VALUES (?,?,?,?)", [(actor.institute_id,course_id,x["dimension"],x["minimumLevel"]) for x in requirements])
        conn.executemany("INSERT INTO course_skills_taught (institute_id,course_id,skill_code,is_primary) VALUES (?,?,?,?)", [(actor.institute_id,course_id,x["code"],int(bool(x.get("isPrimary")))) for x in skills])
        rows=[]
        for kind, values in (("LEARNING_OUTCOME",learning),("CAREER_OUTCOME",career),("JOB_ROLE",roles)):
            rows.extend((actor.institute_id,course_id,kind,value,index) for index,value in enumerate(values))
        conn.executemany("INSERT INTO course_profile_items (institute_id,course_id,item_type,item_text,display_order) VALUES (?,?,?,?,?)", rows)
        after = _dto(conn, actor, course_id)
        changed = [key for key in ("profile","goals","interests","educationSuitability","prerequisites","skillsTaught","learningOutcomes","careerOutcomes","jobRoles") if before.get(key) != after.get(key)]
        event = "course_profile_created" if not existing else "course_profile_updated"
        if existing and bool(existing.get("recommendation_enabled")) != fields["recommendationEnabled"]:
            event = "recommendation_enabled" if fields["recommendationEnabled"] else "recommendation_disabled"
        conn.execute("INSERT INTO course_profile_events (institute_id,course_id,actor_user_id,event_type,changed_fields_json,created_at) VALUES (?,?,?,?,?,?)", (actor.institute_id, course_id, actor.id, event, json.dumps(changed), now))
        conn.commit()
        return after
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
