import json
import re
import unicodedata
from datetime import datetime, timezone

from db import get_conn
from modules.leads.helpers import can_access_lead

from .authorization import authorize_session, require_session_mutable
from .errors import SmartCounsellingError, validation_error
from .phone import normalize_indian_mobile
from .questionnaire import (
    ANSWER_OPTIONS,
    ASSESSMENT_VERSION,
    EDUCATION_TO_CRM,
    GOAL_TO_CRM,
    PROFILE_ENUMS,
    QUESTIONNAIRE_DTO,
    STREAM_TO_CRM,
    TIMEFRAME_TO_CRM,
    codes,
)
from .repository import get_session, insert_event
from .state_machine import IDENTIFICATION_PENDING, IDENTIFIED, IN_PROGRESS, require_transition


PROFILE_REQUIRED = {"name", "age", "educationStatus", "qualification", "currentSituation"}
PROFILE_FIELDS = {
    "name", "age", "educationStatus", "qualification", "qualificationOther", "stream",
    "institution", "currentYear", "currentSituation", "email", "whatsapp",
    "whatsappSameAsMobile", "gender",
}
LEAD_UPDATE_FIELDS = {
    "name": "name", "age": "age", "educationStatus": "education_status",
    "stream": "stream", "institution": "institute_name", "email": "email",
    "whatsapp": "whatsapp", "gender": "gender",
}
ASSESSMENT_KEYS = set(ANSWER_OPTIONS)
REQUIRED_ASSESSMENT_KEYS = {
    "current_situation", "primary_goal", "interests", "computer_skill",
    "accounting_skill", "excel_skill", "english_skill", "start_timeframe",
}
CURRENT_YEAR_EDUCATION = {"PUC_1", "PUC_2", "DIPLOMA", "DEGREE", "POSTGRADUATE"}
STREAM_EDUCATION = {
    "PUC_1", "PUC_2", "DIPLOMA", "DEGREE", "DEGREE_COMPLETED",
    "POSTGRADUATE", "POSTGRADUATE_COMPLETED",
}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def questionnaire():
    return QUESTIONNAIRE_DTO


def _option_code(value, option_list, field, *, required=True):
    value = str(value or "").strip().upper()
    if not value and not required:
        return None
    if value not in codes(option_list):
        raise validation_error("Choose a valid option.", {field: "Unsupported option."})
    return value


def _clean_name(value):
    name = " ".join(str(value or "").strip().split())
    letters = 0
    for character in name:
        category = unicodedata.category(character)
        if category.startswith("L") or category.startswith("M"):
            letters += 1
        elif character not in " .'-’":
            raise validation_error("Enter a valid prospect name.", {"name": "Remove invalid characters."})
    if letters < 2 or len(name) > 120:
        raise validation_error("Enter a valid prospect name.", {"name": "Use the prospect's real name."})
    return name


