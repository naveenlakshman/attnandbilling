from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import os
from db import get_conn, get_company_profile, clear_company_cache
from .utils import login_required, admin_required
from extensions import limiter

core_bp = Blueprint("core", __name__)

@core_bp.route("/erp")
def home():
    if "user_id" in session:
        return redirect(url_for("core.dashboard"))
    return redirect(url_for("core.login"))


@core_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if "user_id" in session:
        return redirect(url_for("core.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM users
            WHERE username = ? AND is_active = 1
        """, (username,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.permanent = True
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["branch_id"] = user["branch_id"]
            session["can_view_all_branches"] = user["can_view_all_branches"]

            flash("Login successful.", "success")
            return redirect(url_for("core.dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("core/login.html")

@core_bp.route("/dashboard")
@login_required
def dashboard():
    # Staff users get their own dedicated dashboard
    if session.get("role") == "staff":
        return _staff_dashboard()

    # ── Admin dashboard below ────────────────────────────────────
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()
    current_month = datetime.now().strftime("%Y-%m")
    seven_days_later = (datetime.now().date() + timedelta(days=7)).isoformat()

    # ── Revenue this month ──────────────────────────────────────
    cur.execute("""
        SELECT COALESCE(SUM(amount_received), 0) AS total
        FROM receipts
        WHERE strftime('%Y-%m', receipt_date) = ?
    """, [current_month])
    revenue_this_month = float(cur.fetchone()["total"] or 0)

    # ── Expenses this month ─────────────────────────────────────
    cur.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE strftime('%Y-%m', expense_date) = ?
    """, [current_month])
    expenses_this_month = float(cur.fetchone()["total"] or 0)

    # ── Active students ─────────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS cnt FROM students WHERE status = 'active'")
    active_students = cur.fetchone()["cnt"]

    # ── New students this month ─────────────────────────────────
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM students
        WHERE strftime('%Y-%m', joined_date) = ?
    """, [current_month])
    new_students_this_month = cur.fetchone()["cnt"]

    # ── Active leads ────────────────────────────────────────────
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM leads
        WHERE status = 'active' AND is_deleted = 0
    """)
    active_leads = cur.fetchone()["cnt"]

    # ── Leads by stage ──────────────────────────────────────────
    cur.execute("""
        SELECT stage, COUNT(*) AS cnt FROM leads
        WHERE status = 'active' AND is_deleted = 0
        GROUP BY stage
        ORDER BY cnt DESC
    """)
    leads_by_stage = cur.fetchall()

    # ── Lead conversion stats ───────────────────────────────────
    cur.execute("SELECT COUNT(*) AS cnt FROM leads WHERE status = 'converted' AND is_deleted = 0")
    total_converted = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM leads WHERE is_deleted = 0")
    total_leads_all = cur.fetchone()["cnt"]
    conversion_rate = round((total_converted / total_leads_all * 100), 1) if total_leads_all else 0

    # ── Today's new leads ───────────────────────────────────────
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM leads
        WHERE date(created_at) = ? AND is_deleted = 0
    """, [today])
    today_new_leads = cur.fetchone()["cnt"]

    # ── Past due installments ───────────────────────────────────
    cur.execute("""
        SELECT
            ip.id, ip.due_date, ip.amount_due, ip.amount_paid, ip.remarks,
            i.invoice_no, i.id AS invoice_id,
            s.full_name AS student_name, s.student_code, s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) < ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
        ORDER BY parse_date(ip.due_date) ASC
    """, [today])
    past_dues = cur.fetchall()
    total_past_due = sum(float(r["balance_due"] or 0) for r in past_dues)

    # ── Today's due installments ────────────────────────────────
    cur.execute("""
        SELECT
            ip.id, ip.due_date, ip.amount_due, ip.amount_paid, ip.remarks,
            i.invoice_no, i.id AS invoice_id,
            s.full_name AS student_name, s.student_code, s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) = ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
        ORDER BY s.full_name ASC
    """, [today])
    todays_dues = cur.fetchall()
    total_today_due = sum(float(r["balance_due"] or 0) for r in todays_dues)

    # ── Due in next 7 days ──────────────────────────────────────
    cur.execute("""
        SELECT
            COALESCE(SUM(ip.amount_due - ip.amount_paid), 0) AS total,
            COUNT(*) AS cnt
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) > ?
          AND parse_date(ip.due_date) <= ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
    """, [today, seven_days_later])
    row = cur.fetchone()
    total_next7_due = float(row["total"] or 0)
    count_next7_due = row["cnt"]

    # ── Bad debt total ──────────────────────────────────────────
    cur.execute("SELECT COALESCE(SUM(amount_written_off), 0) AS total FROM bad_debt_writeoffs")
    total_bad_debt = float(cur.fetchone()["total"] or 0)

    # ── Today's attendance ──────────────────────────────────────
    cur.execute("""
        SELECT status, COUNT(*) AS cnt
        FROM attendance_records
        WHERE attendance_date = ?
        GROUP BY status
    """, [today])
    att_rows = cur.fetchall()
    att_summary = {r["status"]: r["cnt"] for r in att_rows}
    att_present = att_summary.get("present", 0)
    att_late = att_summary.get("late", 0)
    att_absent = att_summary.get("absent", 0)
    att_total = att_present + att_late + att_absent
    attendance_rate = round(((att_present + att_late) / att_total * 100), 1) if att_total else None

    # ── Active batches ──────────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS cnt FROM batches WHERE status = 'active'")
    active_batches = cur.fetchone()["cnt"]

    # ── Past due leads ──────────────────────────────────────────
    cur.execute("""
        SELECT id, name, phone, next_followup_date, lead_score, stage
        FROM leads
        WHERE status = 'active' AND is_deleted = 0
          AND next_followup_date IS NOT NULL
          AND next_followup_date < ?
        ORDER BY next_followup_date ASC
    """, [today])
    past_due_leads = cur.fetchall()

    # ── Today's due leads ───────────────────────────────────────
    cur.execute("""
        SELECT id, name, phone, next_followup_date, lead_score, stage
        FROM leads
        WHERE status = 'active' AND is_deleted = 0
          AND next_followup_date = ?
        ORDER BY lead_score DESC
    """, [today])
    today_due_leads = cur.fetchall()

    # ── Recent activity ─────────────────────────────────────────
    cur.execute("""
        SELECT al.action_type, al.module_name, al.description, al.created_at,
               u.full_name AS user_name
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        ORDER BY al.created_at DESC
        LIMIT 10
    """)
    recent_activity = cur.fetchall()

    conn.close()

    return render_template(
        "core/dashboard_new.html",
        today=today,
        current_month=current_month,
        # Revenue & Expenses
        revenue_this_month=revenue_this_month,
        expenses_this_month=expenses_this_month,
        net_profit_this_month=revenue_this_month - expenses_this_month,
        # Students
        active_students=active_students,
        new_students_this_month=new_students_this_month,
        # Leads
        active_leads=active_leads,
        leads_by_stage=leads_by_stage,
        conversion_rate=conversion_rate,
        today_new_leads=today_new_leads,
        # Receivables
        past_dues=past_dues,
        todays_dues=todays_dues,
        total_past_due=total_past_due,
        total_today_due=total_today_due,
        total_next7_due=total_next7_due,
        count_next7_due=count_next7_due,
        total_bad_debt=total_bad_debt,
        # Attendance
        attendance_rate=attendance_rate,
        att_present=att_present,
        att_late=att_late,
        att_absent=att_absent,
        att_total=att_total,
        active_batches=active_batches,
        # Leads followup
        past_due_leads=past_due_leads,
        today_due_leads=today_due_leads,
        # Activity
        recent_activity=recent_activity,
    )


def _staff_dashboard():
    """Build and render the staff dashboard for the logged-in staff user."""
    user_id = session.get("user_id")
    branch_id = session.get("branch_id")
    can_view_all = session.get("can_view_all_branches", 0)

    conn = get_conn()
    cur = conn.cursor()
    today = datetime.now().date().isoformat()
    current_month = datetime.now().strftime("%Y-%m")

    # ── My batches (trainer = me) ───────────────────────────────
    cur.execute("""
        SELECT b.id, b.batch_name, b.start_time, b.end_time, b.status,
               c.course_name, br.branch_name,
               COUNT(sb.id) AS student_count
        FROM batches b
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN branches br ON b.branch_id = br.id
        LEFT JOIN student_batches sb ON sb.batch_id = b.id AND sb.status = 'active'
        WHERE b.trainer_id = ? AND b.status = 'active'
        GROUP BY b.id
        ORDER BY b.batch_name ASC
    """, [user_id])
    my_batches = cur.fetchall()

    # ── Today's attendance (my batches) ────────────────────────
    batch_ids = [b["id"] for b in my_batches]
    if batch_ids:
        placeholders = ",".join("?" * len(batch_ids))
        cur.execute(f"""
            SELECT status, COUNT(*) AS cnt
            FROM attendance_records
            WHERE attendance_date = ? AND batch_id IN ({placeholders})
            GROUP BY status
        """, [today] + batch_ids)
        att_rows = cur.fetchall()
    else:
        att_rows = []
    att_summary = {r["status"]: r["cnt"] for r in att_rows}
    att_present = att_summary.get("present", 0)
    att_late = att_summary.get("late", 0)
    att_absent = att_summary.get("absent", 0)
    att_total = att_present + att_late + att_absent
    attendance_rate = round(((att_present + att_late) / att_total * 100), 1) if att_total else None

    # ── My assigned leads — followup overdue ───────────────────
    cur.execute("""
        SELECT id, name, phone, next_followup_date, lead_score, stage
        FROM leads
        WHERE assigned_to_id = ? AND status = 'active' AND is_deleted = 0
          AND next_followup_date IS NOT NULL AND next_followup_date < ?
        ORDER BY next_followup_date ASC
    """, [user_id, today])
    my_past_due_leads = cur.fetchall()

    # ── My assigned leads — followup today ─────────────────────
    cur.execute("""
        SELECT id, name, phone, next_followup_date, lead_score, stage
        FROM leads
        WHERE assigned_to_id = ? AND status = 'active' AND is_deleted = 0
          AND next_followup_date = ?
        ORDER BY lead_score DESC
    """, [user_id, today])
    my_today_leads = cur.fetchall()

    # ── Active students in my batches ───────────────────────────
    if batch_ids:
        placeholders = ",".join("?" * len(batch_ids))
        cur.execute(f"""
            SELECT COUNT(DISTINCT sb.student_id) AS cnt
            FROM student_batches sb
            WHERE sb.batch_id IN ({placeholders}) AND sb.status = 'active'
        """, batch_ids)
        my_active_students = cur.fetchone()["cnt"]
    else:
        my_active_students = 0

    # ── New students this month in my branch ────────────────────
    branch_filter = "" if can_view_all else "AND branch_id = ?"
    branch_params = [current_month] if can_view_all else [current_month, branch_id]
    cur.execute(f"""
        SELECT COUNT(*) AS cnt FROM students
        WHERE strftime('%Y-%m', joined_date) = ? {branch_filter}
    """, branch_params)
    new_students_this_month = cur.fetchone()["cnt"]

    # ── Overdue payments for my branch ─────────────────────────
    if can_view_all:
        branch_clause = ""
        branch_param = []
    else:
        branch_clause = "AND i.branch_id = ?"
        branch_param = [branch_id]

    cur.execute(f"""
        SELECT
            ip.id, ip.due_date, ip.amount_due, ip.amount_paid, ip.remarks,
            i.invoice_no, i.id AS invoice_id,
            s.full_name AS student_name, s.student_code, s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) < ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
          {branch_clause}
        ORDER BY parse_date(ip.due_date) ASC
        LIMIT 50
    """, [today] + branch_param)
    past_dues = cur.fetchall()
    total_past_due = sum(float(r["balance_due"] or 0) for r in past_dues)

    # ── Today's dues for my branch ──────────────────────────────
    cur.execute(f"""
        SELECT
            ip.id, ip.due_date, ip.amount_due, ip.amount_paid, ip.remarks,
            i.invoice_no, i.id AS invoice_id,
            s.full_name AS student_name, s.student_code, s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) = ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
          {branch_clause}
        ORDER BY s.full_name ASC
    """, [today] + branch_param)
    todays_dues = cur.fetchall()
    total_today_due = sum(float(r["balance_due"] or 0) for r in todays_dues)

    # ── Recent activity (mine) ──────────────────────────────────
    cur.execute("""
        SELECT al.action_type, al.module_name, al.description, al.created_at
        FROM activity_logs al
        WHERE al.user_id = ?
        ORDER BY al.created_at DESC
        LIMIT 8
    """, [user_id])
    recent_activity = cur.fetchall()

    conn.close()

    return render_template(
        "core/dashboard_staff.html",
        today=today,
        current_month=current_month,
        my_batches=my_batches,
        att_present=att_present,
        att_late=att_late,
        att_absent=att_absent,
        att_total=att_total,
        attendance_rate=attendance_rate,
        my_past_due_leads=my_past_due_leads,
        my_today_leads=my_today_leads,
        my_active_students=my_active_students,
        new_students_this_month=new_students_this_month,
        past_dues=past_dues,
        todays_dues=todays_dues,
        total_past_due=total_past_due,
        total_today_due=total_today_due,
        recent_activity=recent_activity,
    )


@core_bp.route("/dashboard_classic")
@login_required
def dashboard_classic():
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()

    cur.execute("""
        SELECT
            ip.id, ip.due_date, ip.amount_due, ip.amount_paid, ip.status, ip.remarks,
            i.invoice_no, i.id AS invoice_id,
            s.full_name AS student_name, s.student_code, s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) < ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
        ORDER BY parse_date(ip.due_date) ASC
    """, [today])
    past_dues = cur.fetchall()

    cur.execute("""
        SELECT
            ip.id, ip.due_date, ip.amount_due, ip.amount_paid, ip.status, ip.remarks,
            i.invoice_no, i.id AS invoice_id,
            s.full_name AS student_name, s.student_code, s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i ON ip.invoice_id = i.id
        JOIN students s ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) = ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
        ORDER BY s.full_name ASC
    """, [today])
    todays_dues = cur.fetchall()

    total_past_due = sum(float(r["balance_due"] or 0) for r in past_dues)
    total_today_due = sum(float(r["balance_due"] or 0) for r in todays_dues)

    cur.execute("""
        SELECT id, name, phone, next_followup_date, lead_score, stage, status
        FROM leads
        WHERE status = 'active' AND is_deleted = 0
          AND next_followup_date IS NOT NULL AND next_followup_date < ?
        ORDER BY next_followup_date ASC
    """, [today])
    past_due_leads = cur.fetchall()

    cur.execute("""
        SELECT id, name, phone, next_followup_date, lead_score, stage, status
        FROM leads
        WHERE status = 'active' AND is_deleted = 0
          AND next_followup_date IS NOT NULL AND next_followup_date = ?
        ORDER BY lead_score DESC
    """, [today])
    today_due_leads = cur.fetchall()

    conn.close()

    return render_template(
        "core/dashboard.html",
        past_dues=past_dues,
        todays_dues=todays_dues,
        total_past_due=total_past_due,
        total_today_due=total_today_due,
        past_due_leads=past_due_leads,
        today_due_leads=today_due_leads,
        today=today
    )


@core_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("core.login"))


@core_bp.route("/users")
@login_required
@admin_required
def users():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            u.*,
            b.branch_name
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.id
        ORDER BY u.id DESC
    """)
    users_list = cur.fetchall()

    conn.close()
    return render_template("core/users.html", users=users_list)


