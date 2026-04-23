from flask import render_template, request, redirect, url_for, flash, abort
import os
from datetime import datetime
from db import get_conn
from modules.website import website_bp
from extensions import limiter


@website_bp.route("/")
def home():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT course_name, duration, fee, course_domain, course_category
        FROM courses
        WHERE is_active = 1 AND show_on_website = 1
        ORDER BY course_domain, course_category, course_name
    """)
    courses = cur.fetchall()
    conn.close()

    # Group by domain for template
    from collections import OrderedDict
    grouped = OrderedDict()
    ungrouped = []
    for c in courses:
        domain = c["course_domain"] or None
        if domain:
            grouped.setdefault(domain, []).append(c)
        else:
            ungrouped.append(c)
    if ungrouped:
        grouped["Other"] = ungrouped

    return render_template("website/home.html", courses=courses, grouped_courses=grouped)


@website_bp.route("/enquire", methods=["POST"])
@limiter.limit("5 per minute")
def enquire():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    interested_course = request.form.get("interested_course", "").strip()
    message = request.form.get("message", "").strip()

    if not name or not phone:
        flash("Name and phone are required.", "danger")
        return redirect(url_for("website.home") + "#enquire")

    now = datetime.now().isoformat(timespec="seconds")
    notes = message if message else None

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO leads (
                name, phone, email, interested_courses,
                lead_source, stage, status, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'Website', 'New Lead', 'active', ?, ?, ?)
        """, (name, phone, email or None, interested_course or None,
              notes, now, now))
        conn.commit()
    finally:
        conn.close()

    flash("Thank you! We will contact you shortly.", "success")
    return redirect(url_for("website.home") + "#enquire")


@website_bp.route("/courses/<slug>")
def course_page(slug):
    # Security: allow only alphanumeric, hyphens, underscores
    import re
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", slug):
        abort(404)
    template_path = f"website/courses/{slug}.html"
    # Verify the file actually exists before rendering
    from flask import current_app
    full_path = os.path.join(current_app.template_folder, template_path)
    if not os.path.isfile(full_path):
        abort(404)
    return render_template(template_path)