def _clean_email(value):
    email = str(value or "").strip().lower() or None
    if email and (len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
        raise validation_error("Enter a valid email address.", {"email": "Invalid email."})
    return email


def _validate_profile(payload, identity_mobile):
    unknown = set(payload) - PROFILE_FIELDS - {"confirmedFields"}
    if unknown:
        raise validation_error("The profile contains unsupported fields.", {"profile": "Unsupported fields supplied."})
    missing = [field for field in PROFILE_REQUIRED if payload.get(field) in (None, "")]
    if missing:
        raise validation_error("Complete the required profile fields.", {field: "Required." for field in missing})
    try:
        age = int(payload.get("age"))
    except (TypeError, ValueError):
        raise validation_error("Enter a valid age.", {"age": "Use a whole number."})
    if age < 12 or age > 100:
        raise validation_error("Enter a sensible age.", {"age": "Age must be between 12 and 100."})

    education = _option_code(payload.get("educationStatus"), PROFILE_ENUMS["educationStatus"], "educationStatus")
    qualification = _option_code(payload.get("qualification"), PROFILE_ENUMS["qualification"], "qualification")
    stream = _option_code(payload.get("stream"), PROFILE_ENUMS["stream"], "stream", required=False)
    current_situation = _option_code(payload.get("currentSituation"), PROFILE_ENUMS["currentSituation"], "currentSituation")
    gender = _option_code(payload.get("gender"), PROFILE_ENUMS["gender"], "gender", required=False)
    current_year = str(payload.get("currentYear") or "").strip() or None
    qualification_other = str(payload.get("qualificationOther") or "").strip() or None
    if education in STREAM_EDUCATION and not stream:
        raise validation_error("Choose the education stream.", {"stream": "Required for this education level."})
    if education in CURRENT_YEAR_EDUCATION and not current_year:
        raise validation_error("Enter the current class or year.", {"currentYear": "Required for this education level."})
    if qualification == "OTHER" and not qualification_other:
        raise validation_error("Describe the qualification.", {"qualificationOther": "Required for Other."})
    if current_year and len(current_year) > 80:
        raise validation_error("Current class or year is too long.", {"currentYear": "Use 80 characters or fewer."})
    if qualification_other and len(qualification_other) > 120:
        raise validation_error("Qualification description is too long.", {"qualificationOther": "Use 120 characters or fewer."})

    same_whatsapp = bool(payload.get("whatsappSameAsMobile"))
    whatsapp_normalized = identity_mobile if same_whatsapp else (
        normalize_indian_mobile(payload.get("whatsapp")) if payload.get("whatsapp") else None
    )
    return {
        "name": _clean_name(payload.get("name")), "age": age,
        "educationStatus": education, "qualification": qualification,
        "qualificationOther": qualification_other, "stream": stream,
        "institution": str(payload.get("institution") or "").strip()[:160] or None,
        "currentYear": current_year, "currentSituation": current_situation,
        "email": _clean_email(payload.get("email")),
        "whatsapp": whatsapp_normalized[-10:] if whatsapp_normalized else None,
        "whatsappSameAsMobile": same_whatsapp, "gender": gender,
    }


def _get_assessment(conn, institute_id, session_id):
    row = conn.execute(
        "SELECT * FROM counselling_assessments WHERE institute_id = ? AND counselling_session_id = ? LIMIT 1",
        (institute_id, session_id),
    ).fetchone()
    return dict(row) if row else None


def _answers(conn, assessment_id):
    rows = conn.execute(
        "SELECT question_key, answer_value FROM counselling_assessment_answers WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchall()
    return {row["question_key"]: json.loads(row["answer_value"]) for row in rows}


def _upsert_answer(conn, assessment_id, key, value, now):
    existing = conn.execute(
        "SELECT id FROM counselling_assessment_answers WHERE assessment_id = ? AND question_key = ?",
        (assessment_id, key),
    ).fetchone()
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if existing:
        conn.execute(
            "UPDATE counselling_assessment_answers SET answer_value = ?, updated_at = ? WHERE id = ?",
            (encoded, now, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO counselling_assessment_answers
                (assessment_id, question_key, answer_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (assessment_id, key, encoded, now, now),
        )


def _ensure_assessment(conn, actor, row, now):
    assessment = _get_assessment(conn, actor.institute_id, row["id"])
    if assessment:
        return assessment, False
    cursor = conn.execute(
        """
        INSERT INTO counselling_assessments (
            institute_id, counselling_session_id, lead_id, assessment_version,
            status, started_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?, ?, ?)
        """,
        (actor.institute_id, row["id"], row["lead_id"], ASSESSMENT_VERSION, now, now, now),
    )
    return {
        "id": int(cursor.lastrowid), "institute_id": actor.institute_id,
        "counselling_session_id": row["id"], "lead_id": row["lead_id"],
        "assessment_version": ASSESSMENT_VERSION, "status": "IN_PROGRESS",
        "started_at": now, "completed_at": None, "created_at": now, "updated_at": now,
    }, True


def _lead(conn, actor, lead_id):
    row = conn.execute(
        """
        SELECT id, institute_id, name, phone, whatsapp, email, gender, age,
               education_status, stream, institute_name, career_goal,
               start_timeframe, lead_source, decision_maker, branch_id,
               assigned_to_id, status, is_deleted
        FROM leads WHERE id = ? AND institute_id = ? LIMIT 1
        """,
        (lead_id, actor.institute_id),
    ).fetchone()
    if not row or row["is_deleted"]:
        raise SmartCounsellingError("not_found", "The linked lead was not found.", 404)
    data = dict(row)
    if not can_access_lead(actor.id, actor.role, data.get("assigned_to_id")):
        raise SmartCounsellingError("forbidden", "You cannot update this lead.", 403)
    return data


def _profile_dto(row, lead, answers):
    reverse_education = {
        "School Student": "SSLC", "PUC Student": "PUC_2", "Degree Student": "DEGREE",
        "Graduate": "DEGREE_COMPLETED", "Other": "OTHER",
    }
    reverse_stream = {value: key for key, value in STREAM_TO_CRM.items()}
    reverse_gender = {"Male": "MALE", "Female": "FEMALE", "Other": "OTHER"}
    profile = {
        "name": lead.get("name"), "age": lead.get("age"),
        "educationStatus": answers.get("education_status_code") or reverse_education.get(lead.get("education_status")),
        "qualification": answers.get("qualification"),
        "qualificationOther": answers.get("qualification_other"),
        "stream": answers.get("stream_code") or reverse_stream.get(lead.get("stream")),
        "institution": lead.get("institute_name"), "currentYear": answers.get("current_year"),
        "currentSituation": answers.get("current_situation"), "email": lead.get("email"),
        "whatsapp": lead.get("whatsapp"),
        "whatsappSameAsMobile": bool(lead.get("whatsapp") and str(lead.get("whatsapp"))[-10:] == str(row.get("identity_mobile_normalized") or "")[-10:]),
        "gender": answers.get("gender_code") or reverse_gender.get(lead.get("gender")),
    }
    return profile


def _assessment_complete(answers):
    if not REQUIRED_ASSESSMENT_KEYS.issubset(answers):
        return False
    if not isinstance(answers.get("interests"), list) or not answers["interests"]:
        return False
    if "PROGRAMMING" in answers["interests"] and not answers.get("programming_experience"):
        return False
    return True


def _progress(profile_complete, answers):
    if not profile_complete:
        return "PROFILE"
    if not answers.get("primary_goal") or not answers.get("interests") or not answers.get("start_timeframe"):
        return "GOALS"
    if not _assessment_complete(answers):
        return "SKILLS"
    return "RECOMMENDATIONS"


def get_profile(actor, session_id):
    conn = get_conn()
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        if not row.get("lead_id"):
            return {"leadId": None, "profile": None, "profileComplete": False, "nextStep": "PROFILE", "locked": False}
        lead = _lead(conn, actor, row["lead_id"])
        assessment = _get_assessment(conn, actor.institute_id, session_id)
        answers = _answers(conn, assessment["id"]) if assessment else {}
        return {
            "leadId": int(lead["id"]), "profile": _profile_dto(row, lead, answers),
            "profileComplete": bool(assessment), "nextStep": _progress(bool(assessment), answers),
            "locked": row.get("identification_status") == "EXISTING_STUDENT",
        }
    finally:
        conn.close()


def _create_new_lead(conn, actor, row, profile, now):
    # Serialize creation on the counselling-session row. InnoDB holds this row
    # lock until commit; SQLite obtains its write lock on the same statement.
    conn.execute(
        "UPDATE counselling_sessions SET updated_at = updated_at WHERE id = ? AND institute_id = ?",
        (row["id"], actor.institute_id),
    )
    refreshed = get_session(conn, actor.institute_id, row["id"])
    if refreshed.get("lead_id"):
        return int(refreshed["lead_id"]), False
    existing_request = conn.execute(
        "SELECT lead_id FROM counselling_lead_creation_requests WHERE counselling_session_id = ?",
        (row["id"],),
    ).fetchone()
    if existing_request and existing_request["lead_id"]:
        return int(existing_request["lead_id"]), False
    if not existing_request:
        conn.execute(
            """
            INSERT INTO counselling_lead_creation_requests
                (counselling_session_id, institute_id, created_at)
            VALUES (?, ?, ?)
            """,
            (row["id"], actor.institute_id, now),
        )
    mobile = row.get("identity_mobile_normalized")
    if not mobile:
        raise validation_error("The counselling identity has no mobile number.", {"mobile": "Verify or override the mobile first."})
    cursor = conn.execute(
        """
        INSERT INTO leads (
            institute_id, name, phone, whatsapp, email, gender, age, education_status,
            stream, institute_name, lead_source, decision_maker, stage, status,
            lead_score, is_deleted, assigned_to_id, branch_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Walk-in', 'Self', 'New Lead',
                  'active', 0, 0, ?, ?, ?, ?)
        """,
        (
            actor.institute_id, profile["name"], mobile[-10:], profile["whatsapp"], profile["email"],
            {"MALE": "Male", "FEMALE": "Female", "OTHER": "Other"}.get(profile["gender"]),
            profile["age"], EDUCATION_TO_CRM[profile["educationStatus"]],
            STREAM_TO_CRM.get(profile["stream"]), profile["institution"],
            actor.id, row["branch_id"], now, now,
        ),
    )
    lead_id = int(cursor.lastrowid)
    conn.execute(
        """
        UPDATE counselling_lead_creation_requests
        SET lead_id = ?, completed_at = ? WHERE counselling_session_id = ?
        """,
        (lead_id, now, row["id"]),
    )
    conn.execute(
        "UPDATE counselling_sessions SET lead_id = ?, updated_at = ? WHERE id = ? AND institute_id = ? AND lead_id IS NULL",
        (lead_id, now, row["id"], actor.institute_id),
    )
    return lead_id, True


def _update_existing_lead(conn, lead, profile, confirmed_fields, now):
    changes = {}
    proposed = {
        "name": profile["name"], "age": profile["age"],
        "educationStatus": EDUCATION_TO_CRM[profile["educationStatus"]],
        "stream": STREAM_TO_CRM.get(profile["stream"]), "institution": profile["institution"],
        "email": profile["email"], "whatsapp": profile["whatsapp"],
        "gender": {"MALE": "Male", "FEMALE": "Female", "OTHER": "Other"}.get(profile["gender"]),
    }
    for api_field, column in LEAD_UPDATE_FIELDS.items():
        if proposed[api_field] != lead.get(column):
            if api_field not in confirmed_fields:
                raise SmartCounsellingError(
                    "profile_conflict",
                    "Confirm each change to the existing CRM profile.",
                    409,
                    {api_field: "Confirm this CRM change before saving."},
                )
            changes[column] = proposed[api_field]
    if changes:
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE leads SET {assignments}, updated_at = ? WHERE id = ? AND institute_id = ?",
            (*changes.values(), now, lead["id"], lead["institute_id"]),
        )
    return sorted(changes)


def save_profile(actor, session_id, payload):
    conn = get_conn()
    now = _now()
    try:
        row = require_session_mutable(authorize_session(actor, get_session(conn, actor.institute_id, session_id)))
        allowed_identification = {"NEW", "UNVERIFIED_NEW", "EXISTING_LEAD"}
        if row.get("identification_status") not in allowed_identification:
            raise SmartCounsellingError("profile_not_available", "This identification result must be resolved before profile entry.", 409)
        profile = _validate_profile(payload, row.get("identity_mobile_normalized"))
        confirmed = set(payload.get("confirmedFields") or [])
        created = False
        changed_fields = []
        if row.get("lead_id"):
            lead = _lead(conn, actor, row["lead_id"])
            changed_fields = _update_existing_lead(conn, lead, profile, confirmed, now)
            lead_id = int(lead["id"])
        else:
            lead_id, created = _create_new_lead(conn, actor, row, profile, now)
            row = get_session(conn, actor.institute_id, session_id)

        if row["status"] == IDENTIFICATION_PENDING:
            require_transition(IDENTIFICATION_PENDING, IDENTIFIED)
            conn.execute("UPDATE counselling_sessions SET status = 'IDENTIFIED' WHERE id = ? AND institute_id = ?", (session_id, actor.institute_id))
            row["status"] = IDENTIFIED
        if row["status"] == IDENTIFIED:
            require_transition(IDENTIFIED, IN_PROGRESS)
            conn.execute("UPDATE counselling_sessions SET status = 'IN_PROGRESS', updated_at = ? WHERE id = ? AND institute_id = ?", (now, session_id, actor.institute_id))
            row["status"] = IN_PROGRESS
        row["lead_id"] = lead_id
        assessment, assessment_created = _ensure_assessment(conn, actor, row, now)
        profile_answers = {
            "education_status_code": profile["educationStatus"], "qualification": profile["qualification"],
            "qualification_other": profile["qualificationOther"], "stream_code": profile["stream"],
            "current_year": profile["currentYear"], "current_situation": profile["currentSituation"],
            "gender_code": profile["gender"], "mobile_verification_method": row.get("verification_method"),
        }
        for key, value in profile_answers.items():
            if value is not None:
                _upsert_answer(conn, assessment["id"], key, value, now)
        if assessment_created:
            insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead_id, actor_user_id=actor.id, event_type="assessment_started", metadata={"version": ASSESSMENT_VERSION}, now=now)
            insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead_id, actor_user_id=actor.id, event_type="profile_started", metadata={}, now=now)
        insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead_id, actor_user_id=actor.id, event_type="profile_saved", metadata={}, now=now)
        if created:
            insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead_id, actor_user_id=actor.id, event_type="new_lead_created", metadata={"source": "Walk-in", "origin": "SMART_COUNSELLING"}, now=now)
        elif changed_fields:
            insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=lead_id, actor_user_id=actor.id, event_type="existing_lead_profile_updated", metadata={"fields": changed_fields}, now=now)
        conn.commit()
        lead = _lead(conn, actor, lead_id)
        answers = _answers(conn, assessment["id"])
        return {"leadId": lead_id, "profile": _profile_dto(row, lead, answers), "profileComplete": True, "assessmentComplete": _assessment_complete(answers), "nextStep": _progress(True, answers), "created": created}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validate_answers(payload):
    if not isinstance(payload, dict) or not payload:
        raise validation_error("Provide at least one assessment answer.", {"answers": "Required."})
    unknown = set(payload) - ASSESSMENT_KEYS
    if unknown:
        raise validation_error("The assessment contains unsupported questions.", {"answers": "Unsupported question key."})
    validated = {}
    for key, value in payload.items():
        valid_codes = codes(ANSWER_OPTIONS[key])
        if key == "interests":
            if not isinstance(value, list) or not value or len(value) > len(valid_codes):
                raise validation_error("Choose one or more valid interests.", {"interests": "Invalid selection."})
            normalized = list(dict.fromkeys(str(item).strip().upper() for item in value))
            if any(item not in valid_codes for item in normalized):
                raise validation_error("Choose valid interests.", {"interests": "Unsupported interest."})
            validated[key] = normalized
        else:
            normalized = str(value or "").strip().upper()
            if normalized not in valid_codes:
                raise validation_error("Choose a valid assessment option.", {key: "Unsupported option."})
            validated[key] = normalized
    return validated


