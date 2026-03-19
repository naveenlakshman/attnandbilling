from datetime import date, datetime
from flask import Blueprint, render_template, session, flash, redirect, url_for, request
from db import get_conn, log_activity
from modules.core.utils import login_required

leads_bp = Blueprint("leads", __name__)

GENDER_OPTIONS = ["Male", "Female", "Other"]

EDUCATION_OPTIONS = [
    "School Student",
    "PUC Student",
    "Degree Student",
    "Graduate",
    "Job Seeker",
    "Working Professional",
    "Business",
    "Other"
]

STREAM_OPTIONS = [
    "Commerce",
    "Science",
    "Arts",
    "Computer Science",
    "Other"
]

CAREER_GOAL_OPTIONS = [
    "Job",
    "Skill Development",
    "Internship",
    "Business",
    "Career Switch",
    "Other"
]

LEAD_SOURCE_OPTIONS = [
    "Walk-in",
    "Instagram",
    "Facebook",
    "WhatsApp",
    "Referral",
    "Banner",
    "College Campaign",
    "JustDial",
    "Other"
]

DECISION_MAKER_OPTIONS = [
    "Self",
    "Parents",
    "Friends",
    "Spouse",
    "Other"
]

TIMEFRAME_OPTIONS = [
    "Immediately",
    "Within 1 Week",
    "Within 1 Month",
    "Exploring"
]

FOLLOWUP_METHODS = ["Call", "WhatsApp", "Walk-in", "Email"]

FOLLOWUP_OUTCOMES = [
    "Interested",
    "Callback Later",
    "Not Interested",
    "No Response",
    "Joined Elsewhere",
    "Converted"
]

def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return value  # HTML date input already gives YYYY-MM-DD


def compute_lead_score(lead_source, start_timeframe, education_status, career_goal):
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

