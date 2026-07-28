from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from db import clear_company_cache, get_conn
from services.storage import get_storage_service
from services.domain_verification import (
    generate_verification_token,
    verification_record_name,
    verification_record_value,
    verify_dns_challenge,
)
from services.subscriptions import (
    PlanLimitExceeded,
    SubscriptionAccessDenied,
    lock_and_check_limit,
    usage_summary,
)
from modules.core.utils import login_required, platform_owner_required
from services.tenant_context import clear_tenant_cache, normalize_hostname

from . import platform_admin_bp


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BRAND_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".ico"}
_MAX_BRAND_IMAGE_BYTES = 2 * 1024 * 1024


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


def _new_domain_challenge(hostname):
    token = generate_verification_token()
    record_name = verification_record_name(
        hostname, current_app.config["DOMAIN_VERIFICATION_PREFIX"]
    )
    return token, record_name


def _save_brand_file(institute_id, field_name, category, old_path=None):
    uploaded = request.files.get(field_name)
    if not uploaded or not uploaded.filename:
        return old_path
    safe_name = secure_filename(uploaded.filename)
    extension = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if extension not in _BRAND_IMAGE_EXTENSIONS:
        raise ValueError("Brand images must be PNG, JPG, WEBP, or ICO files.")
    payload = uploaded.read(_MAX_BRAND_IMAGE_BYTES + 1)
    if len(payload) > _MAX_BRAND_IMAGE_BYTES:
        raise ValueError("Brand images must be 2 MB or smaller.")
    destination = (
        f"tenants/{int(institute_id)}/branding/{category}/"
        f"{uuid.uuid4().hex}{extension}"
    )
    storage = get_storage_service()
    stored_path = storage.upload_file(
        payload,
        destination,
        content_type=uploaded.content_type,
    )
    return stored_path


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
                    ORDER BY d.id LIMIT 1) AS primary_hostname,
                   (SELECT p.name FROM institute_subscriptions s
                    JOIN subscription_plans p ON p.id = s.plan_id
                    WHERE s.institute_id = i.id LIMIT 1) AS plan_name,
                   (SELECT s.status FROM institute_subscriptions s
                    WHERE s.institute_id = i.id LIMIT 1) AS subscription_status
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
            INSERT INTO institute_subscriptions (
                institute_id, plan_id, status, starts_at, created_at, updated_at
            )
            SELECT ?, id, 'active', ?, ?, ?
            FROM subscription_plans WHERE code = 'starter'
            """,
            (institute_id, now, now, now),
        )
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
        try:
            logo_path = _save_brand_file(institute_id, "logo", "logos")
            favicon_path = _save_brand_file(institute_id, "favicon", "favicons")
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), "danger")
            return render_template(
                "platform_admin/institute_form.html",
                institute=None,
                branding=request.form,
            )
        cur.execute(
            """UPDATE institute_branding SET logo_path = ?, favicon_path = ?
               WHERE institute_id = ?""",
            (logo_path, favicon_path, institute_id),
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
            token, record_name = (
                (None, None)
                if domain_status == "active"
                else _new_domain_challenge(values["hostname"])
            )
            cur.execute(
                """
                INSERT INTO institute_domains (
                    institute_id, hostname, domain_type, is_primary, status,
                    verified_at, verification_token, verification_record_name,
                    created_at, updated_at
                ) VALUES (?, ?, 'custom', 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    institute_id, values["hostname"], domain_status,
                    verified_at, token, record_name, now, now,
                ),
            )
        conn.commit()
        clear_tenant_cache()
        clear_company_cache(institute_id)
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
        subscription = conn.execute(
            """SELECT s.*, p.name AS plan_name, p.code AS plan_code
               FROM institute_subscriptions s
               JOIN subscription_plans p ON p.id = s.plan_id
               WHERE s.institute_id = ?""",
            (institute_id,),
        ).fetchone()
        return render_template(
            "platform_admin/institute_detail.html",
            institute=institute,
            branding=branding,
            settings=settings,
            domains=domains,
            branches=branches,
            admins=admins,
            subscription=subscription,
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
        try:
            logo_path = _save_brand_file(
                institute_id, "logo", "logos", branding["logo_path"] if branding else None
            )
            favicon_path = _save_brand_file(
                institute_id,
                "favicon",
                "favicons",
                branding["favicon_path"] if branding else None,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("platform_admin.institute_edit", institute_id=institute_id))
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
                secondary_color = ?, email = ?, phone = ?, website = ?,
                logo_path = ?, favicon_path = ?, updated_at = ?
            WHERE institute_id = ?
            """,
            (
                values["name"], values["short_name"], values["tagline"],
                values["primary_color"], values["secondary_color"], values["email"],
                values["phone"], values["website"], logo_path, favicon_path,
                now, institute_id,
            ),
        )
        if values["hostname"]:
            domain_status, verified_at = _domain_activation(values["hostname"])
            hostname_changed = (
                not primary_domain
                or primary_domain["hostname"] != values["hostname"]
            )
            if domain_status == "active":
                token, record_name = None, None
            elif hostname_changed:
                token, record_name = _new_domain_challenge(values["hostname"])
            else:
                token = primary_domain["verification_token"]
                record_name = primary_domain["verification_record_name"]
            if primary_domain:
                conn.execute(
                    """
                    UPDATE institute_domains
                    SET hostname = ?, status = ?, verified_at = ?,
                        verification_token = ?, verification_record_name = ?,
                        verification_last_checked_at = NULL,
                        verification_message = NULL, updated_at = ?
                    WHERE id = ? AND institute_id = ?
                    """,
                    (
                        values["hostname"], domain_status, verified_at,
                        token, record_name, now,
                        primary_domain["id"], institute_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO institute_domains (
                        institute_id, hostname, domain_type, is_primary, status,
                        verified_at, verification_token, verification_record_name,
                        created_at, updated_at
                    ) VALUES (?, ?, 'custom', 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        institute_id, values["hostname"], domain_status,
                        verified_at, token, record_name, now, now,
                    ),
                )
        conn.commit()
        clear_tenant_cache()
        clear_company_cache(institute_id)
        flash("Institute settings updated.", "success")
        return redirect(url_for("platform_admin.institute_detail", institute_id=institute_id))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _domain_or_404(conn, institute_id, domain_id):
    domain = conn.execute(
        """SELECT * FROM institute_domains
           WHERE id = ? AND institute_id = ?""",
        (domain_id, institute_id),
    ).fetchone()
    if not domain:
        abort(404)
    return domain


@platform_admin_bp.route(
    "/institutes/<int:institute_id>/domains/<int:domain_id>/verification"
)
@login_required
@platform_owner_required
def institute_domain_verification(institute_id, domain_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        domain = _domain_or_404(conn, institute_id, domain_id)
        return render_template(
            "platform_admin/domain_verification.html",
            institute=institute,
            domain=domain,
            txt_value=(
                verification_record_value(domain["verification_token"])
                if domain["verification_token"]
                else None
            ),
        )
    finally:
        conn.close()


@platform_admin_bp.post(
    "/institutes/<int:institute_id>/domains/<int:domain_id>/verification/challenge"
)
@login_required
@platform_owner_required
def institute_domain_verification_challenge(institute_id, domain_id):
    conn = get_conn()
    try:
        _institute_or_404(conn, institute_id)
        domain = _domain_or_404(conn, institute_id, domain_id)
        if domain["status"] == "active":
            flash("This domain is already verified.", "info")
        else:
            token, record_name = _new_domain_challenge(domain["hostname"])
            conn.execute(
                """UPDATE institute_domains
                   SET verification_token = ?, verification_record_name = ?,
                       verification_last_checked_at = NULL,
                       verification_message = NULL, updated_at = ?
                   WHERE id = ? AND institute_id = ?""",
                (token, record_name, _now(), domain_id, institute_id),
            )
            conn.commit()
            flash("A new DNS verification record has been generated.", "success")
        return redirect(
            url_for(
                "platform_admin.institute_domain_verification",
                institute_id=institute_id,
                domain_id=domain_id,
            )
        )
    finally:
        conn.close()


@platform_admin_bp.post(
    "/institutes/<int:institute_id>/domains/<int:domain_id>/verification/check"
)
@login_required
@platform_owner_required
def institute_domain_verification_check(institute_id, domain_id):
    conn = get_conn()
    try:
        _institute_or_404(conn, institute_id)
        domain = _domain_or_404(conn, institute_id, domain_id)
        if not domain["verification_token"] or not domain["verification_record_name"]:
            flash("Generate a DNS challenge before checking verification.", "warning")
            return redirect(
                url_for(
                    "platform_admin.institute_domain_verification",
                    institute_id=institute_id,
                    domain_id=domain_id,
                )
            )

        verified, message = verify_dns_challenge(
            domain["verification_record_name"],
            verification_record_value(domain["verification_token"]),
        )
        now = _now()
        conn.execute(
            """UPDATE institute_domains
               SET status = ?, verified_at = ?, verification_last_checked_at = ?,
                   verification_message = ?, updated_at = ?
               WHERE id = ? AND institute_id = ?""",
            (
                "active" if verified else "pending",
                now if verified else None,
                now,
                message,
                now,
                domain_id,
                institute_id,
            ),
        )
        conn.commit()
        if verified:
            clear_tenant_cache()
            flash(
                "Domain ownership verified and the hostname is active in the application.",
                "success",
            )
        else:
            flash(message, "warning")
        return redirect(
            url_for(
                "platform_admin.institute_domain_verification",
                institute_id=institute_id,
                domain_id=domain_id,
            )
        )
    finally:
        conn.close()


@platform_admin_bp.post("/institutes/<int:institute_id>/toggle-status")
@login_required
@platform_owner_required
def institute_toggle_status(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        onboarding = conn.execute(
            "SELECT status FROM institute_onboarding WHERE institute_id = ?",
            (institute_id,),
        ).fetchone()
        if onboarding and onboarding["status"] != "completed":
            flash("Finish the onboarding activation checklist first.", "warning")
            return redirect(
                url_for(
                    "platform_admin.onboarding_step",
                    institute_id=institute_id,
                    step=9,
                )
            )
        new_status = "suspended" if institute["status"] == "active" else "active"
        subscription_status = "suspended" if new_status == "suspended" else "active"
        now = _now()
        conn.execute(
            "UPDATE institutes SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, institute_id),
        )
        conn.execute(
            """UPDATE institute_subscriptions
               SET status = ?, suspended_at = ?, suspension_reason = ?,
                   grace_ends_at = NULL, updated_at = ?
               WHERE institute_id = ?""",
            (
                subscription_status,
                now if subscription_status == "suspended" else None,
                "Suspended from institute administration"
                if subscription_status == "suspended" else None,
                now, institute_id,
            ),
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
        try:
            lock_and_check_limit(conn, institute_id, "branches")
        except (PlanLimitExceeded, SubscriptionAccessDenied) as exc:
            conn.rollback()
            flash(str(exc), "danger")
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
        new_status = 0 if branch["is_active"] else 1
        if new_status:
            try:
                lock_and_check_limit(conn, institute_id, "branches")
            except (PlanLimitExceeded, SubscriptionAccessDenied) as exc:
                conn.rollback()
                flash(str(exc), "danger")
                return redirect(
                    url_for("platform_admin.institute_detail", institute_id=institute_id)
                )
        conn.execute(
            "UPDATE branches SET is_active = ? WHERE id = ? AND institute_id = ?",
            (new_status, branch_id, institute_id),
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
        try:
            lock_and_check_limit(conn, institute_id, "staff")
        except (PlanLimitExceeded, SubscriptionAccessDenied) as exc:
            conn.rollback()
            flash(str(exc), "danger")
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
        if new_status:
            try:
                lock_and_check_limit(conn, institute_id, "staff")
            except (PlanLimitExceeded, SubscriptionAccessDenied) as exc:
                conn.rollback()
                flash(str(exc), "danger")
                return redirect(
                    url_for("platform_admin.institute_detail", institute_id=institute_id)
                )
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


def _active_plans(conn):
    return conn.execute(
        "SELECT * FROM subscription_plans WHERE is_active = 1 ORDER BY sort_order, name"
    ).fetchall()


def _onboarding_or_404(conn, institute_id):
    onboarding = conn.execute(
        "SELECT * FROM institute_onboarding WHERE institute_id = ?",
        (institute_id,),
    ).fetchone()
    if not onboarding:
        abort(404)
    return onboarding


def _onboarding_checklist(conn, institute_id):
    institute = _institute_or_404(conn, institute_id)
    checks = {
        "identity": bool(institute["name"] and institute["slug"]),
        "subscription": bool(
            conn.execute(
                """SELECT id FROM institute_subscriptions
                   WHERE institute_id = ?
                     AND status IN ('active', 'trialing', 'grace')""",
                (institute_id,),
            ).fetchone()
        ),
        "domain": bool(
            conn.execute(
                """SELECT id FROM institute_domains
                   WHERE institute_id = ? AND is_primary = 1""",
                (institute_id,),
            ).fetchone()
        ),
        "branding": bool(
            conn.execute(
                "SELECT id FROM institute_branding WHERE institute_id = ?",
                (institute_id,),
            ).fetchone()
        ),
        "branch": bool(
            conn.execute(
                "SELECT id FROM branches WHERE institute_id = ? AND is_active = 1",
                (institute_id,),
            ).fetchone()
        ),
        "administrator": bool(
            conn.execute(
                """SELECT im.id FROM institute_memberships im
                   JOIN users u ON u.id = im.user_id AND u.institute_id = im.institute_id
                   WHERE im.institute_id = ? AND im.membership_role = 'institute_admin'
                     AND im.is_active = 1 AND u.is_active = 1""",
                (institute_id,),
            ).fetchone()
        ),
        "settings": bool(
            conn.execute(
                "SELECT id FROM institute_settings WHERE institute_id = ?",
                (institute_id,),
            ).fetchone()
        ),
    }
    checks["ready"] = all(checks.values())
    return checks


@platform_admin_bp.route("/onboarding/new", methods=["GET", "POST"])
@login_required
@platform_owner_required
def onboarding_new():
    """Step 1: create an inactive institute identity and onboarding record."""
    if request.method == "GET":
        return render_template("platform_admin/onboarding.html", step=1)

    conn = get_conn()
    try:
        values, error = _validate_institute_form(conn)
        if error:
            flash(error, "danger")
            return render_template(
                "platform_admin/onboarding.html", step=1, form_data=request.form
            )
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO institutes (
                name, short_name, slug, status, timezone, locale,
                currency_code, created_at, updated_at
            ) VALUES (?, ?, ?, 'onboarding', ?, ?, ?, ?, ?)
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
        cur.execute(
            """
            INSERT INTO institute_onboarding (
                institute_id, status, current_step, created_by, created_at, updated_at
            ) VALUES (?, 'draft', 2, ?, ?, ?)
            """,
            (institute_id, session.get("user_id"), now, now),
        )
        conn.commit()
        flash("Institute identity saved. Assign its subscription plan.", "success")
        return redirect(
            url_for("platform_admin.onboarding_step", institute_id=institute_id, step=2)
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@platform_admin_bp.route(
    "/onboarding/<int:institute_id>/step/<int:step>", methods=["GET", "POST"]
)
@login_required
@platform_owner_required
def onboarding_step(institute_id, step):
    if step < 2 or step > 9:
        abort(404)
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        onboarding = _onboarding_or_404(conn, institute_id)
        plans = _active_plans(conn)
        subscription = conn.execute(
            """SELECT s.*, p.code AS plan_code, p.name AS plan_name
               FROM institute_subscriptions s
               JOIN subscription_plans p ON p.id = s.plan_id
               WHERE s.institute_id = ?""",
            (institute_id,),
        ).fetchone()
        branding = conn.execute(
            "SELECT * FROM institute_branding WHERE institute_id = ?", (institute_id,)
        ).fetchone()
        domain = conn.execute(
            """SELECT * FROM institute_domains
               WHERE institute_id = ? AND is_primary = 1 ORDER BY id LIMIT 1""",
            (institute_id,),
        ).fetchone()
        branches = conn.execute(
            "SELECT * FROM branches WHERE institute_id = ? ORDER BY branch_name",
            (institute_id,),
        ).fetchall()
        admins = conn.execute(
            """SELECT u.* FROM users u
               JOIN institute_memberships im
                 ON im.user_id = u.id AND im.institute_id = u.institute_id
               WHERE u.institute_id = ? AND im.membership_role = 'institute_admin'""",
            (institute_id,),
        ).fetchall()
        settings = conn.execute(
            "SELECT * FROM institute_settings WHERE institute_id = ?", (institute_id,)
        ).fetchone()
        integrations = conn.execute(
            "SELECT * FROM institute_integrations WHERE institute_id = ? ORDER BY integration_type",
            (institute_id,),
        ).fetchall()

        if request.method == "POST":
            now = _now()
            if step == 2:
                plan_id = request.form.get("plan_id", type=int)
                plan = conn.execute(
                    "SELECT * FROM subscription_plans WHERE id = ? AND is_active = 1",
                    (plan_id,),
                ).fetchone()
                if not plan:
                    flash("Choose an active subscription plan.", "danger")
                    return redirect(request.url)
                status = request.form.get("subscription_status", "trialing")
                if status not in {"trialing", "active"}:
                    status = "trialing"
                trial_days = max(0, min(request.form.get("trial_days", 14, type=int), 90))
                trial_end = (
                    (datetime.now() + timedelta(days=trial_days)).isoformat(timespec="seconds")
                    if status == "trialing" and trial_days
                    else None
                )
                conn.execute(
                    """
                    INSERT INTO institute_subscriptions (
                        institute_id, plan_id, status, starts_at, trial_ends_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE plan_id = VALUES(plan_id),
                        status = VALUES(status), trial_ends_at = VALUES(trial_ends_at),
                        updated_at = VALUES(updated_at)
                    """,
                    (institute_id, plan_id, status, now, trial_end, now, now),
                )
            elif step == 3:
                hostname = normalize_hostname(request.form.get("hostname", ""))
                if not hostname:
                    flash("A primary hostname is required.", "danger")
                    return redirect(request.url)
                owner = conn.execute(
                    "SELECT institute_id FROM institute_domains WHERE hostname = ?",
                    (hostname,),
                ).fetchone()
                if owner and int(owner["institute_id"]) != institute_id:
                    flash("That hostname belongs to another institute.", "danger")
                    return redirect(request.url)
                domain_status, verified_at = _domain_activation(hostname)
                current_primary = conn.execute(
                    """SELECT * FROM institute_domains
                       WHERE institute_id = ? AND is_primary = 1
                       ORDER BY id LIMIT 1""",
                    (institute_id,),
                ).fetchone()
                hostname_changed = (
                    not current_primary or current_primary["hostname"] != hostname
                )
                if domain_status == "active":
                    token, record_name = None, None
                elif hostname_changed:
                    token, record_name = _new_domain_challenge(hostname)
                else:
                    token = current_primary["verification_token"]
                    record_name = current_primary["verification_record_name"]
                if current_primary:
                    conn.execute(
                        """UPDATE institute_domains
                           SET hostname = ?, status = ?, verified_at = ?,
                               verification_token = ?, verification_record_name = ?,
                               verification_last_checked_at = NULL,
                               verification_message = NULL, updated_at = ?
                           WHERE id = ? AND institute_id = ?""",
                        (
                            hostname, domain_status, verified_at,
                            token, record_name, now,
                            current_primary["id"], institute_id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO institute_domains (
                            institute_id, hostname, domain_type, is_primary, status,
                            verified_at, verification_token, verification_record_name,
                            created_at, updated_at
                        ) VALUES (?, ?, 'custom', 1, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            institute_id, hostname, domain_status, verified_at,
                            token, record_name, now, now,
                        ),
                    )
            elif step == 4:
                try:
                    logo_path = _save_brand_file(
                        institute_id, "logo", "logos",
                        branding["logo_path"] if branding else None,
                    )
                    favicon_path = _save_brand_file(
                        institute_id, "favicon", "favicons",
                        branding["favicon_path"] if branding else None,
                    )
                except ValueError as exc:
                    flash(str(exc), "danger")
                    return redirect(request.url)
                conn.execute(
                    """
                    UPDATE institute_branding SET
                        display_name = ?, short_name = ?, tagline = ?,
                        primary_color = ?, secondary_color = ?, logo_path = ?,
                        favicon_path = ?, email = ?, phone = ?, website = ?, updated_at = ?
                    WHERE institute_id = ?
                    """,
                    (
                        request.form.get("display_name", "").strip() or institute["name"],
                        request.form.get("short_name", "").strip() or institute["short_name"],
                        request.form.get("tagline", "").strip(),
                        request.form.get("primary_color", "#2563EB"),
                        request.form.get("secondary_color", "#16A34A"),
                        logo_path, favicon_path,
                        request.form.get("email", "").strip(),
                        request.form.get("phone", "").strip(),
                        request.form.get("website", "").strip(),
                        now, institute_id,
                    ),
                )
            elif step == 5:
                values = _branch_form_values()
                if not values["branch_name"] or not values["branch_code"]:
                    flash("Branch name and code are required.", "danger")
                    return redirect(request.url)
                lock_and_check_limit(conn, institute_id, "branches")
                conn.execute(
                    """
                    INSERT INTO branches (
                        institute_id, branch_name, branch_code, address, is_active,
                        no_of_computers, opening_time, closing_time, created_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        institute_id, values["branch_name"], values["branch_code"],
                        values["address"], values["no_of_computers"],
                        values["opening_time"], values["closing_time"], now,
                    ),
                )
            elif step == 6:
                full_name = request.form.get("full_name", "").strip()
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                branch_id = request.form.get("branch_id", type=int)
                if not full_name or not username or not password:
                    flash("Name, username and password are required.", "danger")
                    return redirect(request.url)
                if branch_id and not conn.execute(
                    "SELECT id FROM branches WHERE id = ? AND institute_id = ?",
                    (branch_id, institute_id),
                ).fetchone():
                    abort(400)
                lock_and_check_limit(conn, institute_id, "staff")
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO users (
                        institute_id, full_name, username, password_hash, role,
                        platform_role, branch_id, can_view_all_branches, is_active,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'admin', NULL, ?, 1, 1, ?, ?)
                    """,
                    (
                        institute_id, full_name, username,
                        generate_password_hash(password), branch_id, now, now,
                    ),
                )
                user_id = cur.lastrowid
                cur.execute(
                    """
                    INSERT INTO institute_memberships (
                        institute_id, user_id, membership_role, is_active,
                        created_at, updated_at
                    ) VALUES (?, ?, 'institute_admin', 1, ?, ?)
                    """,
                    (institute_id, user_id, now, now),
                )
            elif step == 7:
                conn.execute(
                    """
                    UPDATE institute_settings SET
                        invoice_prefix = ?, receipt_prefix = ?, student_prefix = ?,
                        certificate_prefix = ?, date_format = ?, updated_at = ?
                    WHERE institute_id = ?
                    """,
                    (
                        request.form.get("invoice_prefix", "INV").strip() or "INV",
                        request.form.get("receipt_prefix", "RCP").strip() or "RCP",
                        request.form.get("student_prefix", "STU").strip() or "STU",
                        request.form.get("certificate_prefix", "CERT").strip() or "CERT",
                        request.form.get("date_format", "DD-MMM-YYYY").strip(),
                        now, institute_id,
                    ),
                )
            elif step == 8:
                for integration_type in ("sms", "email", "storage"):
                    ready = request.form.get(f"{integration_type}_ready") == "1"
                    provider = request.form.get(
                        f"{integration_type}_provider", ""
                    ).strip() or "not-configured"
                    conn.execute(
                        """
                        INSERT INTO institute_integrations (
                            institute_id, integration_type, provider, status,
                            configuration_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE provider = VALUES(provider),
                            status = VALUES(status),
                            configuration_json = VALUES(configuration_json),
                            updated_at = VALUES(updated_at)
                        """,
                        (
                            institute_id, integration_type, provider,
                            "ready" if ready else "inactive",
                            json.dumps({"readiness_confirmed": ready}), now, now,
                        ),
                    )
            elif step == 9:
                checks = _onboarding_checklist(conn, institute_id)
                conn.execute(
                    "UPDATE institute_onboarding SET checklist_json = ?, updated_at = ? WHERE institute_id = ?",
                    (json.dumps(checks), now, institute_id),
                )

            next_step = min(step + 1, 9)
            conn.execute(
                """UPDATE institute_onboarding
                   SET current_step = GREATEST(current_step, ?), updated_at = ?
                   WHERE institute_id = ?""",
                (next_step, now, institute_id),
            )
            conn.commit()
            clear_tenant_cache()
            clear_company_cache(institute_id)
            return redirect(
                url_for(
                    "platform_admin.onboarding_step",
                    institute_id=institute_id,
                    step=next_step,
                )
            )

        checks = _onboarding_checklist(conn, institute_id) if step == 9 else None
        return render_template(
            "platform_admin/onboarding.html",
            step=step,
            institute=institute,
            onboarding=onboarding,
            plans=plans,
            subscription=subscription,
            branding=branding,
            domain=domain,
            branches=branches,
            admins=admins,
            settings=settings,
            integrations=integrations,
            checks=checks,
        )
    except (PlanLimitExceeded, SubscriptionAccessDenied) as exc:
        conn.rollback()
        flash(str(exc), "danger")
        return redirect(request.url)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@platform_admin_bp.post("/onboarding/<int:institute_id>/activate")
@login_required
@platform_owner_required
def onboarding_activate(institute_id):
    conn = get_conn()
    try:
        _onboarding_or_404(conn, institute_id)
        checks = _onboarding_checklist(conn, institute_id)
        if not checks["ready"]:
            flash("Complete every required activation item first.", "danger")
            return redirect(
                url_for("platform_admin.onboarding_step", institute_id=institute_id, step=9)
            )
        now = _now()
        conn.execute(
            "UPDATE institutes SET status = 'active', updated_at = ? WHERE id = ?",
            (now, institute_id),
        )
        conn.execute(
            """
            UPDATE institute_onboarding SET status = 'completed', current_step = 9,
                checklist_json = ?, completed_by = ?, completed_at = ?, updated_at = ?
            WHERE institute_id = ?
            """,
            (json.dumps(checks), session.get("user_id"), now, now, institute_id),
        )
        conn.commit()
        clear_tenant_cache()
        flash("Institute activated successfully.", "success")
        return redirect(
            url_for("platform_admin.institute_detail", institute_id=institute_id)
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@platform_admin_bp.route(
    "/institutes/<int:institute_id>/subscription", methods=["GET", "POST"]
)
@login_required
@platform_owner_required
def institute_subscription(institute_id):
    conn = get_conn()
    try:
        institute = _institute_or_404(conn, institute_id)
        if request.method == "POST":
            plan_id = request.form.get("plan_id", type=int)
            if not conn.execute(
                "SELECT id FROM subscription_plans WHERE id = ? AND is_active = 1",
                (plan_id,),
            ).fetchone():
                abort(400)

            def optional_nonnegative(name):
                value = request.form.get(name, "").strip()
                if not value:
                    return None
                parsed = int(value)
                if parsed < 0:
                    raise ValueError
                return parsed

            try:
                branch_limit = optional_nonnegative("branch_limit_override")
                staff_limit = optional_nonnegative("staff_limit_override")
                student_limit = optional_nonnegative("student_limit_override")
                storage_mb = optional_nonnegative("storage_limit_mb_override")
            except ValueError:
                flash("Limit overrides must be non-negative whole numbers.", "danger")
                return redirect(request.url)
            features = {
                feature: "1" in request.form.getlist(f"feature_{feature}")
                for feature in (
                    "crm", "students", "finance", "attendance", "reports",
                    "lms", "certificates", "integrations",
                )
            }
            plan = conn.execute(
                "SELECT * FROM subscription_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            _, current_usage = usage_summary(conn, institute_id)
            proposed_limits = {
                "branches": branch_limit if branch_limit is not None else plan["branch_limit"],
                "staff": staff_limit if staff_limit is not None else plan["staff_limit"],
                "students": student_limit if student_limit is not None else plan["student_limit"],
                "storage": (
                    storage_mb * 1024 * 1024
                    if storage_mb is not None else plan["storage_limit_bytes"]
                ),
            }
            has_phase9_onboarding = conn.execute(
                "SELECT id FROM institute_onboarding WHERE institute_id = ?",
                (institute_id,),
            ).fetchone()
            if proposed_limits["storage"] is not None and not has_phase9_onboarding:
                flash(
                    "This legacy institute must complete a storage inventory "
                    "reconciliation before a finite storage limit can be applied.",
                    "danger",
                )
                return redirect(request.url)
            over_limit = [
                resource for resource, limit in proposed_limits.items()
                if limit is not None and current_usage[resource] > int(limit)
            ]
            if over_limit:
                flash(
                    "Cannot apply limits below current usage: "
                    + ", ".join(over_limit) + ".",
                    "danger",
                )
                return redirect(request.url)
            now = _now()
            conn.execute(
                """
                UPDATE institute_subscriptions SET
                    plan_id = ?, branch_limit_override = ?,
                    staff_limit_override = ?, student_limit_override = ?,
                    storage_limit_bytes_override = ?, feature_overrides_json = ?,
                    updated_at = ?
                WHERE institute_id = ?
                """,
                (
                    plan_id, branch_limit, staff_limit, student_limit,
                    storage_mb * 1024 * 1024 if storage_mb is not None else None,
                    json.dumps(features), now, institute_id,
                ),
            )
            conn.commit()
            flash("Subscription and limits updated.", "success")
            return redirect(
                url_for("platform_admin.institute_subscription", institute_id=institute_id)
            )
        entitlement, usage = usage_summary(conn, institute_id)
        subscription = conn.execute(
            "SELECT * FROM institute_subscriptions WHERE institute_id = ?",
            (institute_id,),
        ).fetchone()
        return render_template(
            "platform_admin/subscription.html",
            institute=institute,
            subscription=subscription,
            entitlement=entitlement,
            usage=usage,
            plans=_active_plans(conn),
        )
    finally:
        conn.close()


@platform_admin_bp.post("/institutes/<int:institute_id>/subscription/lifecycle")
@login_required
@platform_owner_required
def institute_subscription_lifecycle(institute_id):
    action = request.form.get("action", "")
    if action not in {"grace", "suspend", "reactivate"}:
        abort(400)
    conn = get_conn()
    try:
        _institute_or_404(conn, institute_id)
        now_dt = datetime.now()
        now = now_dt.isoformat(timespec="seconds")
        if action == "grace":
            days = max(1, min(request.form.get("grace_days", 7, type=int), 90))
            conn.execute(
                """UPDATE institute_subscriptions
                   SET status = 'grace', grace_ends_at = ?, suspended_at = NULL,
                       suspension_reason = NULL, updated_at = ?
                   WHERE institute_id = ?""",
                (
                    (now_dt + timedelta(days=days)).isoformat(timespec="seconds"),
                    now, institute_id,
                ),
            )
            conn.execute(
                "UPDATE institutes SET status = 'active', updated_at = ? WHERE id = ?",
                (now, institute_id),
            )
        elif action == "suspend":
            reason = request.form.get("reason", "").strip()
            if not reason:
                flash("A suspension reason is required.", "danger")
                return redirect(
                    url_for("platform_admin.institute_subscription", institute_id=institute_id)
                )
            conn.execute(
                """UPDATE institute_subscriptions
                   SET status = 'suspended', suspended_at = ?,
                       suspension_reason = ?, updated_at = ?
                   WHERE institute_id = ?""",
                (now, reason, now, institute_id),
            )
            conn.execute(
                "UPDATE institutes SET status = 'suspended', updated_at = ? WHERE id = ?",
                (now, institute_id),
            )
        else:
            conn.execute(
                """UPDATE institute_subscriptions
                   SET status = 'active', grace_ends_at = NULL, suspended_at = NULL,
                       suspension_reason = NULL, updated_at = ?
                   WHERE institute_id = ?""",
                (now, institute_id),
            )
            conn.execute(
                "UPDATE institutes SET status = 'active', updated_at = ? WHERE id = ?",
                (now, institute_id),
            )
        conn.commit()
        clear_tenant_cache()
        flash(f"Institute subscription updated: {action}.", "success")
        return redirect(
            url_for("platform_admin.institute_subscription", institute_id=institute_id)
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