def get_assessment(actor, session_id):
    conn = get_conn()
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        if not row.get("lead_id"):
            return {"assessment": None, "answers": {}, "profileComplete": False, "assessmentComplete": False, "nextStep": "PROFILE"}
        assessment = _get_assessment(conn, actor.institute_id, session_id)
        answers = _answers(conn, assessment["id"]) if assessment else {}
        complete = _assessment_complete(answers)
        return {"assessment": ({"id": assessment["id"], "version": assessment["assessment_version"], "status": assessment["status"]} if assessment else None), "answers": answers, "profileComplete": bool(assessment), "assessmentComplete": complete, "nextStep": _progress(bool(assessment), answers)}
    finally:
        conn.close()


def save_assessment(actor, session_id, payload):
    values = _validate_answers(payload.get("answers") if isinstance(payload, dict) else None)
    conn = get_conn()
    now = _now()
    try:
        row = require_session_mutable(authorize_session(actor, get_session(conn, actor.institute_id, session_id)))
        if row["status"] != IN_PROGRESS or not row.get("lead_id"):
            raise SmartCounsellingError("profile_required", "Complete the prospect profile first.", 409)
        assessment = _get_assessment(conn, actor.institute_id, session_id)
        if not assessment or int(assessment["lead_id"]) != int(row["lead_id"]):
            raise SmartCounsellingError("profile_required", "Complete the prospect profile first.", 409)
        current = _answers(conn, assessment["id"])
        combined = {**current, **values}
        if "PROGRAMMING" in combined.get("interests", []) and "programming_experience" not in combined:
            if "interests" in values and payload.get("complete"):
                raise validation_error("Add programming experience.", {"programming_experience": "Required when Programming is selected."})
        for key, value in values.items():
            _upsert_answer(conn, assessment["id"], key, value, now)
        complete = _assessment_complete(combined)
        requested_complete = bool(payload.get("complete"))
        if requested_complete and not complete:
            raise validation_error("Complete all required assessment questions.", {"assessment": "Required answers are missing."})
        status = "COMPLETED" if complete and (requested_complete or assessment["status"] == "COMPLETED") else "IN_PROGRESS"
        conn.execute(
            """
            UPDATE counselling_assessments
            SET status = ?, completed_at = CASE WHEN ? = 'COMPLETED' THEN ? ELSE completed_at END,
                updated_at = ? WHERE id = ? AND institute_id = ?
            """,
            (status, status, now, now, assessment["id"], actor.institute_id),
        )
        event_types = []
        if {"primary_goal", "start_timeframe"} & set(values): event_types.append("goals_saved")
        if "interests" in values: event_types.append("interests_saved")
        if {"computer_skill", "accounting_skill", "excel_skill", "english_skill", "programming_experience"} & set(values): event_types.append("skills_saved")
        if status == "COMPLETED" and assessment["status"] != "COMPLETED": event_types.append("assessment_completed")
        for event_type in event_types:
            insert_event(conn, institute_id=actor.institute_id, session_id=session_id, lead_id=row["lead_id"], actor_user_id=actor.id, event_type=event_type, metadata={"version": ASSESSMENT_VERSION}, now=now)
        if "primary_goal" in values or "start_timeframe" in values:
            updates = []
            params = []
            if "primary_goal" in values: updates.append("career_goal = ?"); params.append(GOAL_TO_CRM[values["primary_goal"]])
            if "start_timeframe" in values: updates.append("start_timeframe = ?"); params.append(TIMEFRAME_TO_CRM[values["start_timeframe"]])
            params.extend([now, row["lead_id"], actor.institute_id])
            conn.execute(f"UPDATE leads SET {', '.join(updates)}, updated_at = ? WHERE id = ? AND institute_id = ?", tuple(params))
        conn.commit()
        return {"assessment": {"id": assessment["id"], "version": ASSESSMENT_VERSION, "status": status}, "answers": combined, "profileComplete": True, "assessmentComplete": status == "COMPLETED", "nextStep": _progress(True, combined)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