@core_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def user_new():
    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()
        branch_id = request.form.get("branch_id", "").strip() or None
        can_view_all_branches = 1 if request.form.get("can_view_all_branches") == "1" else 0

        if not full_name or not username or not password or not role:
            flash("Full name, username, password and role are required.", "danger")
            conn.close()
            return redirect(url_for("core.user_new"))

        if role not in ["admin", "staff"]:
            flash("Invalid role selected.", "danger")
            conn.close()
            return redirect(url_for("core.user_new"))

        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        existing_user = cur.fetchone()
        if existing_user:
            flash("Username already exists.", "danger")
            conn.close()
            return redirect(url_for("core.user_new"))

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            INSERT INTO users (
                full_name,
                username,
                password_hash,
                role,
                branch_id,
                can_view_all_branches,
                is_active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            full_name,
            username,
            generate_password_hash(password),
            role,
            branch_id,
            can_view_all_branches,
            1,
            now
        ))

        conn.commit()
        conn.close()

        flash("User created successfully.", "success")
        return redirect(url_for("core.users"))

    cur.execute("""
        SELECT id, branch_name
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    conn.close()
    return render_template("core/user_form.html", mode="create", user=None, branches=branches)


@core_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(user_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("core.users"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()
        branch_id = request.form.get("branch_id", "").strip() or None
        can_view_all_branches = 1 if request.form.get("can_view_all_branches") == "1" else 0

        if not full_name or not username or not role:
            flash("Full name, username and role are required.", "danger")
            conn.close()
            return redirect(url_for("core.user_edit", user_id=user_id))

        if role not in ["admin", "staff"]:
            flash("Invalid role selected.", "danger")
            conn.close()
            return redirect(url_for("core.user_edit", user_id=user_id))

        cur.execute("SELECT id FROM users WHERE username = ? AND id != ?", (username, user_id))
        existing_user = cur.fetchone()
        if existing_user:
            flash("Username already exists.", "danger")
            conn.close()
            return redirect(url_for("core.user_edit", user_id=user_id))

        if password:
            cur.execute("""
                UPDATE users
                SET full_name = ?,
                    username = ?,
                    password_hash = ?,
                    role = ?,
                    branch_id = ?,
                    can_view_all_branches = ?
                WHERE id = ?
            """, (
                full_name,
                username,
                generate_password_hash(password),
                role,
                branch_id,
                can_view_all_branches,
                user_id
            ))
        else:
            cur.execute("""
                UPDATE users
                SET full_name = ?,
                    username = ?,
                    role = ?,
                    branch_id = ?,
                    can_view_all_branches = ?
                WHERE id = ?
            """, (
                full_name,
                username,
                role,
                branch_id,
                can_view_all_branches,
                user_id
            ))

        conn.commit()
        conn.close()

        flash("User updated successfully.", "success")
        return redirect(url_for("core.users"))

    cur.execute("""
        SELECT id, branch_name
        FROM branches
        WHERE is_active = 1
        ORDER BY branch_name
    """)
    branches = cur.fetchall()

    conn.close()
    return render_template("core/user_form.html", mode="edit", user=user, branches=branches)


@core_bp.route("/users/<int:user_id>/toggle-status", methods=["POST"])
@login_required
@admin_required
def user_toggle_status(user_id):
    if user_id == session.get("user_id"):
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("core.users"))

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("core.users"))

    new_status = 0 if user["is_active"] == 1 else 1

    cur.execute("""
        UPDATE users
        SET is_active = ?
        WHERE id = ?
    """, (new_status, user_id))

    conn.commit()
    conn.close()

    if new_status == 1:
        flash("User activated successfully.", "success")
    else:
        flash("User deactivated successfully.", "warning")

    return redirect(url_for("core.users"))


# ============== BRANCH MANAGEMENT ==============

@core_bp.route("/branches")
@login_required
@admin_required
def branches():
    """List all branches"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM branches
        ORDER BY branch_name DESC
    """)
    branches_list = cur.fetchall()

    conn.close()
    return render_template("core/branches.html", branches=branches_list)


@core_bp.route("/branches/new", methods=["GET", "POST"])
@login_required
@admin_required
def branch_new():
    """Create new branch"""
    conn = get_conn()
    cur = conn.cursor()

    if request.method == "POST":
        branch_name = request.form.get("branch_name", "").strip()
        branch_code = request.form.get("branch_code", "").strip()
        address = request.form.get("address", "").strip()
        no_of_computers = request.form.get("no_of_computers", "0").strip()
        try:
            no_of_computers = int(no_of_computers)
            if no_of_computers < 0:
                no_of_computers = 0
        except ValueError:
            no_of_computers = 0
        opening_time = request.form.get("opening_time", "").strip() or None
        closing_time = request.form.get("closing_time", "").strip() or None

        if not branch_name or not branch_code:
            flash("Branch name and branch code are required.", "danger")
            conn.close()
            return redirect(url_for("core.branch_new"))

        cur.execute("SELECT id FROM branches WHERE branch_name = ? OR branch_code = ?", (branch_name, branch_code))
        existing_branch = cur.fetchone()
        if existing_branch:
            flash("Branch name or code already exists.", "danger")
            conn.close()
            return redirect(url_for("core.branch_new"))

        now = datetime.now().isoformat(timespec="seconds")

        cur.execute("""
            INSERT INTO branches (branch_name, branch_code, address, is_active, no_of_computers, opening_time, closing_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            branch_name,
            branch_code,
            address,
            1,
            no_of_computers,
            opening_time,
            closing_time,
            now
        ))

        conn.commit()
        conn.close()

        flash("Branch created successfully.", "success")
        return redirect(url_for("core.branches"))

    conn.close()
    return render_template("core/branch_form.html", mode="create", branch=None)


