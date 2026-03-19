from datetime import date, datetime
from flask import Blueprint, render_template, session, flash, redirect, url_for
from db import get_conn
from modules.core.utils import login_required

leads_bp = Blueprint("leads", __name__)

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

# Temporary placeholder so dashboard links do not break
@leads_bp.route("/<int:lead_id>")
@login_required
def lead_detail(lead_id):
    flash(f"Lead detail page for Lead ID {lead_id} is not migrated yet.", "info")
    return redirect(url_for("leads.dashboard"))