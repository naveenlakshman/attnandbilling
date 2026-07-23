from __future__ import annotations

import re
from datetime import datetime

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from db import get_conn
from modules.core.utils import login_required, platform_owner_required
from services.tenant_context import clear_tenant_cache, normalize_hostname

from . import platform_admin_bp


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _domain_activation(hostname):
    """Automatically verify only loopback hostnames outside production."""
    is_local = (
        hostname
        and (hostname == "localhost" or hostname.endswith(".localhost"))
        and current_app.config.get("APP_ENV") != "production"
    )
    return ("active", _now()) if is_local else ("pending", None)


def _institute_or_404(conn, institute_id):
    institute = conn.execute(
        "SELECT * FROM institutes WHERE id = ?",
        (institute_id,),
    ).fetchone()
    if not institute:
        abort(404)
    return institute


def _validate_institute_form(conn, institute_id=None):
    name = request.form.get("name", "").strip()
    short_name = request.form.get("short_name", "").strip()
    slug = request.form.get("slug", "").strip().lower()
    hostname = normalize_hostname(request.form.get("hostname", ""))
    timezone = request.form.get("timezone", "Asia/Kolkata").strip() or "Asia/Kolkata"
    locale = request.form.get("locale", "en-IN").strip() or "en-IN"
    currency_code = request.form.get("currency_code", "INR").strip().upper() or "INR"

    if not name or not short_name or not slug:
        return None, "Name, short name and slug are required."
    if not _SLUG_RE.fullmatch(slug):
        return None, "Slug may contain lowercase letters, numbers and single hyphens only."
    if len(currency_code) != 3 or not currency_code.isalpha():
        return None, "Currency must be a three-letter ISO code."

    params = [slug]
    sql = "SELECT id FROM institutes WHERE slug = ?"
    if institute_id is not None:
        sql += " AND id != ?"
        params.append(institute_id)
    if conn.execute(sql, tuple(params)).fetchone():
        return None, "That institute slug is already in use."

    if hostname:
        params = [hostname]
        sql = "SELECT institute_id FROM institute_domains WHERE hostname = ?"
        if institute_id is not None:
            sql += " AND institute_id != ?"
            params.append(institute_id)
        if conn.execute(sql, tuple(params)).fetchone():
            return None, "That hostname is already assigned to another institute."

    return {
        "name": name,
        "short_name": short_name,
        "slug": slug,
        "hostname": hostname,
        "timezone": timezone,
        "locale": locale,
        "currency_code": currency_code,
        "tagline": request.form.get("tagline", "").strip(),
        "primary_color": request.form.get("primary_color", "#2563EB").strip() or "#2563EB",
        "secondary_color": request.form.get("secondary_color", "#16A34A").strip() or "#16A34A",
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "website": request.form.get("website", "").strip(),
    }, None