@core_bp.route("/branches/<int:branch_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def branch_edit(branch_id):
    """Edit branch"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM branches WHERE id = ?", (branch_id,))
    branch = cur.fetchone()

    if not branch:
        conn.close()
        flash("Branch not found.", "danger")
        return redirect(url_for("core.branches"))

    if request.method == "POST":
        branch_name = request.form.get("branch_name", "").strip()
        branch_code = request.form.get("branch_code", "").strip()
        address = request.form.get("address", "").strip()
        no_of_computers = request.form.get("no_of_computers", "0").strip()
        try:
            no_of_computers = int(no_of_computers)
            if no_of_computers < 0:
                no_of_computers = 0
        except ValueError:
            no_of_computers = 0
        opening_time = request.form.get("opening_time", "").strip() or None
        closing_time = request.form.get("closing_time", "").strip() or None

        if not branch_name or not branch_code:
            flash("Branch name and branch code are required.", "danger")
            conn.close()
            return redirect(url_for("core.branch_edit", branch_id=branch_id))

        cur.execute("SELECT id FROM branches WHERE (branch_name = ? OR branch_code = ?) AND id != ?", 
                   (branch_name, branch_code, branch_id))
        existing_branch = cur.fetchone()
        if existing_branch:
            flash("Branch name or code already exists.", "danger")
            conn.close()
            return redirect(url_for("core.branch_edit", branch_id=branch_id))

        cur.execute("""
            UPDATE branches
            SET branch_name = ?,
                branch_code = ?,
                address = ?,
                no_of_computers = ?,
                opening_time = ?,
                closing_time = ?
            WHERE id = ?
        """, (
            branch_name,
            branch_code,
            address,
            no_of_computers,
            opening_time,
            closing_time,
            branch_id
        ))

        conn.commit()
        conn.close()

        flash("Branch updated successfully.", "success")
        return redirect(url_for("core.branches"))

    conn.close()
    return render_template("core/branch_form.html", mode="edit", branch=branch)


@core_bp.route("/branches/<int:branch_id>/toggle-status", methods=["POST"])
@login_required
@admin_required
def branch_toggle_status(branch_id):
    """Toggle branch active/inactive status"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM branches WHERE id = ?", (branch_id,))
    branch = cur.fetchone()

    if not branch:
        conn.close()
        flash("Branch not found.", "danger")
        return redirect(url_for("core.branches"))

    new_status = 0 if branch["is_active"] == 1 else 1

    cur.execute("""
        UPDATE branches
        SET is_active = ?
        WHERE id = ?
    """, (new_status, branch_id))

    conn.commit()
    conn.close()

    if new_status == 1:
        flash("Branch activated successfully.", "success")
    else:
        flash("Branch deactivated successfully.", "warning")

    return redirect(url_for("core.branches"))


