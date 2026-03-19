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

def get_next_stages(current_stage):
    stage_flow = {
        "New Lead": [{"name": "Contacted", "color": "primary"}],
        "Contacted": [{"name": "Interested", "color": "info"}],
        "Interested": [{"name": "Counseling Done", "color": "warning"}],
        "Counseling Done": [{"name": "Follow-up", "color": "secondary"}],
        "Follow-up": [
            {"name": "Converted", "color": "success"},
            {"name": "Lost", "color": "danger"}
        ],
        "Converted": [],
        "Lost": []
    }
    return stage_flow.get(current_stage, [])

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

@leads_bp.route("/list")
@login_required
def leads_list():
    conn = get_conn()
    cur = conn.cursor()

    q = request.args.get("q", "").strip()
    stage = request.args.get("stage", "").strip()
    source = request.args.get("source", "").strip()
    user_id = request.args.get("user_id", "").strip()

    current_user_id = session.get("user_id")
    current_user_role = session.get("role")

    # Base query
    query = """
        SELECT l.*, u.full_name AS owner_name, u.username AS owner_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.is_deleted = 0
    """
    params = []

    # Role-based filter
    if current_user_role != "admin":
        query += " AND l.assigned_to_id = ?"
        params.append(current_user_id)
    elif user_id:
        query += " AND l.assigned_to_id = ?"
        params.append(user_id)

    # Filters
    if q:
        query += " AND (l.name LIKE ? OR l.phone LIKE ? OR l.whatsapp LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    if stage:
        query += " AND l.stage = ?"
        params.append(stage)

    if source:
        query += " AND l.lead_source = ?"
        params.append(source)

    query += " ORDER BY l.updated_at DESC"

    cur.execute(query, params)
    leads = cur.fetchall()

    # Users (for admin filter dropdown)
    cur.execute("SELECT id, full_name, username FROM users ORDER BY full_name")
    all_users = cur.fetchall()

    # Simple metrics (basic version for now)
    cur.execute("SELECT COUNT(*) FROM leads WHERE is_deleted = 0")
    total = cur.fetchone()[0]

    metrics = {
        "total_overall": total,
        "total_this_month": total,
        "active_overall": total,
        "active_this_month": total,
        "converted_overall": 0,
        "converted_this_month": 0,
        "lost_overall": 0,
        "lost_this_month": 0,
    }

    conn.close()

    stages = ["New Lead", "Contacted", "Interested", "Counseling Done", "Follow-up", "Converted", "Lost"]
    sources = ["Walk-in", "Instagram", "Reference", "Website"]

    return render_template(
        "leads/leads_list.html",
        leads=leads,
        q=q,
        stage=stage,
        source=source,
        stages=stages,
        sources=sources,
        all_users=all_users,
        selected_user_id=user_id,
        is_admin=(current_user_role == "admin"),
        metrics=metrics
    )

@leads_bp.route("/<int:lead_id>/followups/new", methods=["POST"])
@login_required
def followup_add(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    # Check lead exists
    cur.execute("""
        SELECT *
        FROM leads
        WHERE id = ? AND is_deleted = 0
    """, (lead_id,))
    lead = cur.fetchone()

    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))

    method = request.form.get("method", "").strip() or None
    outcome = request.form.get("outcome", "").strip() or None
    note = request.form.get("note", "").strip() or None
    next_dt = parse_date(request.form.get("next_followup_date"))

    now = datetime.now().isoformat(timespec="seconds")
    today_str = date.today().strftime("%Y-%m-%d")

    # Insert follow-up
    cur.execute("""
        INSERT INTO followups (
            lead_id,
            user_id,
            method,
            outcome,
            note,
            next_followup_date,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_id,
        session.get("user_id"),
        method,
        outcome,
        note,
        next_dt,
        now
    ))

    # Lead updates
    current_followup_count = lead["followup_count"] or 0
    current_stage = lead["stage"] or "New Lead"

    new_stage = current_stage
    if current_stage == "New Lead":
        new_stage = "Contacted"

    cur.execute("""
        UPDATE leads
        SET last_contact_date = ?,
            followup_count = ?,
            next_followup_date = ?,
            stage = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        today_str,
        current_followup_count + 1,
        next_dt,
        new_stage,
        now,
        lead_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        user_id=session.get("user_id"),
        branch_id=session.get("branch_id"),
        action_type="followup_added",
        module_name="leads",
        record_id=lead_id,
        description=f"Follow-up added for {lead['name']} - Method: {method or 'Not specified'}, Outcome: {outcome or 'Not specified'}"
    )

    flash("Follow-up saved.", "success")
    return redirect(url_for("leads.lead_detail", lead_id=lead_id))