@platform_admin_bp.route("/institutes")
@login_required
@platform_owner_required
def institutes():
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT i.*,
                   (SELECT COUNT(*) FROM branches b WHERE b.institute_id = i.id) AS branch_count,
                   (SELECT COUNT(*) FROM institute_memberships im
                    WHERE im.institute_id = i.id AND im.membership_role = 'institute_admin'
                      AND im.is_active = 1) AS admin_count,
                   (SELECT hostname FROM institute_domains d
                    WHERE d.institute_id = i.id AND d.is_primary = 1
                    ORDER BY d.id LIMIT 1) AS primary_hostname
            FROM institutes i
            ORDER BY i.name
            """
        ).fetchall()
        return render_template("platform_admin/institutes.html", institutes=rows)
    finally:
        conn.close()


@platform_admin_bp.route("/institutes/new", methods=["GET", "POST"])
@login_required
@platform_owner_required
def institute_new():
    if request.method == "GET":
        return render_template("platform_admin/institute_form.html", institute=None, branding=None)

    conn = get_conn()
    try:
        values, error = _validate_institute_form(conn)
        if error:
            flash(error, "danger")
            return render_template("platform_admin/institute_form.html", institute=None, branding=request.form)

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO institutes (
                name, short_name, slug, status, timezone, locale,
                currency_code, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
            """,
            (
                values["name"], values["short_name"], values["slug"],
                values["timezone"], values["locale"], values["currency_code"], now, now,
            ),
        )
        institute_id = cur.lastrowid
        cur.execute(
            """
            INSERT INTO institute_branding (
                institute_id, display_name, short_name, tagline, primary_color,
                secondary_color, email, phone, website, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                institute_id, values["name"], values["short_name"], values["tagline"],
                values["primary_color"], values["secondary_color"], values["email"],
                values["phone"], values["website"], now, now,
            ),
        )
        cur.execute(
            """
            INSERT INTO institute_settings (
                institute_id, invoice_prefix, receipt_prefix, student_prefix,
                certificate_prefix, date_format, created_at, updated_at
            ) VALUES (?, 'INV', 'RCP', 'STU', 'CERT', 'DD-MMM-YYYY', ?, ?)
            """,
            (institute_id, now, now),
        )
        if values["hostname"]:
            domain_status, verified_at = _domain_activation(values["hostname"])
            cur.execute(
                """
                INSERT INTO institute_domains (
                    institute_id, hostname, domain_type, is_primary, status,
                    verified_at, created_at, updated_at
                ) VALUES (?, ?, 'custom', 1, ?, ?, ?, ?)
                """,
                (
                    institute_id, values["hostname"], domain_status,
                    verified_at, now, now,
                ),
            )
        conn.commit()
        clear_tenant_cache()
        flash("Institute created. Add its first branch and administrator next.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@platform_admin_bp.route("/institutes/<int:institute_id>")
@login_required
@platform_owner_required
def institute_detail(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        branding = conn.execute(
            "SELECT * FROM institute_branding WHERE institute_id = ?",
            (institute_id,),
        ).fetchone()
        settings = conn.execute(
            "SELECT * FROM institute_settings WHERE institute_id = ?",
            (institute_id,),
        ).fetchone()
        domains = conn.execute(
            "SELECT * FROM institute_domains WHERE institute_id = ? ORDER BY is_primary DESC, hostname",
            (institute_id,),
        ).fetchall()
        branches = conn.execute(
            "SELECT * FROM branches WHERE institute_id = ? ORDER BY branch_name",
            (institute_id,),
        ).fetchall()
        admins = conn.execute(
            """
            SELECT u.*, b.branch_name, im.membership_role, im.is_active AS membership_active
            FROM institute_memberships im
            JOIN users u ON u.id = im.user_id AND u.institute_id = im.institute_id
            LEFT JOIN branches b ON b.id = u.branch_id AND b.institute_id = u.institute_id
            WHERE im.institute_id = ? AND im.membership_role = 'institute_admin'
            ORDER BY u.full_name
            """,
            (institute_id,),
        ).fetchall()
        return render_template(
            "platform_admin/institute_detail.html",
            institute=institute,
            branding=branding,
            settings=settings,
            domains=domains,
            branches=branches,
            admins=admins,
        )
    finally:
        conn.close()


@platform_admin_bp.route("/institutes/<int:institute_id>/edit", methods=["GET", "POST"])
@login_required
@platform_owner_required
def institute_edit(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        branding = conn.execute(
            "SELECT * FROM institute_branding WHERE institute_id = ?",
            (institute_id,),
        ).fetchone()
        primary_domain = conn.execute(
            """SELECT * FROM institute_domains
               WHERE institute_id = ? AND is_primary = 1 ORDER BY id LIMIT 1""",
            (institute_id,),
        ).fetchone()
        if request.method == "GET":
            return render_template(
                "platform_admin/institute_form.html",
                institute=institute,
                branding=branding,
                primary_domain=primary_domain,
            )

        values, error = _validate_institute_form(conn, institute_id)
        if error:
            flash(error, "danger")
            return redirect(url_for("platform_admin.institute_edit", institute_id=institute_id))
        now = _now()
        conn.execute(
            """
            UPDATE institutes
            SET name = ?, short_name = ?, slug = ?, timezone = ?, locale = ?,
                currency_code = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                values["name"], values["short_name"], values["slug"],
                values["timezone"], values["locale"], values["currency_code"],
                now, institute_id,
            ),
        )
        conn.execute(
            """
            UPDATE institute_branding
            SET display_name = ?, short_name = ?, tagline = ?, primary_color = ?,
                secondary_color = ?, email = ?, phone = ?, website = ?, updated_at = ?
            WHERE institute_id = ?
            """,
            (
                values["name"], values["short_name"], values["tagline"],
                values["primary_color"], values["secondary_color"], values["email"],
                values["phone"], values["website"], now, institute_id,
            ),
        )
        if values["hostname"]:
            domain_status, verified_at = _domain_activation(values["hostname"])
            if primary_domain:
                conn.execute(
                    """
                    UPDATE institute_domains
                    SET hostname = ?, status = ?, verified_at = ?, updated_at = ?
                    WHERE id = ? AND institute_id = ?
                    """,
                    (
                        values["hostname"], domain_status, verified_at, now,
                        primary_domain["id"], institute_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO institute_domains (
                        institute_id, hostname, domain_type, is_primary, status,
                        verified_at, created_at, updated_at
                    ) VALUES (?, ?, 'custom', 1, ?, ?, ?, ?)
                    """,
                    (
                        institute_id, values["hostname"], domain_status,
                        verified_at, now, now,
                    ),
                )
        conn.commit()
        clear_tenant_cache()
        flash("Institute settings updated.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@platform_admin_bp.post("/institutes/<int:institute_id>/toggle-status")
@login_required
@platform_owner_required
def institute_toggle_status(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        new_status = "inactive" if institute["status"] == "active" else "active"
        conn.execute(
            "UPDATE institutes SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _now(), institute_id),
        )
        conn.commit()
        clear_tenant_cache()
        flash(f"Institute marked {new_status}.", "success")
        return redirect(url_for("platform_admin.institutes"))
    finally:
        conn.close()


def _branch_form_values():
    try:
        computers = max(0, int(request.form.get("no_of_computers", "0") or 0))
    except ValueError:
        computers = 0
    return {
        "branch_name": request.form.get("branch_name", "").strip(),
        "branch_code": request.form.get("branch_code", "").strip().upper(),
        "address": request.form.get("address", "").strip(),
        "no_of_computers": computers,
        "opening_time": request.form.get("opening_time", "").strip() or None,
        "closing_time": request.form.get("closing_time", "").strip() or None,
    }


@platform_admin_bp.route("/institutes/<int:institute_id>/branches/new", methods=["GET", "POST"])
@login_required
@platform_owner_required
def institute_branch_new(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        if request.method == "GET":
            return render_template(
                "core/branch_form.html",
                mode="create",
                branch=None,
                platform_institute=institute,
                cancel_url=url_for("platform_admin.institute_detail", institute_id=institute_id),
            )
        values = _branch_form_values()
        if not values["branch_name"] or not values["branch_code"]:
            flash("Branch name and branch code are required.", "danger")
            return redirect(url_for("platform_admin.institute_branch_new", institute_id=institute_id))
        duplicate = conn.execute(
            """SELECT id FROM branches WHERE institute_id = ?
               AND (branch_name = ? OR branch_code = ?)""",
            (institute_id, values["branch_name"], values["branch_code"]),
        ).fetchone()
        if duplicate:
            flash("That branch name or code is already used by this institute.", "danger")
            return redirect(url_for("platform_admin.institute_branch_new", institute_id=institute_id))
        conn.execute(
            """
            INSERT INTO branches (
                institute_id, branch_name, branch_code, address, is_active,
                no_of_computers, opening_time, closing_time, created_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                institute_id, values["branch_name"], values["branch_code"], values["address"],
                values["no_of_computers"], values["opening_time"], values["closing_time"], _now(),
            ),
        )
        conn.commit()
        flash("Institute branch created.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    finally:
        conn.close()


@platform_admin_bp.route(
    "/institutes/<int:institute_id>/branches/<int:branch_id>/edit",
    methods=["GET", "POST"],
)
@login_required
@platform_owner_required
def institute_branch_edit(institute_id, branch_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        branch = conn.execute(
            "SELECT * FROM branches WHERE id = ? AND institute_id = ?",
            (branch_id, institute_id),
        ).fetchone()
        if not branch:
            abort(404)
        if request.method == "GET":
            return render_template(
                "core/branch_form.html",
                mode="edit",
                branch=branch,
                platform_institute=institute,
                cancel_url=url_for("platform_admin.institute_detail", institute_id=institute_id),
            )
        values = _branch_form_values()
        duplicate = conn.execute(
            """SELECT id FROM branches WHERE institute_id = ? AND id != ?
               AND (branch_name = ? OR branch_code = ?)""",
            (institute_id, branch_id, values["branch_name"], values["branch_code"]),
        ).fetchone()
        if duplicate:
            flash("That branch name or code is already used by this institute.", "danger")
            return redirect(
                url_for(
                    "platform_admin.institute_branch_edit",
                    institute_id=institute_id,
                    branch_id=branch_id,
                )
            )
        conn.execute(
            """
            UPDATE branches
            SET branch_name = ?, branch_code = ?, address = ?, no_of_computers = ?,
                opening_time = ?, closing_time = ?
            WHERE id = ? AND institute_id = ?
            """,
            (
                values["branch_name"], values["branch_code"], values["address"],
                values["no_of_computers"], values["opening_time"], values["closing_time"],
                branch_id, institute_id,
            ),
        )
        conn.commit()
        flash("Institute branch updated.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    finally:
        conn.close()


@platform_admin_bp.route(
    "/institutes/<int:institute_id>/administrators/<int:user_id>/edit",
    methods=["GET", "POST"],
)
@login_required
@platform_owner_required
def institute_admin_edit(institute_id, user_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        user = conn.execute(
            """
            SELECT u.* FROM users u
            JOIN institute_memberships im
              ON im.user_id = u.id AND im.institute_id = u.institute_id
            WHERE u.id = ? AND u.institute_id = ?
              AND im.membership_role = 'institute_admin'
            """,
            (user_id, institute_id),
        ).fetchone()
        if not user:
            abort(404)
        branches = conn.execute(
            "SELECT id, branch_name FROM branches WHERE institute_id = ? AND is_active = 1 ORDER BY branch_name",
            (institute_id,),
        ).fetchall()
        if request.method == "GET":
            return render_template(
                "platform_admin/admin_form.html",
                institute=institute,
                user=user,
                branches=branches,
            )

        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        branch_id = request.form.get("branch_id", "").strip() or None
        if not full_name or not username:
            flash("Full name and username are required.", "danger")
            return redirect(url_for(
                "platform_admin.institute_admin_edit",
                institute_id=institute_id,
                user_id=user_id,
            ))
        if branch_id and not conn.execute(
            "SELECT id FROM branches WHERE id = ? AND institute_id = ? AND is_active = 1",
            (branch_id, institute_id),
        ).fetchone():
            abort(400)
        if conn.execute(
            "SELECT id FROM users WHERE institute_id = ? AND username = ? AND id != ?",
            (institute_id, username, user_id),
        ).fetchone():
            flash("That username is already used by this institute.", "danger")
            return redirect(url_for(
                "platform_admin.institute_admin_edit",
                institute_id=institute_id,
                user_id=user_id,
            ))
        now = _now()
        params = [full_name, username, branch_id, now]
        password_sql = ""
        if password:
            password_sql = ", password_hash = ?"
            params.append(generate_password_hash(password))
        params.extend([user_id, institute_id])
        conn.execute(
            f"""
            UPDATE users
            SET full_name = ?, username = ?, branch_id = ?, updated_at = ?
                {password_sql}
            WHERE id = ? AND institute_id = ?
            """,
            tuple(params),
        )
        conn.commit()
        flash("Institute administrator updated.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@platform_admin_bp.post(
    "/institutes/<int:institute_id>/branches/<int:branch_id>/toggle-status"
)
@login_required
@platform_owner_required
def institute_branch_toggle(institute_id, branch_id):
    conn = get_conn()
    try:
        _institute_or_404(conn, institute_id)
        branch = conn.execute(
            "SELECT * FROM branches WHERE id = ? AND institute_id = ?",
            (branch_id, institute_id),
        ).fetchone()
        if not branch:
            abort(404)
        conn.execute(
            "UPDATE branches SET is_active = ? WHERE id = ? AND institute_id = ?",
            (0 if branch["is_active"] else 1, branch_id, institute_id),
        )
        conn.commit()
        flash("Branch status updated.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    finally:
        conn.close()


@platform_admin_bp.route("/institutes/<int:institute_id>/administrators/new", methods=["GET", "POST"])
@login_required
@platform_owner_required
def institute_admin_new(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        branches = conn.execute(
            "SELECT id, branch_name FROM branches WHERE institute_id = ? AND is_active = 1 ORDER BY branch_name",
            (institute_id,),
        ).fetchall()
        if request.method == "GET":
            return render_template(
                "platform_admin/admin_form.html",
                institute=institute,
                user=None,
                branches=branches,
            )
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        branch_id = request.form.get("branch_id", "").strip() or None
        if not full_name or not username or not password:
            flash("Full name, username and password are required.", "danger")
            return redirect(url_for("platform_admin.institute_admin_new", institute_id=institute_id))
        if branch_id and not conn.execute(
            "SELECT id FROM branches WHERE id = ? AND institute_id = ? AND is_active = 1",
            (branch_id, institute_id),
        ).fetchone():
            abort(400)
        if conn.execute(
            "SELECT id FROM users WHERE institute_id = ? AND username = ?",
            (institute_id, username),
        ).fetchone():
            flash("That username is already used by this institute.", "danger")
            return redirect(url_for("platform_admin.institute_admin_new", institute_id=institute_id))
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (
                institute_id, full_name, username, password_hash, role, platform_role,
                branch_id, can_view_all_branches, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'admin', NULL, ?, 1, 1, ?, ?)
            """,
            (
                institute_id, full_name, username, generate_password_hash(password),
                branch_id, now, now,
            ),
        )
        user_id = cur.lastrowid
        cur.execute(
            """
            INSERT INTO institute_memberships (
                institute_id, user_id, membership_role, is_active, created_at, updated_at
            ) VALUES (?, ?, 'institute_admin', 1, ?, ?)
            """,
            (institute_id, user_id, now, now),
        )
        conn.commit()
        flash("Institute administrator created.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    finally:
        conn.close()


@platform_admin_bp.post(
    "/institutes/<int:institute_id>/administrators/<int:user_id>/toggle-status"
)
@login_required
@platform_owner_required
def institute_admin_toggle(institute_id, user_id):
    conn = get_conn()
    try:
        _institute_or_404(conn, institute_id)
        user = conn.execute(
            """SELECT u.* FROM users u
               JOIN institute_memberships im
                 ON im.user_id = u.id AND im.institute_id = u.institute_id
               WHERE u.id = ? AND u.institute_id = ?
                 AND im.membership_role = 'institute_admin'""",
            (user_id, institute_id),
        ).fetchone()
        if not user:
            abort(404)
        new_status = 0 if user["is_active"] else 1
        now = _now()
        conn.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ? AND institute_id = ?",
            (new_status, now, user_id, institute_id),
        )
        conn.execute(
            """UPDATE institute_memberships SET is_active = ?, updated_at = ?
               WHERE user_id = ? AND institute_id = ?""",
            (new_status, now, user_id, institute_id),
        )
        conn.commit()
        flash("Administrator status updated.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    finally:
        conn.close()
