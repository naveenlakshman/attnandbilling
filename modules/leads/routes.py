from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, session, flash, redirect, url_for, request, jsonify
from db import get_conn, log_activity
from modules.core.utils import login_required
from modules.leads import ai_helper
from modules.leads import services as lead_services
from modules.leads.helpers import get_lead_or_404_with_access

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
    "Call Later",
    "Parent Discussion Pending",
    "Fees Concern",
    "Visited",
    "Not Interested",
    "No Response",
    "Joined Elsewhere",
    "Converted"
]

PARENT_DISCUSSION_STATUS_OPTIONS = [
    "Pending",
    "Not Required",
    "Scheduled",
    "Completed",
    "Parent Not Responding",
    "Parent Rejected",
]

VISIT_STATUS_OPTIONS = [
    "Not Visited",
    "Visit Scheduled",
    "Visited",
    "Demo Attended",
    "Not Interested After Visit",
]

LOST_REASONS = [
    "Fees High",
    "Joined Other Institute",
    "Parent Rejected",
    "No Response",
    "Course Not Required",
    "Timing Issue",
    "Location Issue",
    "Not Eligible",
    "Duplicate Lead",
    "Other",
]

def get_next_stages(current_stage):
    return lead_services.get_next_stages(current_stage)

def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return value  # HTML date input already gives YYYY-MM-DD


def _to_int_or_none(value):
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def _load_active_branches():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, branch_name, branch_code
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def _get_branch_form_access():
    role = (session.get("role") or "").strip().lower()
    can_view_all = int(session.get("can_view_all_branches", 0) or 0)
    can_select_branch = role == "admin" or can_view_all == 1
    session_branch_id = _to_int_or_none(session.get("branch_id"))
    return can_select_branch, session_branch_id


def compute_lead_score(lead_source, start_timeframe, education_status, career_goal):
    return lead_services.compute_lead_score({
        "lead_source": lead_source,
        "start_timeframe": start_timeframe,
        "education_status": education_status,
        "career_goal": career_goal,
    })

