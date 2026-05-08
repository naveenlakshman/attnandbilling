from datetime import date, datetime
from db import log_activity

VALID_STAGES = [
    "New Lead",
    "Contacted",
    "Interested",
    "Counseling Done",
    "Follow-up",
    "Converted",
    "Lost",
]


def _parse_yyyy_mm_dd(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_updated_at_date(value):
    text = (value or "").strip()
    if not text:
        return None
    # updated_at is ISO datetime text in this codebase.
    day_part = text.split("T", 1)[0]
    return _parse_yyyy_mm_dd(day_part)


def compute_lead_score(lead_data):
    lead_source = (lead_data.get("lead_source") or "").strip()
    start_timeframe = (lead_data.get("start_timeframe") or "").strip()
    education_status = (lead_data.get("education_status") or "").strip()
    career_goal = (lead_data.get("career_goal") or "").strip()

    score = 0

    if lead_source in ["Walk-in", "Referral"]:
        score += 25
    elif lead_source in ["Instagram", "WhatsApp", "College Campaign"]:
        score += 15
    elif lead_source:
        score += 10

    if start_timeframe == "Immediately":
        score += 25
    elif start_timeframe == "Within 1 Week":
        score += 20
    elif start_timeframe == "Within 1 Month":
        score += 10
    elif start_timeframe == "Exploring":
        score += 5

    if education_status in ["Degree Student", "Graduate", "Job Seeker", "Working Professional"]:
        score += 20
    elif education_status:
        score += 10

    if career_goal in ["Job", "Skill Development", "Career Switch"]:
        score += 20
    elif career_goal:
        score += 10

    return min(score, 100)


def map_stage_to_status(stage):
    if stage == "Converted":
        return "converted"
    if stage == "Lost":
        return "lost"
    return "active"


def get_followup_status(next_followup_date, today=None):
    due_date = _parse_yyyy_mm_dd(next_followup_date)
    if not due_date:
        return "none"

    current_day = today or date.today()
    if due_date < current_day:
        return "overdue"
    if due_date == current_day:
        return "today"
    return "upcoming"


def get_inactive_days(last_contact_date, updated_at, today=None):
    current_day = today or date.today()
    contact_day = _parse_yyyy_mm_dd(last_contact_date)
    base_day = contact_day or _parse_updated_at_date(updated_at)
    if not base_day:
        return None
    return max((current_day - base_day).days, 0)


def get_lead_temperature(score, followup_status, stage):
    stage_name = (stage or "").strip()
    if stage_name == "Converted":
        return "Converted"
    if stage_name == "Lost":
        return "Lost"

    if score is None:
        score = 0
    try:
        numeric_score = int(score)
    except (TypeError, ValueError):
        numeric_score = 0

    if numeric_score >= 75:
        return "Hot"
    if numeric_score >= 40:
        return "Warm"
    return "Cold"


def get_next_action(lead):
    stage = (lead.get("stage") or "").strip()
    followup_status = get_followup_status(lead.get("next_followup_date"))

    if stage == "Converted":
        return "Converted"
    if stage == "Lost":
        return "Closed as lost"
    if followup_status == "overdue":
        return "Call immediately"
    if stage == "New Lead":
        return "Call and qualify"
    if stage == "Contacted":
        return "Understand course interest"
    if stage == "Interested":
        return "Schedule counseling"
    if stage == "Counseling Done":
        return "Discuss fees/parents"
    if stage == "Follow-up":
        return "Complete follow-up"
    return "Review and follow up"


def enrich_lead_for_crm(lead, today=None):
    lead_dict = dict(lead)
    followup_status = get_followup_status(lead_dict.get("next_followup_date"), today=today)
    score = lead_dict.get("lead_score")
    stage = lead_dict.get("stage")

    lead_dict["followup_status"] = followup_status
    lead_dict["inactive_days"] = get_inactive_days(
        lead_dict.get("last_contact_date"),
        lead_dict.get("updated_at"),
        today=today,
    )
    lead_dict["temperature"] = get_lead_temperature(score, followup_status, stage)
    lead_dict["next_action"] = get_next_action(lead_dict)

    return lead_dict


def get_next_stages(current_stage):
    stage_flow = {
        "New Lead": [{"name": "Contacted", "color": "primary"}],
        "Contacted": [{"name": "Interested", "color": "info"}],
        "Interested": [{"name": "Counseling Done", "color": "warning"}],
        "Counseling Done": [{"name": "Follow-up", "color": "secondary"}],
        "Follow-up": [
            {"name": "Converted", "color": "success"},
            {"name": "Lost", "color": "danger"},
        ],
        "Converted": [],
        "Lost": [],
    }
    return stage_flow.get(current_stage, [])


def log_lead_activity(conn, lead_id, user_id, action_type, description):
    cur = conn.cursor()
    cur.execute("SELECT branch_id FROM users WHERE id = ?", (user_id,))
    user_row = cur.fetchone()
    branch_id = user_row["branch_id"] if user_row else None

    log_activity(
        user_id=user_id,
        branch_id=branch_id,
        action_type=action_type,
        module_name="leads",
        record_id=lead_id,
        description=description,
        conn=conn,
    )


def update_lead_stage(conn, lead_id, new_stage, user_id):
    if new_stage not in VALID_STAGES:
        raise ValueError("Invalid stage selected.")

    cur = conn.cursor()
    cur.execute("SELECT id, name, stage, next_followup_date FROM leads WHERE id = ?", (lead_id,))
    lead = cur.fetchone()
    if not lead:
        return None

    old_stage = lead["stage"]
    status = map_stage_to_status(new_stage)
    next_followup_date = None if status in ("converted", "lost") else lead["next_followup_date"]
    now = datetime.now().isoformat(timespec="seconds")

    cur.execute(
        """
        UPDATE leads
        SET stage = ?,
            status = ?,
            next_followup_date = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (new_stage, status, next_followup_date, now, lead_id),
    )

    log_lead_activity(
        conn=conn,
        lead_id=lead_id,
        user_id=user_id,
        action_type="stage_changed",
        description=f"Lead stage changed: {lead['name']} - {old_stage} -> {new_stage}",
    )

    return {
        "old_stage": old_stage,
        "new_stage": new_stage,
        "status": status,
        "updated_at": now,
    }