# ============== COMPANY PROFILE ==============

COMPANY_LOGO_DIR = os.path.join('static', 'images', 'company_logo')
ALLOWED_LOGO_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.svg', '.webp'}
MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


@core_bp.route("/company-profile", methods=["GET", "POST"])
@login_required
@admin_required
def company_profile():
    """View and edit company profile (global white-label settings)."""
    profile = get_company_profile()

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        company_short_name = request.form.get("company_short_name", "").strip()
        tagline = request.form.get("tagline", "").strip()
        address = request.form.get("address", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        website = request.form.get("website", "").strip()
        reg_number = request.form.get("reg_number", "").strip()

        if not company_name or not company_short_name:
            flash("Company name and short name are required.", "danger")
            return redirect(url_for("core.company_profile"))

        # Handle logo upload
        logo_filename = profile.get("logo_filename")
        logo_file = request.files.get("logo_file")
        if logo_file and logo_file.filename:
            ext = os.path.splitext(logo_file.filename)[1].lower()
            if ext not in ALLOWED_LOGO_EXTENSIONS:
                flash("Invalid logo format. Allowed: PNG, JPG, SVG, WEBP.", "danger")
                return redirect(url_for("core.company_profile"))
            logo_bytes = logo_file.read()
            if len(logo_bytes) > MAX_LOGO_SIZE_BYTES:
                flash("Logo file too large. Maximum size is 2 MB.", "danger")
                return redirect(url_for("core.company_profile"))
            os.makedirs(COMPANY_LOGO_DIR, exist_ok=True)
            safe_filename = f"company_logo{ext}"
            save_path = os.path.join(COMPANY_LOGO_DIR, safe_filename)
            with open(save_path, 'wb') as f:
                f.write(logo_bytes)
            logo_filename = safe_filename

        now = datetime.now().isoformat(timespec="seconds")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO company_profile
                (id, company_name, company_short_name, tagline, address, phone,
                 email, website, logo_filename, reg_number, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                company_name = excluded.company_name,
                company_short_name = excluded.company_short_name,
                tagline = excluded.tagline,
                address = excluded.address,
                phone = excluded.phone,
                email = excluded.email,
                website = excluded.website,
                logo_filename = excluded.logo_filename,
                reg_number = excluded.reg_number,
                updated_at = excluded.updated_at
        """, (
            company_name, company_short_name, tagline, address,
            phone, email, website, logo_filename, reg_number, now
        ))
        conn.commit()
        conn.close()
        clear_company_cache()
        flash("Company profile updated successfully.", "success")
        return redirect(url_for("core.company_profile"))

    return render_template("core/company_profile.html", profile=profile)


@core_bp.route("/company-profile/remove-logo", methods=["POST"])
@login_required
@admin_required
def company_profile_remove_logo():
    """Remove the current company logo."""
    profile = get_company_profile()
    old_logo = profile.get("logo_filename")
    if old_logo:
        path = os.path.join(COMPANY_LOGO_DIR, old_logo)
        if os.path.isfile(path):
            os.remove(path)

    now = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE company_profile SET logo_filename = NULL, updated_at = ? WHERE id = 1",
        (now,)
    )
    conn.commit()
    conn.close()
    clear_company_cache()
    flash("Logo removed.", "success")
    return redirect(url_for("core.company_profile"))