@leads_bp.route("/")
@login_required
def dashboard():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    month_str = today.strftime("%Y-%m")
    inactive_cutoff = (today - timedelta(days=7)).strftime("%Y-%m-%d")

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
        SELECT l.*, u.full_name AS owner_name, u.username AS owner_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.status = 'active'
          AND l.is_deleted = 0
          AND l.next_followup_date IS NOT NULL
          AND l.next_followup_date <= ?
          {assigned_filter_sql}
        ORDER BY l.next_followup_date ASC, l.lead_score DESC
        LIMIT 50
    """, [today_str] + assigned_params)
    followups_due = [lead_services.enrich_lead_for_crm(row, today=today) for row in cur.fetchall()]
    overdue_followups = [l for l in followups_due if l.get("followup_status") == "overdue"]
    today_followups = [l for l in followups_due if l.get("followup_status") == "today"]

    # Hot leads
    cur.execute(f"""
        SELECT l.*, u.full_name AS owner_name, u.username AS owner_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.status = 'active'
          AND l.is_deleted = 0
          AND l.lead_score >= 60
          {assigned_filter_sql}
        ORDER BY l.lead_score DESC, l.updated_at DESC
        LIMIT 25
    """, assigned_params)
    hot_leads_all = [lead_services.enrich_lead_for_crm(row, today=today) for row in cur.fetchall()]
    hot_leads = hot_leads_all[:10]

    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          AND (last_contact_date IS NULL OR last_contact_date = '' OR last_contact_date < ?)
          {assigned_filter_sql}
    """, [inactive_cutoff] + assigned_params)
    inactive_leads_count = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT l.*, u.full_name AS owner_name, u.username AS owner_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.is_deleted = 0
          AND substr(l.created_at, 1, 10) = ?
          AND (l.last_contact_date IS NULL OR l.last_contact_date = '')
          {assigned_filter_sql}
        ORDER BY l.created_at DESC
        LIMIT 5
    """, [today_str] + assigned_params)
    new_not_contacted = [lead_services.enrich_lead_for_crm(row, today=today) for row in cur.fetchall()]

    # Converted this month (prefer conversion_date, fall back to updated_at)
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE status = 'converted'
          AND is_deleted = 0
          AND substr(COALESCE(conversion_date, updated_at), 1, 7) = ?
          {assigned_filter_sql}
    """, [month_str] + assigned_params)
    converted_this_month = cur.fetchone()["cnt"]

    # Parent discussion pending (active leads)
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE is_deleted = 0
          AND status = 'active'
          AND parent_discussion_status = 'Pending'
          {assigned_filter_sql}
    """, assigned_params)
    parent_pending_count = cur.fetchone()["cnt"]

    # Visit scheduled
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE is_deleted = 0
          AND status = 'active'
          AND visit_status = 'Visit Scheduled'
          {assigned_filter_sql}
    """, assigned_params)
    visit_scheduled_count = cur.fetchone()["cnt"]

    # Visited but not converted
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads
        WHERE is_deleted = 0
          AND status = 'active'
          AND visit_status IN ('Visited', 'Demo Attended')
          {assigned_filter_sql}
    """, assigned_params)
    visited_not_converted_count = cur.fetchone()["cnt"]

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
    high_risk_leads = [lead_services.enrich_lead_for_crm(row, today=today) for row in cur.fetchall()]

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
        overdue_followups=overdue_followups,
        overdue_followups_count=len(overdue_followups),
        today_followups=today_followups,
        today_followups_count=len(today_followups),
        top_overdue_followups=overdue_followups[:5],
        top_hot_leads=hot_leads_all[:5],
        new_not_contacted=new_not_contacted,
        hot_leads_count=len(hot_leads_all),
        inactive_leads_count=inactive_leads_count,
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
        now=today,
        parent_pending_count=parent_pending_count,
        visit_scheduled_count=visit_scheduled_count,
        visited_not_converted_count=visited_not_converted_count,
    )

@leads_bp.route("/new", methods=["GET", "POST"])
@login_required
def lead_create():
    can_select_branch, session_branch_id = _get_branch_form_access()

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
        lead_location = request.form.get("lead_location", "").strip() or None
        start_timeframe = request.form.get("start_timeframe", "").strip() or None
        stage = request.form.get("stage", "New Lead").strip() or "New Lead"
        parent_discussion_status = request.form.get("parent_discussion_status", "Pending").strip() or "Pending"
        visit_status = request.form.get("visit_status", "Not Visited").strip() or "Not Visited"
        notes = request.form.get("notes", "").strip() or None

        form_branch_id = _to_int_or_none(request.form.get("branch_id"))
        if can_select_branch:
            branch_id = form_branch_id
        else:
            branch_id = session_branch_id

        last_contact_date = parse_date(request.form.get("last_contact_date"))
        next_followup_date = parse_date(request.form.get("next_followup_date"))

        lead_score = lead_services.compute_lead_score({
            "lead_source": lead_source,
            "start_timeframe": start_timeframe,
            "education_status": education_status,
            "career_goal": career_goal,
        })

        assigned_to_id = session.get("user_id")

        status = lead_services.map_stage_to_status(stage)
        if status in ("converted", "lost"):
            next_followup_date = None

        _phone_digits = ''.join(filter(str.isdigit, phone))
        _wa_digits = ''.join(filter(str.isdigit, whatsapp or ''))
        _phone_error = None
        if not name or not phone:
            _phone_error = "Name and Phone are required."
        elif len(_phone_digits) != 10 or _phone_digits[0] not in '6789':
            _phone_error = "Phone must be a valid 10-digit Indian mobile number (starting with 6, 7, 8, or 9)."
        elif not whatsapp:
            _phone_error = "WhatsApp number is required and must be a valid 10-digit Indian mobile number."
        elif len(_wa_digits) != 10 or _wa_digits[0] not in '6789':
            _phone_error = "WhatsApp must be a valid 10-digit Indian mobile number (starting with 6, 7, 8, or 9)."
        if _phone_error:
            _conn2 = get_conn()
            _cur2 = _conn2.cursor()
            _cur2.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name")
            _active_courses = _cur2.fetchall()
            _conn2.close()
            flash(_phone_error, "danger")
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
                active_courses=_active_courses,
                parent_discussion_status_options=PARENT_DISCUSSION_STATUS_OPTIONS,
                visit_status_options=VISIT_STATUS_OPTIONS,
                branches=_load_active_branches(),
                can_select_branch=can_select_branch,
                session_branch_id=session_branch_id,
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
                branch_id,
                parent_discussion_status,
                visit_status,
                lead_location,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            branch_id,
            parent_discussion_status,
            visit_status,
            lead_location,
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

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name")
    active_courses = cur.fetchall()
    conn.close()

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
        active_courses=active_courses,
        parent_discussion_status_options=PARENT_DISCUSSION_STATUS_OPTIONS,
        visit_status_options=VISIT_STATUS_OPTIONS,
        branches=_load_active_branches(),
        can_select_branch=can_select_branch,
        session_branch_id=session_branch_id,
    )
@leads_bp.route("/<int:lead_id>")
@login_required
def lead_detail(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    _, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.dashboard"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        return redirect(url_for("leads.dashboard"))

    # Lead master data
    cur.execute("""
        SELECT
            l.*, 
            u.full_name AS assigned_to_name,
            u.username AS assigned_to_username,
            b.branch_name AS branch_name,
            b.branch_code AS branch_code
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        LEFT JOIN branches b ON l.branch_id = b.id
        WHERE l.id = ?
    """, (lead_id,))
    lead = cur.fetchone()

    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.dashboard"))

    lead = lead_services.enrich_lead_for_crm(lead)
    if lead.get("branch_id") and not lead.get("branch_name"):
        lead["branch_name"] = f"Branch #{lead.get('branch_id')}"

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

    cur.execute("""
        SELECT
            al.*,
            u.username AS user_username,
            u.full_name AS user_full_name
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        WHERE al.module_name = 'leads'
          AND al.record_id = ?
        ORDER BY al.created_at DESC
        LIMIT 100
    """, (lead_id,))
    activity_items = cur.fetchall()

    timeline_items = []
    for f in followups:
        f_dict = dict(f)
        timeline_items.append({
            "kind": "followup",
            "created_at": f_dict.get("created_at"),
            "actor": f_dict.get("user_full_name") or f_dict.get("user_username"),
            "title": (f_dict.get("method") or "Follow-up") + (f" · {f_dict.get('outcome')}" if f_dict.get("outcome") else ""),
            "note": f_dict.get("note"),
            "next_followup_date": f_dict.get("next_followup_date"),
        })

    for a in activity_items:
        a_dict = dict(a)
        timeline_items.append({
            "kind": "activity",
            "created_at": a_dict.get("created_at"),
            "actor": a_dict.get("user_full_name") or a_dict.get("user_username"),
            "title": a_dict.get("action_type") or "Activity",
            "note": a_dict.get("description"),
            "next_followup_date": None,
        })

    timeline_items.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    # Linked student (if this lead was converted)
    cur.execute(
        "SELECT id, student_code, full_name FROM students WHERE lead_id = ?",
        (lead_id,)
    )
    linked_student = cur.fetchone()

    alerts = []
    parent_status = (lead.get("parent_discussion_status") or "").strip()
    visit_status = (lead.get("visit_status") or "").strip()
    lead_stage = (lead.get("stage") or "").strip()
    lead_status = (lead.get("status") or "").strip()

    is_closed = lead_status in ("converted", "lost")

    if not is_closed:
        if lead.get("followup_status") == "overdue":
            alerts.append({"type": "danger", "text": "Follow-up is overdue. Call immediately."})
        elif lead.get("followup_status") == "today":
            alerts.append({"type": "warning", "text": "Follow-up is due today."})

        if lead.get("inactive_days") is not None and lead.get("inactive_days") >= 7:
            alerts.append({"type": "warning", "text": f"No contact for {lead.get('inactive_days')} days."})

        if not lead.get("last_contact_date"):
            alerts.append({"type": "info", "text": "This lead has never been contacted."})

        if parent_status == "Pending":
            alerts.append({"type": "warning", "text": "Parent discussion pending."})

        if visit_status == "Visited":
            alerts.append({"type": "warning", "text": "Visited but not converted yet."})
        elif visit_status == "Visit Scheduled":
            alerts.append({"type": "info", "text": "Visit scheduled - follow up after visit."})

    if lead_stage == "Lost" and lead.get("lost_reason"):
        alerts.append({"type": "danger", "text": f"Lost reason: {lead.get('lost_reason')}"})

    conn.close()

    return render_template(
        "leads/lead_detail.html",
        lead=lead,
        all_users=all_users,
        followups=followups,
        timeline_items=timeline_items,
        alerts=alerts,
        methods=FOLLOWUP_METHODS,
        outcomes=FOLLOWUP_OUTCOMES,
        linked_student=linked_student,
        lost_reasons=LOST_REASONS,
    )

@leads_bp.route("/list")
@login_required
def leads_list():
    conn = get_conn()
    cur = conn.cursor()
    today_str = date.today().strftime("%Y-%m-%d")

    q = request.args.get("q", "").strip()
    stage = request.args.get("stage", "").strip()
    source = request.args.get("source", "").strip()
    user_id = request.args.get("user_id", "").strip()
    my_leads = request.args.get("my_leads", "").strip()
    temperature = request.args.get("temperature", "").strip()
    course = request.args.get("course", "").strip()
    followup_due = request.args.get("followup_due", "").strip()
    status_filter = request.args.get("status_filter", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    hide_converted = request.args.get("hide_converted", "").strip()
    filter_branch_id = request.args.get("branch_id", "").strip()
    parent_discussion_status = request.args.get("parent_discussion_status", "").strip()
    visit_status = request.args.get("visit_status", "").strip()
    lost_reason_filter = request.args.get("lost_reason", "").strip()

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
    elif my_leads == "1":
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

    if course:
        query += " AND l.interested_courses = ?"
        params.append(course)

    if status_filter in ("active", "converted", "lost"):
        query += " AND l.status = ?"
        params.append(status_filter)

    if followup_due == "overdue":
        query += " AND l.status = 'active' AND l.next_followup_date IS NOT NULL AND l.next_followup_date < ?"
        params.append(today_str)
    elif followup_due == "today":
        query += " AND l.status = 'active' AND l.next_followup_date = ?"
        params.append(today_str)

    if date_from:
        query += " AND substr(l.created_at, 1, 10) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND substr(l.created_at, 1, 10) <= ?"
        params.append(date_to)
    if hide_converted == "1":
        query += " AND l.status NOT IN ('converted', 'lost')"

    if filter_branch_id and current_user_role == "admin":
        query += " AND l.branch_id = ?"
        params.append(filter_branch_id)

    if parent_discussion_status:
        query += " AND l.parent_discussion_status = ?"
        params.append(parent_discussion_status)

    if visit_status:
        query += " AND l.visit_status = ?"
        params.append(visit_status)

    if lost_reason_filter:
        query += " AND l.lost_reason = ?"
        params.append(lost_reason_filter)

    query += " ORDER BY l.updated_at DESC"

    cur.execute(query, params)
    leads = [lead_services.enrich_lead_for_crm(row) for row in cur.fetchall()]

    if temperature in ("Hot", "Warm", "Cold", "Converted", "Lost"):
        leads = [lead for lead in leads if lead.get("temperature") == temperature]

    # Users (for admin filter dropdown)
    cur.execute("SELECT id, full_name, username FROM users ORDER BY full_name")
    all_users = cur.fetchall()

    # Calculate metrics with role-aware scope
    today = date.today()
    month_str = today.strftime("%Y-%m")

    metrics_filter_sql = ""
    metrics_params = []
    if current_user_role != "admin" or my_leads == "1":
        metrics_filter_sql = " AND assigned_to_id = ?"
        metrics_params.append(current_user_id)
    elif user_id:
        metrics_filter_sql = " AND assigned_to_id = ?"
        metrics_params.append(user_id)

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 {metrics_filter_sql}", metrics_params)
    total_overall = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND substr(created_at, 1, 7) = ? {metrics_filter_sql}", (month_str, *metrics_params))
    total_this_month = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'active' {metrics_filter_sql}", metrics_params)
    active_overall = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'active' AND substr(created_at, 1, 7) = ? {metrics_filter_sql}", (month_str, *metrics_params))
    active_this_month = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'converted' {metrics_filter_sql}", metrics_params)
    converted_overall = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'converted' AND substr(updated_at, 1, 7) = ? {metrics_filter_sql}", (month_str, *metrics_params))
    converted_this_month = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'lost' {metrics_filter_sql}", metrics_params)
    lost_overall = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'lost' AND substr(updated_at, 1, 7) = ? {metrics_filter_sql}", (month_str, *metrics_params))
    lost_this_month = cur.fetchone()[0]

    cur.execute("""
        SELECT DISTINCT interested_courses
        FROM leads
        WHERE is_deleted = 0
          AND interested_courses IS NOT NULL
          AND TRIM(interested_courses) != ''
        ORDER BY interested_courses
    """)
    course_options = [row["interested_courses"] for row in cur.fetchall()]

    cur.execute("""
        SELECT DISTINCT lost_reason
        FROM leads
        WHERE is_deleted = 0
          AND lost_reason IS NOT NULL
          AND TRIM(lost_reason) != ''
        ORDER BY lost_reason
    """)
    lost_reason_options = [row["lost_reason"] for row in cur.fetchall()]

    branch_options = _load_active_branches() if current_user_role == "admin" else []

    metrics = {
        "total_overall": total_overall,
        "total_this_month": total_this_month,
        "active_overall": active_overall,
        "active_this_month": active_this_month,
        "converted_overall": converted_overall,
        "converted_this_month": converted_this_month,
        "lost_overall": lost_overall,
        "lost_this_month": lost_this_month,
    }

    conn.close()

    stages = ["New Lead", "Contacted", "Interested", "Counseling Done", "Follow-up", "Converted", "Lost"]
    sources = ["Walk-in", "Instagram", "Facebook", "WhatsApp", "Referral", "Banner", "College Campaign", "JustDial", "Other"]

    return render_template(
        "leads/leads_list.html",
        leads=leads,
        q=q,
        stage=stage,
        source=source,
        course=course,
        my_leads=my_leads,
        followup_due=followup_due,
        status_filter=status_filter,
        temperature=temperature,
        date_from=date_from,
        date_to=date_to,
        hide_converted=hide_converted,
        filter_branch_id=filter_branch_id,
        parent_discussion_status=parent_discussion_status,
        visit_status=visit_status,
        lost_reason_filter=lost_reason_filter,
        stages=stages,
        sources=sources,
        course_options=course_options,
        lost_reason_options=lost_reason_options,
        branch_options=branch_options,
        all_users=all_users,
        selected_user_id=user_id,
        is_admin=(current_user_role == "admin"),
        metrics=metrics,
        parent_discussion_status_options=PARENT_DISCUSSION_STATUS_OPTIONS,
        visit_status_options=VISIT_STATUS_OPTIONS,
    )

@leads_bp.route("/<int:lead_id>/followups/new", methods=["POST"])
@login_required
def followup_add(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
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

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        return redirect(url_for("leads.leads_list"))

    can_select_branch, session_branch_id = _get_branch_form_access()

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
        lead_location = request.form.get("lead_location", "").strip() or None
        start_timeframe = request.form.get("start_timeframe", "").strip() or None
        parent_discussion_status = request.form.get("parent_discussion_status", "Pending").strip() or "Pending"
        visit_status = request.form.get("visit_status", "Not Visited").strip() or "Not Visited"

        stage = request.form.get("stage", lead["stage"]).strip() or lead["stage"]
        notes = request.form.get("notes", "").strip() or None

        form_branch_id = _to_int_or_none(request.form.get("branch_id"))
        if can_select_branch:
            branch_id = form_branch_id
        else:
            branch_id = session_branch_id

        last_contact_date = parse_date(request.form.get("last_contact_date"))
        next_followup_date = parse_date(request.form.get("next_followup_date"))

        lead_score = lead_services.compute_lead_score({
            "lead_source": lead_source,
            "start_timeframe": start_timeframe,
            "education_status": education_status,
            "career_goal": career_goal,
        })

        status = lead_services.map_stage_to_status(stage)
        if status in ("converted", "lost"):
            next_followup_date = None

        _phone_digits_edit = ''.join(filter(str.isdigit, phone))
        _wa_digits_edit = ''.join(filter(str.isdigit, whatsapp or ''))
        _phone_error_edit = None
        if not name or not phone:
            _phone_error_edit = "Name and Phone are required."
        elif len(_phone_digits_edit) != 10 or _phone_digits_edit[0] not in '6789':
            _phone_error_edit = "Phone must be a valid 10-digit Indian mobile number (starting with 6, 7, 8, or 9)."
        elif not whatsapp:
            _phone_error_edit = "WhatsApp number is required and must be a valid 10-digit Indian mobile number."
        elif len(_wa_digits_edit) != 10 or _wa_digits_edit[0] not in '6789':
            _phone_error_edit = "WhatsApp must be a valid 10-digit Indian mobile number (starting with 6, 7, 8, or 9)."
        if _phone_error_edit:
            _conn3 = get_conn()
            _cur3 = _conn3.cursor()
            _cur3.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name")
            _active_courses_edit = _cur3.fetchall()
            _conn3.close()
            conn.close()
            flash(_phone_error_edit, "danger")
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
                active_courses=_active_courses_edit,
                parent_discussion_status_options=PARENT_DISCUSSION_STATUS_OPTIONS,
                visit_status_options=VISIT_STATUS_OPTIONS,
                branches=_load_active_branches(),
                can_select_branch=can_select_branch,
                session_branch_id=session_branch_id,
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
                branch_id = ?,
                parent_discussion_status = ?,
                visit_status = ?,
                lead_location = ?,
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
            branch_id,
            parent_discussion_status,
            visit_status,
            lead_location,
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

        field_changes = []
        if str(lead.get("parent_discussion_status") or "") != str(parent_discussion_status or ""):
            field_changes.append(
                f"Parent discussion status changed from {lead.get('parent_discussion_status') or 'None'} to {parent_discussion_status or 'None'}"
            )
        if str(lead.get("visit_status") or "") != str(visit_status or ""):
            field_changes.append(
                f"Visit status changed from {lead.get('visit_status') or 'None'} to {visit_status or 'None'}"
            )
        old_branch = _to_int_or_none(lead.get("branch_id"))
        if old_branch != branch_id:
            field_changes.append(f"Lead branch changed from {old_branch or 'None'} to {branch_id or 'None'}")

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="lead_edited",
            module_name="leads",
            record_id=lead_id,
            description=f"Lead updated: {name} - Current Stage: {stage}"
        )

        for msg in field_changes:
            log_activity(
                user_id=session.get("user_id"),
                branch_id=session.get("branch_id"),
                action_type="lead_field_updated",
                module_name="leads",
                record_id=lead_id,
                description=msg,
            )

        flash("Lead updated.", "success")
        return redirect(url_for("leads.lead_detail", lead_id=lead_id))

    cur.execute("SELECT id, course_name FROM courses WHERE is_active = 1 ORDER BY course_name")
    active_courses = cur.fetchall()
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
        active_courses=active_courses,
        parent_discussion_status_options=PARENT_DISCUSSION_STATUS_OPTIONS,
        visit_status_options=VISIT_STATUS_OPTIONS,
        branches=_load_active_branches(),
        can_select_branch=can_select_branch,
        session_branch_id=session_branch_id,
    )

@leads_bp.route("/<int:lead_id>/stage", methods=["POST"])
@login_required
def lead_set_stage(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        return redirect(request.referrer or url_for("leads.dashboard"))

    st = request.form.get("stage", "").strip()

    if st not in lead_services.VALID_STAGES:
        conn.close()
        flash("Invalid stage selected.", "danger")
        return redirect(request.referrer or url_for("leads.dashboard"))

    try:
        update_result = lead_services.update_lead_stage(
            conn=conn,
            lead_id=lead_id,
            new_stage=st,
            user_id=session.get("user_id"),
        )
    except ValueError:
        conn.close()
        flash("Invalid stage selected.", "danger")
        return redirect(request.referrer or url_for("leads.dashboard"))

    if not update_result:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))

    conn.commit()
    conn.close()

    flash("Lead stage updated.", "success")
    return redirect(request.referrer or url_for("leads.dashboard"))

@leads_bp.route("/<int:lead_id>/reassign", methods=["POST"])
@login_required
def lead_reassign(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
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

    today_date = date.today()
    today = today_date.strftime("%Y-%m-%d")
    tomorrow = (today_date + timedelta(days=1)).strftime("%Y-%m-%d")
    current_user_id = session.get("user_id")
    current_user_role = session.get("role")
    user_filter = request.args.get("user_id", "").strip()
    selected_tab = request.args.get("tab", "overdue").strip().lower()
    if selected_tab not in {"overdue", "today", "tomorrow", "upcoming", "completed"}:
        selected_tab = "overdue"

    query = """
        SELECT
            l.*,
            u.full_name AS owner_name,
            u.username AS owner_username,
            (
                SELECT f2.note
                FROM followups f2
                WHERE f2.lead_id = l.id
                ORDER BY f2.created_at DESC
                LIMIT 1
            ) AS last_note
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.status = 'active'
          AND l.is_deleted = 0
          AND l.next_followup_date IS NOT NULL
    """
    params = []

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

    query += " ORDER BY l.next_followup_date ASC, l.lead_score DESC"

    cur.execute(query, params)
    due_leads = [lead_services.enrich_lead_for_crm(row, today=today_date) for row in cur.fetchall()]

    overdue_items = []
    today_items = []
    tomorrow_items = []
    upcoming_items = []

    for lead in due_leads:
        due_date = (lead.get("next_followup_date") or "").strip()
        if not due_date:
            continue
        if due_date < today:
            overdue_items.append(lead)
        elif due_date == today:
            today_items.append(lead)
        elif due_date == tomorrow:
            tomorrow_items.append(lead)
        else:
            upcoming_items.append(lead)

    completed_query = """
        SELECT
            f.id AS followup_id,
            f.lead_id,
            f.method,
            f.outcome,
            f.note,
            f.next_followup_date AS followup_next_followup_date,
            f.created_at AS followup_created_at,
            l.name,
            l.phone,
            l.interested_courses AS course_interested,
            l.stage,
            l.lead_score,
            l.next_followup_date,
            u.full_name AS owner_name,
            u.username AS owner_username
        FROM followups f
        JOIN leads l ON l.id = f.lead_id
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE substr(f.created_at, 1, 10) = ?
          AND l.is_deleted = 0
    """
    completed_params = [today]

    if current_user_role != "admin":
        completed_query += " AND l.assigned_to_id = ?"
        completed_params.append(current_user_id)
    elif user_filter:
        try:
            completed_query += " AND l.assigned_to_id = ?"
            completed_params.append(int(user_filter))
        except (ValueError, TypeError):
            pass

    completed_query += " ORDER BY f.created_at DESC"
    cur.execute(completed_query, completed_params)
    completed_items = []
    for row in cur.fetchall():
        item = dict(row)
        item["temperature"] = lead_services.get_lead_temperature(
            item.get("lead_score"), item.get("followup_status"), item.get("stage")
        )
        completed_items.append(item)

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

    tab_counts = {
        "overdue": len(overdue_items),
        "today": len(today_items),
        "tomorrow": len(tomorrow_items),
        "upcoming": len(upcoming_items),
        "completed": len(completed_items),
    }

    tab_items = {
        "overdue": overdue_items,
        "today": today_items,
        "tomorrow": tomorrow_items,
        "upcoming": upcoming_items,
        "completed": completed_items,
    }

    return render_template(
        "leads/followups.html",
        leads=tab_items[selected_tab],
        tab_items=tab_items,
        tab_counts=tab_counts,
        selected_tab=selected_tab,
        today=today,
        tomorrow=tomorrow,
        all_users=all_users,
        selected_user_id=user_filter,
        is_admin=(current_user_role == "admin"),
        outcomes=[
            "Interested",
            "Call Later",
            "No Response",
            "Parent Discussion Pending",
            "Fees Concern",
            "Visited",
            "Not Interested",
            "Converted",
        ]
    )

@leads_bp.route("/followups/complete", methods=["POST"])
@login_required
def followups_quick_complete():
    lead_id_raw = request.form.get("lead_id", "").strip()
    if not lead_id_raw.isdigit():
        flash("Invalid lead selected.", "danger")
        return redirect(url_for("leads.followups_today"))

    lead_id = int(lead_id_raw)
    tab = request.form.get("tab", "overdue").strip().lower()
    if tab not in {"overdue", "today", "tomorrow", "upcoming", "completed"}:
        tab = "overdue"

    selected_user_id = request.form.get("selected_user_id", "").strip()
    mode = request.form.get("mode", "complete").strip().lower()
    method = request.form.get("method", "Call").strip() or "Call"
    outcome = request.form.get("outcome", "").strip()
    note = request.form.get("note", "").strip()
    next_dt = parse_date(request.form.get("next_followup_date"))
    next_action = request.form.get("next_action", "").strip() or None
    followup_note = note
    if next_action:
        followup_note = (note + "\n" if note else "") + f"Next action: {next_action}"

    if mode == "reschedule" and not next_dt:
        flash("Next follow-up date is required for reschedule.", "danger")
        if selected_user_id:
            return redirect(url_for("leads.followups_today", tab=tab, user_id=selected_user_id))
        return redirect(url_for("leads.followups_today", tab=tab))

    if mode == "reschedule" and not outcome:
        outcome = "Call Later"

    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        if selected_user_id:
            return redirect(url_for("leads.followups_today", tab=tab, user_id=selected_user_id))
        return redirect(url_for("leads.followups_today", tab=tab))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        if selected_user_id:
            return redirect(url_for("leads.followups_today", tab=tab, user_id=selected_user_id))
        return redirect(url_for("leads.followups_today", tab=tab))

    now = datetime.now().isoformat(timespec="seconds")
    today_str = date.today().strftime("%Y-%m-%d")

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
        outcome or None,
        followup_note or None,
        next_dt,
        now
    ))

    current_followup_count = lead["followup_count"] or 0
    current_stage = lead["stage"] or "New Lead"
    new_stage = "Contacted" if current_stage == "New Lead" else current_stage

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

    action_label = "Follow-up rescheduled" if mode == "reschedule" else "Follow-up completed"
    log_activity(
        user_id=session.get("user_id"),
        branch_id=session.get("branch_id"),
        action_type="followup_completed",
        module_name="leads",
        record_id=lead_id,
        description=(
            f"{action_label} for {lead['name']} - Method: {method}, "
            f"Outcome: {outcome or 'Not specified'}, Next: {next_dt or 'Not set'}, "
            f"Next action: {next_action or 'Not specified'}"
        )
    )

    flash(action_label + ".", "success")
    if selected_user_id:
        return redirect(url_for("leads.followups_today", tab=tab, user_id=selected_user_id))
    return redirect(url_for("leads.followups_today", tab=tab))
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
            row_dict = lead_services.enrich_lead_for_crm(row)
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
@leads_bp.route("/reports")
@login_required
def reports():
    if session.get("role") != "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("leads.dashboard"))

    conn = get_conn()
    cur = conn.cursor()

    user_id_filter = request.args.get("user_id", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    # Build WHERE conditions
    where_clauses = ["l.is_deleted = 0"]
    params = []

    if user_id_filter:
        try:
            where_clauses.append("l.assigned_to_id = ?")
            params.append(int(user_id_filter))
        except (ValueError, TypeError):
            user_id_filter = ""

    if date_from:
        try:
            datetime.strptime(date_from, "%Y-%m-%d")
            where_clauses.append("substr(l.created_at, 1, 10) >= ?")
            params.append(date_from)
        except ValueError:
            date_from = ""

    if date_to:
        try:
            datetime.strptime(date_to, "%Y-%m-%d")
            where_clauses.append("substr(l.created_at, 1, 10) <= ?")
            params.append(date_to)
        except ValueError:
            date_to = ""

    where_sql = " AND ".join(where_clauses)

    # Overall KPIs
    cur.execute(f"SELECT COUNT(*) AS cnt FROM leads l WHERE {where_sql}", params)
    total_leads = cur.fetchone()["cnt"]

    cur.execute(f"SELECT COUNT(*) AS cnt FROM leads l WHERE {where_sql} AND l.status = 'active'", params)
    active = cur.fetchone()["cnt"]

    cur.execute(f"SELECT COUNT(*) AS cnt FROM leads l WHERE {where_sql} AND l.status = 'converted'", params)
    converted_total = cur.fetchone()["cnt"]

    cur.execute(f"SELECT COUNT(*) AS cnt FROM leads l WHERE {where_sql} AND l.status = 'lost'", params)
    lost = cur.fetchone()["cnt"]

    conversion_rate = round((converted_total / total_leads * 100), 1) if total_leads > 0 else 0

    # Follow-up completion rate (leads that have at least one followup entry)
    followup_where_parts = [where_sql]
    followup_params = list(params)
    if date_from:
        followup_where_parts.append("substr(f.created_at, 1, 10) >= ?")
        followup_params.append(date_from)
    if date_to:
        followup_where_parts.append("substr(f.created_at, 1, 10) <= ?")
        followup_params.append(date_to)
    followup_where_sql = " AND ".join(followup_where_parts)

    cur.execute(f"""
        SELECT COUNT(DISTINCT f.lead_id) AS cnt
        FROM followups f
        JOIN leads l ON l.id = f.lead_id
        WHERE {followup_where_sql}
    """, followup_params)
    leads_with_followups = cur.fetchone()["cnt"]
    followup_completion_rate = round((leads_with_followups / total_leads * 100), 1) if total_leads > 0 else 0

    # Hot lead conversion rate
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads l
        WHERE {where_sql} AND l.lead_score >= 75
    """, params)
    hot_total = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM leads l
        WHERE {where_sql} AND l.lead_score >= 75 AND l.status = 'converted'
    """, params)
    hot_converted = cur.fetchone()["cnt"]
    hot_lead_conversion_rate = round((hot_converted / hot_total * 100), 1) if hot_total > 0 else 0

    # Average days to conversion (approx using created_at -> updated_at)
    cur.execute(f"""
        SELECT AVG(julianday(l.updated_at) - julianday(l.created_at)) AS avg_days
        FROM leads l
        WHERE {where_sql}
          AND l.status = 'converted'
          AND l.created_at IS NOT NULL
          AND l.updated_at IS NOT NULL
    """, params)
    avg_days_to_conversion_raw = cur.fetchone()["avg_days"]
    avg_days_to_conversion = round(avg_days_to_conversion_raw, 1) if avg_days_to_conversion_raw is not None else None

    # Lead source performance
    cur.execute(f"""
        SELECT
            l.lead_source,
            COUNT(l.id) AS total_count,
            SUM(CASE WHEN l.status = 'converted' THEN 1 ELSE 0 END) AS converted_count
        FROM leads l
        WHERE {where_sql} AND l.lead_source IS NOT NULL
        GROUP BY l.lead_source
    """, params)
    source_query = cur.fetchall()

    source_dict = {
        row["lead_source"]: (row["total_count"], row["converted_count"])
        for row in source_query
    }

    source_rows = []
    for source in LEAD_SOURCE_OPTIONS:
        total, converted = source_dict.get(source, (0, 0))
        conv_rate = round((converted / total * 100), 1) if total > 0 else 0
        source_rows.append((source, total, converted, conv_rate))

    # Course interest performance
    cur.execute(f"""
        SELECT
            l.interested_courses,
            COUNT(l.id) AS total_count,
            SUM(CASE WHEN l.status = 'converted' THEN 1 ELSE 0 END) AS converted_count
        FROM leads l
        WHERE {where_sql}
        GROUP BY l.interested_courses
    """, params)
    raw_course_rows = cur.fetchall()

    course_rows = []
    for row in raw_course_rows:
        course = row["interested_courses"]
        total = row["total_count"]
        converted = row["converted_count"]
        conv_rate = round((converted / total * 100), 1) if total > 0 else 0
        course_rows.append((course, total, converted, conv_rate))

    # Lost reason report
    cur.execute(f"""
        SELECT
            COALESCE(NULLIF(TRIM(l.lost_reason), ''), 'Unknown') AS reason,
            COUNT(*) AS cnt
        FROM leads l
        WHERE {where_sql}
          AND l.status = 'lost'
        GROUP BY COALESCE(NULLIF(TRIM(l.lost_reason), ''), 'Unknown')
        ORDER BY cnt DESC
    """, params)
    lost_reason_rows = cur.fetchall()

    # Monthly conversion trend (use conversion_date, fall back to updated_at)
    trend_where = ["l.is_deleted = 0", "l.status = 'converted'",
                   "COALESCE(l.conversion_date, substr(l.updated_at,1,10)) IS NOT NULL"]
    trend_params = []

    if user_id_filter:
        trend_where.append("l.assigned_to_id = ?")
        trend_params.append(int(user_id_filter))

    if date_from:
        trend_where.append("COALESCE(l.conversion_date, substr(l.updated_at,1,10)) >= ?")
        trend_params.append(date_from)
    if date_to:
        trend_where.append("COALESCE(l.conversion_date, substr(l.updated_at,1,10)) <= ?")
        trend_params.append(date_to)

    trend_where_sql = " AND ".join(trend_where)
    cur.execute(f"""
        SELECT
            substr(COALESCE(l.conversion_date, l.updated_at), 1, 7) AS month,
            COUNT(*) AS converted_count
        FROM leads l
        WHERE {trend_where_sql}
        GROUP BY substr(COALESCE(l.conversion_date, l.updated_at), 1, 7)
        ORDER BY month ASC
    """, trend_params)
    monthly_conversion_rows = cur.fetchall()

    # Branch-wise report
    cur.execute(f"""
        SELECT
            COALESCE(b.branch_name, 'Unassigned') AS branch_name,
            COUNT(l.id) AS total_count,
            SUM(CASE WHEN l.status = 'converted' THEN 1 ELSE 0 END) AS converted_count,
            SUM(CASE WHEN l.status = 'lost' THEN 1 ELSE 0 END) AS lost_count
        FROM leads l
        LEFT JOIN branches b ON l.branch_id = b.id
        WHERE {where_sql}
        GROUP BY COALESCE(b.branch_name, 'Unassigned')
        ORDER BY total_count DESC
    """, params)
    raw_branch_rows = cur.fetchall()
    branch_wise_rows = []
    for row in raw_branch_rows:
        total = row["total_count"]
        converted = row["converted_count"]
        rate = round((converted / total * 100), 1) if total > 0 else 0
        branch_wise_rows.append({
            "branch_name": row["branch_name"],
            "total": total,
            "converted": converted,
            "lost": row["lost_count"],
            "rate": rate,
        })

    # Parent discussion status report
    cur.execute(f"""
        SELECT
            COALESCE(NULLIF(TRIM(l.parent_discussion_status), ''), 'Unknown') AS status_label,
            COUNT(*) AS cnt,
            SUM(CASE WHEN l.status = 'converted' THEN 1 ELSE 0 END) AS converted_count
        FROM leads l
        WHERE {where_sql}
        GROUP BY status_label
        ORDER BY cnt DESC
    """, params)
    parent_discussion_rows = cur.fetchall()

    # Visit status conversion report
    cur.execute(f"""
        SELECT
            COALESCE(NULLIF(TRIM(l.visit_status), ''), 'Unknown') AS status_label,
            COUNT(*) AS cnt,
            SUM(CASE WHEN l.status = 'converted' THEN 1 ELSE 0 END) AS converted_count
        FROM leads l
        WHERE {where_sql}
        GROUP BY status_label
        ORDER BY cnt DESC
    """, params)
    visit_status_rows = cur.fetchall()

    # Users dropdown
    cur.execute("""
        SELECT id, full_name, username, is_active
        FROM users
        ORDER BY full_name
    """)
    all_users = cur.fetchall()

    # User stats only when no specific user filter is selected
    user_stats = []
    if not user_id_filter:
        for user in all_users:
            user_where = ["assigned_to_id = ?", "is_deleted = 0"]
            user_params = [user["id"]]

            if date_from:
                user_where.append("substr(created_at, 1, 10) >= ?")
                user_params.append(date_from)

            if date_to:
                user_where.append("substr(created_at, 1, 10) <= ?")
                user_params.append(date_to)

            user_where_sql = " AND ".join(user_where)

            cur.execute(f"SELECT COUNT(*) AS cnt FROM leads WHERE {user_where_sql}", user_params)
            user_total = cur.fetchone()["cnt"]

            if user_total == 0:
                continue

            cur.execute(f"SELECT COUNT(*) AS cnt FROM leads WHERE {user_where_sql} AND status = 'active'", user_params)
            user_active = cur.fetchone()["cnt"]

            cur.execute(f"SELECT COUNT(*) AS cnt FROM leads WHERE {user_where_sql} AND status = 'converted'", user_params)
            user_converted = cur.fetchone()["cnt"]

            cur.execute(f"SELECT COUNT(*) AS cnt FROM leads WHERE {user_where_sql} AND status = 'lost'", user_params)
            user_lost = cur.fetchone()["cnt"]

            cur.execute(f"SELECT MAX(last_contact_date) AS last_contact FROM leads WHERE {user_where_sql}", user_params)
            last_contact = cur.fetchone()["last_contact"]

            user_conv_rate = round((user_converted / user_total * 100), 1) if user_total > 0 else 0

            cur.execute(f"""
                SELECT stage, COUNT(id) AS cnt
                FROM leads
                WHERE {user_where_sql}
                GROUP BY stage
            """, user_params)
            stage_breakdown_rows = cur.fetchall()
            stage_breakdown = [(r["stage"], r["cnt"]) for r in stage_breakdown_rows]

            # convert date string for template compatibility
            last_contact_obj = None
            if last_contact:
                try:
                    last_contact_obj = datetime.strptime(last_contact, "%Y-%m-%d").date()
                except ValueError:
                    last_contact_obj = None

            user_stats.append({
                "user": user,
                "total": user_total,
                "active": user_active,
                "converted": user_converted,
                "lost": user_lost,
                "conversion_rate": user_conv_rate,
                "last_contact": last_contact_obj,
                "stage_breakdown": stage_breakdown
            })

        user_stats.sort(key=lambda x: x["conversion_rate"], reverse=True)

    conn.close()

    return render_template(
        "leads/reports.html",
        total_leads=total_leads,
        active=active,
        converted=converted_total,
        lost=lost,
        conversion_rate=conversion_rate,
        leads_with_followups=leads_with_followups,
        followup_completion_rate=followup_completion_rate,
        hot_total=hot_total,
        hot_converted=hot_converted,
        hot_lead_conversion_rate=hot_lead_conversion_rate,
        avg_days_to_conversion=avg_days_to_conversion,
        source_rows=source_rows,
        course_rows=course_rows,
        lost_reason_rows=lost_reason_rows,
        monthly_conversion_rows=monthly_conversion_rows,
        branch_wise_rows=branch_wise_rows,
        parent_discussion_rows=parent_discussion_rows,
        visit_status_rows=visit_status_rows,
        all_users=all_users,
        selected_user_id=user_id_filter if user_id_filter else None,
        date_from=date_from,
        date_to=date_to,
        user_stats=user_stats
    )

@leads_bp.route("/activity-log")
@login_required
def activity_log():
    conn = get_conn()
    cur = conn.cursor()

    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    user_id_filter = request.args.get("user_id", "").strip()
    action_type_filter = request.args.get("action_type", "").strip()

    current_user_id = session.get("user_id")
    current_user_role = session.get("role")

    query = """
        SELECT
            al.*,
            u.full_name AS user_full_name,
            u.username AS user_username,
            l.name AS lead_name,
            l.phone AS lead_phone
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        LEFT JOIN leads l ON al.record_id = l.id AND al.module_name = 'leads'
        WHERE al.module_name = 'leads'
    """
    params = []

    # Staff sees only own activities
    if current_user_role != "admin":
        query += " AND al.user_id = ?"
        params.append(current_user_id)
        all_users = []
    else:
        # Admin can filter by user
        if user_id_filter:
            try:
                query += " AND al.user_id = ?"
                params.append(int(user_id_filter))
            except (ValueError, TypeError):
                user_id_filter = ""

        cur.execute("""
            SELECT id, full_name, username
            FROM users
            ORDER BY full_name
        """)
        all_users = cur.fetchall()

    # Date range filter
    if date_from:
        try:
            datetime.strptime(date_from, "%Y-%m-%d")
            query += " AND substr(al.created_at, 1, 10) >= ?"
            params.append(date_from)
        except ValueError:
            date_from = ""

    if date_to:
        try:
            datetime.strptime(date_to, "%Y-%m-%d")
            query += " AND substr(al.created_at, 1, 10) <= ?"
            params.append(date_to)
        except ValueError:
            date_to = ""

    # Action type filter
    if action_type_filter:
        query += " AND al.action_type = ?"
        params.append(action_type_filter)

    query += " ORDER BY al.created_at DESC"

    cur.execute(query, params)
    activities = cur.fetchall()

    # Unique action types for dropdown
    cur.execute("""
        SELECT DISTINCT action_type
        FROM activity_logs
        WHERE module_name = 'leads' AND action_type IS NOT NULL
        ORDER BY action_type
    """)
    all_action_types = [row["action_type"] for row in cur.fetchall()]

    conn.close()

    return render_template(
        "leads/activity_log.html",
        activities=activities,
        all_users=all_users,
        all_action_types=all_action_types,
        date_from=date_from,
        date_to=date_to,
        selected_user_id=user_id_filter if user_id_filter else None,
        selected_action_type=action_type_filter,
        is_admin=(current_user_role == "admin")
    )

@leads_bp.route("/<int:lead_id>/delete", methods=["POST"])
@login_required
def lead_delete(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        return redirect(url_for("leads.leads_list"))

    now = datetime.now().isoformat(timespec="seconds")

    cur.execute("""
        UPDATE leads
        SET is_deleted = 1,
            updated_at = ?
        WHERE id = ?
    """, (now, lead_id))

    conn.commit()
    conn.close()

    log_activity(
        user_id=session.get("user_id"),
        branch_id=session.get("branch_id"),
        action_type="lead_deleted",
        module_name="leads",
        record_id=lead_id,
        description=f"Lead soft deleted: {lead['name']} ({lead['phone']})"
    )

    flash("Lead deleted successfully.", "success")
    return redirect(url_for("leads.leads_list"))

@leads_bp.route("/deleted")
@login_required
def deleted_leads():
    conn = get_conn()
    cur = conn.cursor()

    current_user_id = session.get("user_id")
    current_user_role = session.get("role")

    q = request.args.get("q", "").strip()

    query = """
        SELECT
            l.*,
            u.full_name AS owner_name,
            u.username AS owner_username
        FROM leads l
        LEFT JOIN users u ON l.assigned_to_id = u.id
        WHERE l.is_deleted = 1
    """
    params = []

    # Staff sees only own deleted leads
    if current_user_role != "admin":
        query += " AND l.assigned_to_id = ?"
        params.append(current_user_id)

    if q:
        query += " AND (l.name LIKE ? OR l.phone LIKE ? OR l.whatsapp LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])

    query += " ORDER BY l.updated_at DESC"

    cur.execute(query, params)
    leads = cur.fetchall()

    conn.close()

    return render_template(
        "leads/deleted_leads.html",
        leads=leads,
        q=q,
        is_admin=(current_user_role == "admin")
    )
@leads_bp.route("/<int:lead_id>/restore", methods=["POST"])
@login_required
def lead_restore(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session, include_deleted=True)
    if access_error == "not_found" or (lead and lead["is_deleted"] != 1):
        conn.close()
        flash("Deleted lead not found.", "danger")
        return redirect(url_for("leads.deleted_leads"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        return redirect(url_for("leads.deleted_leads"))

    now = datetime.now().isoformat(timespec="seconds")

    cur.execute("""
        UPDATE leads
        SET is_deleted = 0,
            updated_at = ?
        WHERE id = ?
    """, (now, lead_id))

    conn.commit()
    conn.close()

    log_activity(
        user_id=session.get("user_id"),
        branch_id=session.get("branch_id"),
        action_type="lead_restored",
        module_name="leads",
        record_id=lead_id,
        description=f"Lead restored: {lead['name']} ({lead['phone']})"
    )

    flash("Lead restored successfully.", "success")
    return redirect(url_for("leads.deleted_leads"))

@leads_bp.route("/<int:lead_id>/mark-lost", methods=["POST"])
@login_required
def lead_mark_lost(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.leads_list"))
    if access_error == "forbidden":
        conn.close()
        flash("Access denied for this lead.", "danger")
        return redirect(url_for("leads.lead_detail", lead_id=lead_id))

    lost_reason = request.form.get("lost_reason", "").strip()
    lost_note = request.form.get("lost_note", "").strip()

    if not lost_reason:
        conn.close()
        flash("Please select a lost reason.", "danger")
        return redirect(url_for("leads.lead_detail", lead_id=lead_id))

    if lost_reason not in LOST_REASONS:
        conn.close()
        flash("Invalid lost reason selected.", "danger")
        return redirect(url_for("leads.lead_detail", lead_id=lead_id))

    now = datetime.now().isoformat(timespec="seconds")
    lost_status = lead_services.map_stage_to_status("Lost")

    cur.execute("""
        UPDATE leads
        SET stage = ?,
            status = ?,
            lost_reason = ?,
            next_followup_date = NULL,
            updated_at = ?
        WHERE id = ?
    """, (
        "Lost",
        lost_status,
        lost_reason,
        now,
        lead_id
    ))

    lead_services.log_lead_activity(
        conn=conn,
        lead_id=lead_id,
        user_id=session.get("user_id"),
        action_type="lead_lost",
        description=(
            f"Lead marked as lost: {lead['name']} - Reason: {lost_reason}"
            + (f". Note: {lost_note}" if lost_note else "")
        )
    )

    conn.commit()
    conn.close()

    flash("Lead marked as lost.", "warning")
    return redirect(url_for("leads.lead_detail", lead_id=lead_id))


@leads_bp.route("/<int:lead_id>/ai-assist", methods=["POST"])
@login_required
def ai_assist(lead_id):
    conn = get_conn()
    cur = conn.cursor()

    lead, access_error = get_lead_or_404_with_access(conn, lead_id, session)
    if access_error == "not_found":
        conn.close()
        return jsonify({"error": "Lead not found."}), 404
    if access_error == "forbidden":
        conn.close()
        return jsonify({"error": "Access denied for this lead."}), 403

    cur.execute("""
        SELECT f.*, u.full_name AS user_full_name
        FROM followups f
        LEFT JOIN users u ON f.user_id = u.id
        WHERE f.lead_id = ?
        ORDER BY f.created_at DESC
        LIMIT 10
    """, (lead_id,))
    followups = cur.fetchall()
    conn.close()

    data = request.get_json(silent=True) or {}
    action = data.get("action", "script")

    lead_dict = dict(lead)
    followups_list = [dict(f) for f in followups]

    try:
        if action == "script":
            result = ai_helper.generate_followup_script(lead_dict, followups_list)
        elif action == "next_action":
            result = ai_helper.suggest_next_action(lead_dict, followups_list)
        elif action == "whatsapp":
            result = ai_helper.draft_message_template(lead_dict, method="WhatsApp")
        elif action == "email":
            result = ai_helper.draft_message_template(lead_dict, method="Email")
        else:
            return jsonify({"error": "Unknown action."}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "quota" in err_msg.lower() or "ResourceExhausted" in err_msg:
            return jsonify({"error": "Google AI quota exceeded. Please check your plan at https://ai.dev/rate-limit or try again later."}), 503
        return jsonify({"error": f"AI error: {err_msg[:200]}"}), 503

    return jsonify({"result": result})

