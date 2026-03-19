from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from db import get_conn
from .utils import login_required

core_bp = Blueprint("core", __name__)

@core_bp.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("core.dashboard"))
    return redirect(url_for("core.login"))

@core_bp.route("/login", methods=["GET", "POST"])
def login():
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
    return render_template("core/dashboard.html")

@core_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("core.login"))