from flask import render_template, request, redirect, url_for, flash, abort
import os
from datetime import datetime
from db import get_conn
from modules.website import website_bp
from extensions import public_form_limit


@website_bp.route("/")
def home():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT course_name, duration, fee, course_domain, course_category,
               duration_hours, course_slug
        FROM courses
        WHERE is_active = 1 AND show_on_website = 1
        ORDER BY
            CASE WHEN course_domain IS NULL OR course_domain = '' THEN 1 ELSE 0 END,
            course_domain,
            CASE WHEN duration_hours IS NULL THEN 9999 ELSE duration_hours END,
            course_name
    """)
    courses = cur.fetchall()
    conn.close()

    # Build set of slugs that have an actual detail page file
    from flask import current_app
    courses_dir = os.path.join(current_app.template_folder, "website", "courses")
    valid_slugs = set()
    if os.path.isdir(courses_dir):
        for fname in os.listdir(courses_dir):
            if fname.endswith(".html"):
                valid_slugs.add(fname[:-5])

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

    return render_template("website/home.html", courses=courses,
                           grouped_courses=grouped, valid_slugs=valid_slugs)


@website_bp.route("/enquire", methods=["POST"])
@public_form_limit()
def enquire():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    interested_course = request.form.get("interested_course", "").strip()
    message = request.form.get("message", "").strip()

    # Honeypot check (Spambot detection)
    honeypot = request.form.get("website_url_honeypot", "").strip()
    
    # Link & Spam Keyword detection
    import re
    link_pattern = re.compile(r"https?://|www\.|href=|<a\b|(?:\b[a-z0-9\-]+\.)+[a-z]{2,}(?:/[^\s]*)?", re.IGNORECASE)
    has_links = (
        link_pattern.search(name) or 
        link_pattern.search(message)
    )
    
    spam_keywords = ["withdraw", "btc", "bitcoin", "crypto", "casino", "earn money", "viagra", "pills", "btc", "withdraw link"]
    text_to_check = f"{name} {email} {message}".lower()
    has_spam_words = any(kw in text_to_check for kw in spam_keywords)
    
    if honeypot or has_links or has_spam_words:
        # Silent discard: pretend it succeeded so spambots don't try other workarounds
        flash("Thank you! We will contact you shortly.", "success")
        return redirect(url_for("website.home") + "#enquire")

    if not name or not phone:
        flash("Name and phone are required.", "danger")
        return redirect(url_for("website.home") + "#enquire")

    # Clean and validate Indian Mobile Number
    cleaned_phone = re.sub(r"[\s\-\(\)]", "", phone)
    phone_pattern = re.compile(r"^(?:\+91|91|0)?[6-9]\d{9}$")
    if not phone_pattern.match(cleaned_phone):
        flash("Please enter a valid 10-digit Indian mobile number.", "danger")
        return redirect(url_for("website.home") + "#enquire")

    # Validate email formatting if provided
    if email:
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        if not email_pattern.match(email):
            flash("Please enter a valid email address.", "danger")
            return redirect(url_for("website.home") + "#enquire")

    now = datetime.now().isoformat(timespec="seconds")
    notes = message if message else None

    # Auto-assign website leads to Chaithra (user id=2)
    WEBSITE_DEFAULT_OWNER_ID = 2

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO leads (
                name, phone, email, interested_courses,
                lead_source, stage, status, notes,
                assigned_to_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'Website', 'New Lead', 'active', ?, ?, ?, ?)
        """, (name, phone, email or None, interested_course or None,
              notes, WEBSITE_DEFAULT_OWNER_ID, now, now))
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