@leads_bp.route("/<int:lead_id>/edit", methods=["GET", "POST"])
@login_required
def lead_edit(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM leads
        WHERE id = ? AND is_deleted = 0
    """, (lead_id,))
    lead = cur.fetchone()

    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))

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

        stage = request.form.get("stage", lead["stage"]).strip() or lead["stage"]
        notes = request.form.get("notes", "").strip() or None

        last_contact_date = parse_date(request.form.get("last_contact_date"))
        next_followup_date = parse_date(request.form.get("next_followup_date"))

        lead_score = compute_lead_score(
            lead_source,
            start_timeframe,
            education_status,
            career_goal
        )

        if stage == "Converted":
            status = "converted"
            next_followup_date = None
        elif stage == "Lost":
            status = "lost"
            next_followup_date = None
        else:
            status = "active"

        if not name or not phone:
            conn.close()
            flash("Name and Phone are required.", "danger")
            return render_template(
                "leads/lead_form.html",
                lead=lead,
                mode="edit",
                genders=GENDER_OPTIONS,
                educations=EDUCATION_OPTIONS,
                streams=STREAM_OPTIONS,
                career_goals=CAREER_GOAL_OPTIONS,
                lead_sources=LEAD_SOURCE_OPTIONS,
                decision_makers=DECISION_MAKER_OPTIONS,
                timeframes=TIMEFRAME_OPTIONS,
            )

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            UPDATE leads
            SET name = ?,
                phone = ?,
                whatsapp = ?,
                gender = ?,
                age = ?,
                education_status = ?,
                stream = ?,
                institute_name = ?,
                career_goal = ?,
                interested_courses = ?,
                lead_source = ?,
                decision_maker = ?,
                start_timeframe = ?,
                stage = ?,
                notes = ?,
                last_contact_date = ?,
                next_followup_date = ?,
                lead_score = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
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
            stage,
            notes,
            last_contact_date,
            next_followup_date,
            lead_score,
            status,
            now,
            lead_id
        ))

        conn.commit()
        conn.close()

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="lead_edited",
            module_name="leads",
            record_id=lead_id,
            description=f"Lead updated: {name} - Current Stage: {stage}"
        )

        flash("Lead updated.", "success")
        return redirect(url_for("leads.lead_detail", lead_id=lead_id))

    conn.close()

    return render_template(
        "leads/lead_form.html",
        lead=lead,
        mode="edit",
        genders=GENDER_OPTIONS,
        educations=EDUCATION_OPTIONS,
        streams=STREAM_OPTIONS,
        career_goals=CAREER_GOAL_OPTIONS,
        lead_sources=LEAD_SOURCE_OPTIONS,
        decision_makers=DECISION_MAKER_OPTIONS,
        timeframes=TIMEFRAME_OPTIONS,
    )

@leads_bp.route("/<int:lead_id>/stage", methods=["POST"])
@login_required
def lead_set_stage(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM leads
        WHERE id = ? AND is_deleted = 0
    """, (lead_id,))
    lead = cur.fetchone()

    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))

    st = request.form.get("stage", "").strip()

    valid_stages = [
        "New Lead",
        "Contacted",
        "Interested",
        "Counseling Done",
        "Follow-up",
        "Converted",
        "Lost"
    ]

    if st not in valid_stages:
        conn.close()
        flash("Invalid stage selected.", "danger")
        return redirect(request.referrer or url_for("leads.dashboard"))

    old_stage = lead["stage"]

    if st == "Converted":
        status = "converted"
        next_followup_date = None
    elif st == "Lost":
        status = "lost"
        next_followup_date = None
    else:
        status = "active"
        next_followup_date = lead["next_followup_date"]

    now = datetime.now().isoformat(timespec="seconds")

    cur.execute("""
        UPDATE leads
        SET stage = ?,
            status = ?,
            next_followup_date = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        st,
        status,
        next_followup_date,
        now,
        lead_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        user_id=session.get("user_id"),
        branch_id=session.get("branch_id"),
        action_type="stage_changed",
        module_name="leads",
        record_id=lead_id,
        description=f"Lead stage changed: {lead['name']} - {old_stage} → {st}"
    )

    flash("Lead stage updated.", "success")
    return redirect(request.referrer or url_for("leads.dashboard"))

@leads_bp.route("/<int:lead_id>/reassign", methods=["POST"])
@login_required
def lead_reassign(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    # Check lead exists
    cur.execute("""
        SELECT *
        FROM leads
        WHERE id = ? AND is_deleted = 0
    """, (lead_id,))
    lead = cur.fetchone()

    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))

    assigned_to_id = request.form.get("assigned_to_id", "").strip() or None
    now = datetime.now().isoformat(timespec="seconds")

    if assigned_to_id:
        # Verify user exists and is active
        cur.execute("""
            SELECT id, full_name, username, is_active
            FROM users
            WHERE id = ?
        """, (assigned_to_id,))
        user = cur.fetchone()

        if not user or user["is_active"] != 1:
            conn.close()
            flash("Invalid user selected.", "danger")
            return redirect(url_for("leads.lead_detail", lead_id=lead_id))

        cur.execute("""
            UPDATE leads
            SET assigned_to_id = ?, updated_at = ?
            WHERE id = ?
        """, (assigned_to_id, now, lead_id))

        conn.commit()
        conn.close()

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="lead_reassigned",
            module_name="leads",
            record_id=lead_id,
            description=f"Lead reassigned: {lead['name']} → {user['full_name'] or user['username']}"
        )

        flash(f"Lead reassigned to {user['full_name'] or user['username']}.", "success")

    else:
        cur.execute("""
            UPDATE leads
            SET assigned_to_id = NULL, updated_at = ?
            WHERE id = ?
        """, (now, lead_id))

        conn.commit()
        conn.close()

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="lead_unassigned",
            module_name="leads",
            record_id=lead_id,
            description=f"Lead unassigned: {lead['name']}"
        )

        flash("Lead unassigned.", "info")

    return redirect(url_for("leads.lead_detail", lead_id=lead_id))

@leads_bp.route("/followups")
@login_required
def followups_today():
    conn = get_conn()
    cur = conn.cursor()

    today = date.today().strftime("%Y-%m-%d")
    current_user_id = session.get("user_id")
    current_user_role = session.get("role")
    user_filter = request.args.get("user_id", "").strip()

    query = """
        SELECT
            l.*,
            u.full_name AS owner_name,
            u.username AS owner_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.status = 'active'
          AND l.is_deleted = 0
          AND l.next_followup_date IS NOT NULL
          AND l.next_followup_date <= ?
    """
    params = [today]

    # Counselors see only their own leads
    if current_user_role != "admin":
        query += " AND l.assigned_to_id = ?"
        params.append(current_user_id)

    # Admin can filter by selected user
    elif user_filter:
        try:
            query += " AND l.assigned_to_id = ?"
            params.append(int(user_filter))
        except (ValueError, TypeError):
            pass

    query += " ORDER BY l.next_followup_date ASC"

    cur.execute(query, params)
    leads = cur.fetchall()

    # Admin dropdown users
    if current_user_role == "admin":
        cur.execute("""
            SELECT id, full_name, username
            FROM users
            WHERE is_active = 1
            ORDER BY full_name
        """)
        all_users = cur.fetchall()
    else:
        all_users = []

    conn.close()

    return render_template(
        "leads/followups.html",
        leads=leads,
        today=today,
        all_users=all_users,
        selected_user_id=user_filter,
        is_admin=(current_user_role == "admin")
    )
@leads_bp.route("/pipeline")
@login_required
def pipeline():
    stages = ["New Lead", "Contacted", "Interested", "Counseling Done", "Follow-up", "Converted", "Lost"]

    conn = get_conn()
    cur = conn.cursor()

    selected_user_id = request.args.get("user_id", "").strip()
    current_user_id = session.get("user_id")
    current_user_role = session.get("role")

    # Users for admin filter
    if current_user_role == "admin":
        cur.execute("""
            SELECT id, full_name, username
            FROM users
            ORDER BY full_name
        """)
        all_users = cur.fetchall()
    else:
        all_users = []

    data = {}

    for st in stages:
        query = """
            SELECT
                l.*,
                u.full_name AS owner_name,
                u.username AS owner_username
            FROM leads l
            LEFT JOIN users u ON l.assigned_to_id = u.id
            WHERE l.is_deleted = 0
              AND l.stage = ?
        """
        params = [st]

        if current_user_role != "admin":
            query += " AND l.assigned_to_id = ?"
            params.append(current_user_id)
        elif selected_user_id:
            try:
                query += " AND l.assigned_to_id = ?"
                params.append(int(selected_user_id))
            except (ValueError, TypeError):
                pass

        query += " ORDER BY l.updated_at DESC LIMIT 50"

        cur.execute(query, params)
        rows = cur.fetchall()

        processed_rows = []
        for row in rows:
            row_dict = dict(row)
            lcd = row_dict.get("last_contact_date")
            if lcd:
                try:
                    row_dict["last_contact_date_obj"] = datetime.strptime(lcd, "%Y-%m-%d").date()
                except ValueError:
                    row_dict["last_contact_date_obj"] = None
            else:
                row_dict["last_contact_date_obj"] = None
            processed_rows.append(row_dict)

        data[st] = processed_rows

    conn.close()

    return render_template(
        "leads/pipeline.html",
        stages=stages,
        data=data,
        get_next_stages=get_next_stages,
        is_admin=(current_user_role == "admin"),
        all_users=all_users,
        selected_user_id=selected_user_id if selected_user_id else None
    )