@leads_bp.route("/")
@login_required
def dashboard():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    month_str = today.strftime("%Y-%m")

    conn = get_conn()
    cur = conn.cursor()

    user_id = session.get("user_id")
    role = session.get("role")

    # Admin sees all leads, staff sees only assigned leads
    assigned_filter_sql = ""
    assigned_params = []

    if role != "admin":
        assigned_filter_sql = " AND assigned_to_id = ? "
        assigned_params.append(user_id)

    # New leads today
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE is_deleted = 0
          AND substr(created_at, 1, 10) = ?
          {assigned_filter_sql}
    """, [today_str] + assigned_params)
    new_leads_today = cur.fetchone()["cnt"]

    # Total leads this month
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE is_deleted = 0
          AND substr(created_at, 1, 7) = ?
          {assigned_filter_sql}
    """, [month_str] + assigned_params)
    total_leads_this_month = cur.fetchone()["cnt"]

    # Followups due
    cur.execute(f"""
        SELECT *
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          AND next_followup_date IS NOT NULL
          AND next_followup_date <= ?
          {assigned_filter_sql}
        ORDER BY next_followup_date ASC
    """, [today_str] + assigned_params)
    followups_due = cur.fetchall()

    # Hot leads
    cur.execute(f"""
        SELECT *
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          AND lead_score >= 60
          {assigned_filter_sql}
        ORDER BY lead_score DESC
        LIMIT 10
    """, assigned_params)
    hot_leads = cur.fetchall()

    # Converted this month
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'converted'
          AND is_deleted = 0
          AND substr(updated_at, 1, 7) = ?
          {assigned_filter_sql}
    """, [month_str] + assigned_params)
    converted_this_month = cur.fetchone()["cnt"]

    # Active totals
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          {assigned_filter_sql}
    """, assigned_params)
    total_active = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          AND substr(created_at, 1, 7) = ?
          {assigned_filter_sql}
    """, [month_str] + assigned_params)
    active_this_month = cur.fetchone()["cnt"]

    # Overall totals
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE is_deleted = 0
          {assigned_filter_sql}
    """, assigned_params)
    total_leads = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'converted'
          AND is_deleted = 0
          {assigned_filter_sql}
    """, assigned_params)
    converted_total = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'lost'
          AND is_deleted = 0
          {assigned_filter_sql}
    """, assigned_params)
    lost_total = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'lost'
          AND is_deleted = 0
          AND substr(updated_at, 1, 7) = ?
          {assigned_filter_sql}
    """, [month_str] + assigned_params)
    lost_this_month = cur.fetchone()["cnt"]

    conversion_rate = round((converted_total / total_leads * 100), 1) if total_leads > 0 else 0

    # Stage breakdown
    cur.execute(f"""
        SELECT stage, COUNT(id) AS cnt
        FROM leads
        WHERE is_deleted = 0
          AND status = 'active'
          {assigned_filter_sql}
        GROUP BY stage
    """, assigned_params)
    stage_breakdown_rows = cur.fetchall()
    stage_breakdown = [(row["stage"], row["cnt"]) for row in stage_breakdown_rows]

    # High-risk leads (old or never contacted)
    cur.execute(f"""
        SELECT *
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          {assigned_filter_sql}
        ORDER BY
            CASE WHEN last_contact_date IS NULL THEN 0 ELSE 1 END,
            last_contact_date ASC
        LIMIT 5
    """, assigned_params)
    high_risk_leads = cur.fetchall()

    # Convert last_contact_date strings to Python date objects for template compatibility
    high_risk_leads_processed = []
    for lead in high_risk_leads:
        lead_dict = dict(lead)
        lcd = lead_dict.get("last_contact_date")
        if lcd:
            try:
                lead_dict["last_contact_date"] = datetime.strptime(lcd, "%Y-%m-%d").date()
            except ValueError:
                lead_dict["last_contact_date"] = None
        else:
            lead_dict["last_contact_date"] = None
        high_risk_leads_processed.append(lead_dict)

    # Team stats for admin
    team_stats = None
    if role == "admin":
        team_stats = []

        cur.execute("""
            SELECT id, full_name, username
            FROM users
            WHERE role = 'staff' AND is_active = 1
            ORDER BY full_name
        """)
        staff_users = cur.fetchall()

        for staff in staff_users:
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM leads
                WHERE assigned_to_id = ?
                  AND is_deleted = 0
            """, (staff["id"],))
            c_total = cur.fetchone()["cnt"]

            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM leads
                WHERE assigned_to_id = ?
                  AND status = 'converted'
                  AND is_deleted = 0
            """, (staff["id"],))
            c_converted = cur.fetchone()["cnt"]

            c_rate = round((c_converted / c_total * 100), 1) if c_total > 0 else 0

            if c_total > 0:
                team_stats.append({
                    "name": staff["full_name"] or staff["username"],
                    "total": c_total,
                    "converted": c_converted,
                    "rate": c_rate
                })

        team_stats.sort(key=lambda x: x["rate"], reverse=True)

    conn.close()

    return render_template(
        "leads/dashboard.html",
        new_leads_today=new_leads_today,
        followups_due=followups_due[:10],
        followups_due_count=len(followups_due),
        hot_leads=hot_leads,
        converted_this_month=converted_this_month,
        total_active=total_active,
        active_this_month=active_this_month,
        total_leads=total_leads,
        total_leads_this_month=total_leads_this_month,
        converted_total=converted_total,
        lost_total=lost_total,
        lost_this_month=lost_this_month,
        conversion_rate=conversion_rate,
        stage_breakdown=stage_breakdown,
        high_risk_leads=high_risk_leads_processed,
        team_stats=team_stats,
        is_admin=(role == "admin"),
        now=today
    )

@leads_bp.route("/new", methods=["GET", "POST"])
@login_required
def lead_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        whatsapp = request.form.get("whatsapp", "").strip() or None
        gender = request.form.get("gender", "").strip() or None
        age = int(request.form.get("age")) if request.form.get("age") else None
        education_status = request.form.get("education_status", "").strip() or None
        stream = request.form.get("stream", "").strip() or None
        institute_name = request.form.get("institute_name", "").strip() or None
        career_goal = request.form.get("career_goal", "").strip() or None
        interested_courses = request.form.get("interested_courses", "").strip() or None
        lead_source = request.form.get("lead_source", "").strip() or None
        decision_maker = request.form.get("decision_maker", "Self").strip() or "Self"
        start_timeframe = request.form.get("start_timeframe", "").strip() or None
        stage = request.form.get("stage", "New Lead").strip() or "New Lead"
        notes = request.form.get("notes", "").strip() or None

        last_contact_date = parse_date(request.form.get("last_contact_date"))
        next_followup_date = parse_date(request.form.get("next_followup_date"))

        lead_score = compute_lead_score(
            lead_source,
            start_timeframe,
            education_status,
            career_goal
        )

        assigned_to_id = session.get("user_id")

        if stage == "Converted":
            status = "converted"
            next_followup_date = None
        elif stage == "Lost":
            status = "lost"
            next_followup_date = None
        else:
            status = "active"

        if not name or not phone:
            flash("Name and Phone are required.", "danger")
            return render_template(
                "leads/lead_form.html",
                lead=None,
                mode="create",
                genders=GENDER_OPTIONS,
                educations=EDUCATION_OPTIONS,
                streams=STREAM_OPTIONS,
                career_goals=CAREER_GOAL_OPTIONS,
                lead_sources=LEAD_SOURCE_OPTIONS,
                decision_makers=DECISION_MAKER_OPTIONS,
                timeframes=TIMEFRAME_OPTIONS,
            )

        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            INSERT INTO leads (
                name,
                phone,
                whatsapp,
                gender,
                age,
                education_status,
                stream,
                institute_name,
                career_goal,
                interested_courses,
                lead_source,
                decision_maker,
                start_timeframe,
                lead_score,
                stage,
                last_contact_date,
                next_followup_date,
                notes,
                status,
                is_deleted,
                assigned_to_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            phone,
            whatsapp,
            gender,
            age,
            education_status,
            stream,
            institute_name,
            career_goal,
            interested_courses,
            lead_source,
            decision_maker,
            start_timeframe,
            lead_score,
            stage,
            last_contact_date,
            next_followup_date,
            notes,
            status,
            0,
            assigned_to_id,
            now,
            now
        ))

        lead_id = cur.lastrowid
        conn.commit()
        conn.close()

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="lead_created",
            module_name="leads",
            record_id=lead_id,
            description=f"Lead created: {name} ({phone}) - Stage: {stage}, Source: {lead_source or 'N/A'}"
        )

        flash("Lead created successfully.", "success")
        return redirect(url_for("leads.dashboard"))

    return render_template(
        "leads/lead_form.html",
        lead=None,
        mode="create",
        genders=GENDER_OPTIONS,
        educations=EDUCATION_OPTIONS,
        streams=STREAM_OPTIONS,
        career_goals=CAREER_GOAL_OPTIONS,
        lead_sources=LEAD_SOURCE_OPTIONS,
        decision_makers=DECISION_MAKER_OPTIONS,
        timeframes=TIMEFRAME_OPTIONS,
    )
@leads_bp.route("/<int:lead_id>")
@login_required
def lead_detail(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    # Lead master data
    cur.execute("""
        SELECT l.*, u.full_name AS assigned_to_name, u.username AS assigned_to_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.id = ? AND l.is_deleted = 0
    """, (lead_id,))
    lead = cur.fetchone()

    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.dashboard"))

    # Active users for reassignment dropdown
    cur.execute("""
        SELECT id, full_name, username
        FROM users
        WHERE is_active = 1
        ORDER BY full_name
    """)
    all_users = cur.fetchall()

    # Followups timeline
    cur.execute("""
        SELECT
            f.*,
            u.username AS user_username,
            u.full_name AS user_full_name
        FROM followups f
        LEFT JOIN users u ON f.user_id = u.id
        WHERE f.lead_id = ?
        ORDER BY f.created_at DESC
    """, (lead_id,))
    followups = cur.fetchall()

    conn.close()

    return render_template(
        "leads/lead_detail.html",
        lead=lead,
        all_users=all_users,
        followups=followups,
        methods=FOLLOWUP_METHODS,
        outcomes=FOLLOWUP_OUTCOMES,
    )
