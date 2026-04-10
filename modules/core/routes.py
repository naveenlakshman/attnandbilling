from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from db import get_conn
from .utils import login_required, admin_required

core_bp = Blueprint("core", __name__)

@core_bp.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("core.dashboard"))
    return redirect(url_for("core.login"))


@core_bp.route("/login", methods=["GET", "POST"])
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
    conn = get_conn()
    cur = conn.cursor()

    today = datetime.now().date().isoformat()

    # Past dues
    past_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) < ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
        ORDER BY parse_date(ip.due_date) ASC
    """

    cur.execute(past_dues_query, [today])
    past_dues = cur.fetchall()

    # Today's dues
    todays_dues_query = """
        SELECT
            ip.id,
            ip.due_date,
            ip.amount_due,
            ip.amount_paid,
            ip.status,
            ip.remarks,
            i.invoice_no,
            i.id AS invoice_id,
            s.full_name AS student_name,
            s.student_code,
            s.phone AS student_phone,
            (ip.amount_due - ip.amount_paid) AS balance_due
        FROM installment_plans ip
        JOIN invoices i
            ON ip.invoice_id = i.id
        JOIN students s
            ON i.student_id = s.id
        WHERE ip.status != 'paid'
          AND parse_date(ip.due_date) = ?
          AND i.status NOT IN ('write_off', 'partially_written_off')
        ORDER BY s.full_name ASC
    """

    cur.execute(todays_dues_query, [today])
    todays_dues = cur.fetchall()

    total_past_due = sum(float(row["balance_due"] or 0) for row in past_dues)
    total_today_due = sum(float(row["balance_due"] or 0) for row in todays_dues)

    # Past due leads (followup due before today)
    past_due_leads_query = """
        SELECT
            id,
            name,
            phone,
            next_followup_date,
            lead_score,
            stage,
            status
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          AND next_followup_date IS NOT NULL
          AND next_followup_date < ?
        ORDER BY next_followup_date ASC
    """

    cur.execute(past_due_leads_query, [today])
    past_due_leads = cur.fetchall()

    # Today's due leads (followup due today)
    today_due_leads_query = """
        SELECT
            id,
            name,
            phone,
            next_followup_date,
            lead_score,
            stage,
            status
        FROM leads
        WHERE status = 'active'
          AND is_deleted = 0
          AND next_followup_date IS NOT NULL
          AND next_followup_date = ?
        ORDER BY lead_score DESC
    """

    cur.execute(today_due_leads_query, [today])
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