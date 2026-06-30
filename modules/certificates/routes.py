import datetime
# pyrefly: ignore [missing-import]
from flask import render_template, request, redirect, url_for, session, flash, jsonify, abort, current_app
from db import get_conn
from modules.core.utils import lms_content_manager_required
from . import certificates_bp
from .services import EligibilityService, CertificateService
from .verifier import verify_certificate_number
from .generator import get_certificate_render_data
from .audit import log_certificate_action

# ---------------------------------------------------------------------------
# Student Portal Auth Helper
# ---------------------------------------------------------------------------
def _student_required():
    if "student_id" not in session:
        return True, redirect(url_for("students.login"))
    return False, None

def _get_client_info():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    ua = request.headers.get('User-Agent', '')
    return ip, ua

# ---------------------------------------------------------------------------
# Public Verification Page
# ---------------------------------------------------------------------------
@certificates_bp.route("/verify-certificate", methods=["GET"])
@certificates_bp.route("/verify-certificate/", methods=["GET"])
@certificates_bp.route("/verify-certificate/<cert_no>", methods=["GET"])
def verify_certificate(cert_no=None):
    if not cert_no:
        return render_template("certificates/verify.html", cert=None, cert_no=None)
    conn = get_conn()
    try:
        data = verify_certificate_number(conn, cert_no)
        if data:
            ip, ua = _get_client_info()
            # Log verification check in audit log
            log_certificate_action(
                conn, data["certificate_id"], "Verified",
                performed_by=None,
                ip_address=ip,
                user_agent=ua,
                reason="Public certificate verification page queried"
            )
            conn.commit()
        return render_template("certificates/verify.html", cert=data, cert_no=cert_no)
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# API Log Action (Downloaded/Printed)
# ---------------------------------------------------------------------------
@certificates_bp.route("/api/certificates/<int:cert_id>/log-action", methods=["POST"])
def api_log_action(cert_id):
    action = request.json.get("action")
    if action not in ("Downloaded", "Printed", "Viewed"):
        return jsonify({"success": False, "error": "Invalid action"}), 400

    conn = get_conn()
    try:
        # Check permissions: caller must be admin OR the student mapped to the cert
        cert = conn.execute("SELECT student_id FROM certificates WHERE id = ?", (cert_id,)).fetchone()
        if not cert:
            return jsonify({"success": False, "error": "Certificate not found"}), 404

        is_admin = session.get("user_id") is not None and session.get("role") in ("admin", "staff")
        is_student = session.get("student_id") == cert["student_id"]

        if not is_admin and not is_student:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        ip, ua = _get_client_info()
        user_id = session.get("user_id")
        
        log_certificate_action(
            conn, cert_id, action,
            performed_by=user_id,
            ip_address=ip,
            user_agent=ua
        )
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Clean Render (A4 aspect-ratio sheet representation)
# ---------------------------------------------------------------------------
@certificates_bp.route("/student/certificates/render/<int:cert_id>", methods=["GET"])
def render_certificate(cert_id):
    conn = get_conn()
    try:
        # Fetch certificate details
        cert = conn.execute("SELECT student_id, certificate_number FROM certificates WHERE id = ?", (cert_id,)).fetchone()
        if not cert:
            abort(404)

        # Enforce security context
        is_admin = session.get("user_id") is not None and session.get("role") in ("admin", "staff")
        is_student = session.get("student_id") == cert["student_id"]

        if not is_admin and not is_student:
            abort(403)

        base_url = request.url_root
        data = get_certificate_render_data(conn.cursor(), cert_id, base_url)
        if not data:
            abort(404)

        # Fetch settings to check overrides
        settings = EligibilityService.get_settings(conn.cursor())

        return render_template(
            "certificates/view.html",
            cert=data["certificate"],
            template=data["template"],
            month=data["completion_month"],
            year=data["completion_year"],
            qr_base64=data["qr_base64"],
            overlay_styles=data["overlay_styles"],
            settings=settings,
            standalone=True
        )
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Student Portal Page
# ---------------------------------------------------------------------------
@certificates_bp.route("/student/certificates", methods=["GET"])
def student_certificates_list():
    redirect_required, response = _student_required()
    if redirect_required:
        return response

    student_id = session["student_id"]
    conn = get_conn()
    try:
        # Before showing page, execute self-healing eligibility checks on student programs
        # to auto-generate any missing eligible certificates.
        cur = conn.cursor()
        settings = EligibilityService.get_settings(cur)
        
        if settings.get("auto_generate_certificates", 1) == 1:
            # Query courses for which student has exam attempts
            invoiced_courses = cur.execute(
                """
                SELECT DISTINCT c.id
                FROM courses c
                WHERE EXISTS (
                    SELECT 1 FROM lms_final_exam_attempts a
                    WHERE a.student_id = ? AND a.course_id = c.id
                )
                """,
                (student_id,)
            ).fetchall()
            
            for c in invoiced_courses:
                try:
                    # Attempt transactional issuance (will skip if already exists or not eligible)
                    CertificateService.issue_certificate(
                        conn, student_id, c["id"],
                        performed_by=None,
                        ip_address="System Auto",
                        user_agent="System Auto-Generation Flow"
                    )
                    conn.commit()
                except Exception as ex:
                    # Rollback and proceed safely (non-blocking)
                    conn.rollback()

        # Fetch student's issued certificates
        certs = conn.execute(
            """
            SELECT c.*, t.background_filename, cr.course_name
            FROM certificates c
            JOIN certificate_templates t ON t.id = c.template_id
            JOIN courses cr ON cr.id = c.course_id
            WHERE c.student_id = ?
            ORDER BY c.issue_date DESC, c.id DESC
            """,
            (student_id,)
        ).fetchall()
        
        # Load Company Info
        company = conn.execute("SELECT * FROM company_profile WHERE id = 1").fetchone()
        
        return render_template("certificates/my_certificates.html", certs=certs, company=company)
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Student Certificate Full View
# ---------------------------------------------------------------------------
@certificates_bp.route("/student/certificates/view/<int:cert_id>", methods=["GET"])
def student_certificate_view(cert_id):
    conn = get_conn()
    try:
        cert = conn.execute("SELECT student_id, certificate_number FROM certificates WHERE id = ?", (cert_id,)).fetchone()
        if not cert:
            abort(404)

        # Enforce security context: must be admin OR the student mapped to the cert
        is_admin = session.get("user_id") is not None and session.get("role") in ("admin", "staff")
        is_student = session.get("student_id") == cert["student_id"]

        if not is_admin and not is_student:
            if "student_id" not in session and "user_id" not in session:
                return redirect(url_for("students.login"))
            abort(403)

        # Log viewing action
        ip, ua = _get_client_info()
        log_certificate_action(
            conn, cert_id, "Viewed",
            performed_by=session.get("user_id"),
            ip_address=ip,
            user_agent=ua
        )
        conn.commit()

        # Renders the download envelope template (which contains standard header/footer controls)
        base_url = request.url_root
        data = get_certificate_render_data(conn.cursor(), cert_id, base_url)
        settings = EligibilityService.get_settings(conn.cursor())
        company = conn.execute("SELECT * FROM company_profile WHERE id = 1").fetchone()

        layout = "base.html" if is_admin else "students/base.html"

        return render_template(
            "certificates/view.html",
            cert=data["certificate"],
            template=data["template"],
            month=data["completion_month"],
            year=data["completion_year"],
            qr_base64=data["qr_base64"],
            overlay_styles=data["overlay_styles"],
            settings=settings,
            company=company,
            standalone=False,
            layout=layout
        )
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Admin Panel - Certificate Dashboard & List
# ---------------------------------------------------------------------------
@certificates_bp.route("/lms_admin/certificates", methods=["GET"])
@lms_content_manager_required
def admin_list():
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # 1. Fetch search filters
        student_filter = request.args.get("student", "").strip()
        course_filter = request.args.get("course", "").strip()
        branch_filter = request.args.get("branch", "").strip()
        status_filter = request.args.get("status", "").strip()
        
        # Build dynamic query
        query_parts = ["SELECT c.*, cr.course_name, s.full_name AS student_name, s.student_code, b.branch_name FROM certificates c JOIN students s ON s.id = c.student_id JOIN courses cr ON cr.id = c.course_id LEFT JOIN branches b ON b.id = s.branch_id"]
        where_parts = []
        params = []
        
        if student_filter:
            where_parts.append("(s.full_name LIKE ? OR s.student_code LIKE ?)")
            params.extend([f"%{student_filter}%", f"%{student_filter}%"])
        if course_filter:
            where_parts.append("cr.course_name LIKE ?")
            params.append(f"%{course_filter}%")
        if branch_filter:
            where_parts.append("b.branch_name LIKE ?")
            params.append(f"%{branch_filter}%")
        if status_filter:
            where_parts.append("c.status = ?")
            params.append(status_filter)
            
        if where_parts:
            query_parts.append("WHERE " + " AND ".join(where_parts))
            
        query_parts.append("ORDER BY c.issue_date DESC, c.id DESC")
        certs = cur.execute(" ".join(query_parts), params).fetchall()

        # 2. Fetch metrics
        total_issued = cur.execute("SELECT COUNT(*) AS count FROM certificates").fetchone()["count"]
        
        today_date = datetime.date.today().isoformat()
        issued_today = cur.execute("SELECT COUNT(*) AS count FROM certificates WHERE issue_date = ?", (today_date,)).fetchone()["count"]
        
        this_month_prefix = today_date[:7] + "%"
        issued_month = cur.execute("SELECT COUNT(*) AS count FROM certificates WHERE issue_date LIKE ?", (this_month_prefix,)).fetchone()["count"]
        
        revoked_count = cur.execute("SELECT COUNT(*) AS count FROM certificates WHERE status = 'Revoked'").fetchone()["count"]
        reissued_count = cur.execute("SELECT COUNT(*) AS count FROM certificates WHERE status = 'Re-issued'").fetchone()["count"]
        
        # Operational verification metrics from audit log
        verifications = cur.execute("SELECT COUNT(*) AS count FROM certificate_audit_logs WHERE action = 'Verified'").fetchone()["count"]
        downloads = cur.execute("SELECT COUNT(*) AS count FROM certificate_audit_logs WHERE action = 'Downloaded'").fetchone()["count"]
        prints = cur.execute("SELECT COUNT(*) AS count FROM certificate_audit_logs WHERE action = 'Printed'").fetchone()["count"]
        views = cur.execute("SELECT COUNT(*) AS count FROM certificate_audit_logs WHERE action = 'Viewed'").fetchone()["count"]

        # Fetch branches and courses for dropdown filters
        branches = cur.execute("SELECT branch_name FROM branches WHERE is_active = 1").fetchall()
        courses = cur.execute("SELECT course_name FROM courses WHERE is_active = 1").fetchall()

        return render_template(
            "certificates/admin_list.html",
            certs=certs,
            total_issued=total_issued,
            issued_today=issued_today,
            issued_month=issued_month,
            revoked_count=revoked_count,
            reissued_count=reissued_count,
            verifications=verifications,
            downloads=downloads,
            prints=prints,
            views=views,
            branches=branches,
            courses=courses
        )
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Admin Panel - Issue Certificate Screen
# ---------------------------------------------------------------------------
@certificates_bp.route("/lms_admin/certificates/issue", methods=["GET", "POST"])
@lms_content_manager_required
def admin_issue():
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        if request.method == "POST":
            student_id = request.form.get("student_id", type=int)
            course_id = request.form.get("course_id", type=int)
            grade = request.form.get("grade", "").strip() or None
            completion_date = request.form.get("completion_date", "").strip() or None
            notes = request.form.get("notes", "").strip() or None
            force_issue = request.form.get("force_issue") == "1"
            
            if not student_id or not course_id:
                flash("Please select both a student and an invoiced course.", "danger")
                return redirect(url_for("certificates.admin_issue"))

            try:
                performed_by = session.get("user_id")
                ip, ua = _get_client_info()
                
                cert_no = CertificateService.issue_certificate(
                    conn, student_id, course_id,
                    grade=grade,
                    completion_date=completion_date,
                    notes=notes,
                    performed_by=performed_by,
                    ip_address=ip,
                    user_agent=ua,
                    force=force_issue
                )
                conn.commit()
                flash(f"Certificate successfully issued! Number: {cert_no}", "success")
                return redirect(url_for("certificates.admin_list"))
            except Exception as e:
                conn.rollback()
                flash(f"Error issuing certificate: {str(e)}", "danger")
                return redirect(url_for("certificates.admin_issue", student_id=student_id, course_id=course_id))

        selected_student_id = request.args.get("student_id", type=int)
        selected_course_id = request.args.get("course_id", type=int)

        # Handle GET request: list students eligible or search
        # We fetch active students enrolled in batches
        students = cur.execute("SELECT id, student_code, full_name FROM students WHERE status = 'active' ORDER BY full_name").fetchall()
        
        # Fetch invoiced courses for the selected student
        courses_list = []
        if selected_student_id:
            courses_list = cur.execute(
                """
                SELECT DISTINCT c.id, c.course_name
                FROM courses c
                JOIN invoice_items ii ON ii.course_id = c.id
                JOIN invoices i ON i.id = ii.invoice_id
                WHERE i.student_id = ?
                  AND i.status != 'cancelled'
                ORDER BY c.course_name
                """,
                (selected_student_id,)
            ).fetchall()
        
        eligibility = None
        if selected_student_id and selected_course_id:
            is_eligible, reasons, details = EligibilityService.check_eligibility(cur, selected_student_id, selected_course_id)
            eligibility = {
                "is_eligible": is_eligible,
                "reasons": reasons,
                "details": details
            }

        return render_template(
            "certificates/admin_issue.html",
            students=students,
            courses_list=courses_list,
            selected_student_id=selected_student_id,
            selected_course_id=selected_course_id,
            eligibility=eligibility
        )
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Admin Actions - Re-issue & Revoke
# ---------------------------------------------------------------------------
@certificates_bp.route("/lms_admin/certificates/<int:cert_id>/reissue", methods=["POST"])
@lms_content_manager_required
def admin_reissue(cert_id):
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Re-issuance requires a reason.", "danger")
        return redirect(url_for("certificates.admin_list"))

    conn = get_conn()
    try:
        performed_by = session.get("user_id")
        ip, ua = _get_client_info()
        
        new_cert_no = CertificateService.reissue_certificate(
            conn, cert_id,
            reason=reason,
            performed_by=performed_by,
            ip_address=ip,
            user_agent=ua
        )
        conn.commit()
        flash(f"Certificate successfully reissued. New Number: {new_cert_no}", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error reissuing certificate: {str(e)}", "danger")
    finally:
        conn.close()
    return redirect(url_for("certificates.admin_list"))


@certificates_bp.route("/lms_admin/certificates/<int:cert_id>/revoke", methods=["POST"])
@lms_content_manager_required
def admin_revoke(cert_id):
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Revocation requires a reason.", "danger")
        return redirect(url_for("certificates.admin_list"))

    conn = get_conn()
    try:
        performed_by = session.get("user_id")
        ip, ua = _get_client_info()
        
        CertificateService.revoke_certificate(
            conn, cert_id,
            reason=reason,
            performed_by=performed_by,
            ip_address=ip,
            user_agent=ua
        )
        conn.commit()
        flash("Certificate successfully revoked.", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Error revoking certificate: {str(e)}", "danger")
    finally:
        conn.close()
    return redirect(url_for("certificates.admin_list"))

# ---------------------------------------------------------------------------
# Admin - Manage Templates & settings
# ---------------------------------------------------------------------------
@certificates_bp.route("/lms_admin/certificates/settings", methods=["GET", "POST"])
@lms_content_manager_required
def admin_settings():
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        if request.method == "POST":
            prefix = request.form.get("prefix", "GIT").strip().upper()
            default_template_id = request.form.get("default_template_id", type=int)
            pass_percentage = request.form.get("default_pass_percentage", type=float, default=50.0)
            auto_generate = 1 if request.form.get("auto_generate_certificates") else 0
            allow_manual = 1 if request.form.get("allow_manual_issue") else 0
            allow_reissue = 1 if request.form.get("allow_reissue") else 0
            show_photo = 1 if request.form.get("show_student_photo") else 0
            show_grade = 1 if request.form.get("show_grade") else 0
            enable_verification = 1 if request.form.get("enable_certificate_verification") else 0
            year_format = request.form.get("year_format", "YYYY")
            sequence_length = request.form.get("sequence_length", type=int, default=6)

            cur.execute(
                """
                UPDATE certificate_settings
                SET prefix = ?, default_template_id = ?, default_pass_percentage = ?,
                    auto_generate_certificates = ?, allow_manual_issue = ?, allow_reissue = ?,
                    show_student_photo = ?, show_grade = ?, enable_certificate_verification = ?,
                    year_format = ?, sequence_length = ?, updated_at = datetime('now')
                WHERE id = 1
                """,
                (prefix, default_template_id, pass_percentage, auto_generate, allow_manual, allow_reissue,
                 show_photo, show_grade, enable_verification, year_format, sequence_length)
            )
            conn.commit()
            flash("Settings updated successfully.", "success")
            return redirect(url_for("certificates.admin_settings"))

        settings = EligibilityService.get_settings(cur)
        templates = cur.execute("SELECT id, template_name, template_code FROM certificate_templates WHERE is_active = 1").fetchall()
        
        return render_template("certificates/admin_settings.html", settings=settings, templates=templates)
    finally:
        conn.close()


@certificates_bp.route("/lms_admin/certificates/templates", methods=["GET", "POST"])
@lms_content_manager_required
def admin_templates():
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        if request.method == "POST":
            # Action: Create or edit a template or field positioning
            action = request.form.get("action_type")
            if action == "create_template":
                name = request.form.get("template_name", "").strip()
                code = request.form.get("template_code", "").strip().upper()
                sig_name = request.form.get("authorized_signature_name", "").strip()
                sig_desig = request.form.get("authorized_signature_designation", "").strip()
                
                if not name or not code or not sig_name or not sig_desig:
                    flash("All template fields are required.", "danger")
                    return redirect(url_for("certificates.admin_templates"))

                # Handle background image file upload
                bg_filename = "default.png"
                bg_file = request.files.get("background_image")
                if bg_file and bg_file.filename:
                    import os
                    from werkzeug.utils import secure_filename
                    bg_filename = secure_filename(bg_file.filename)
                    dest_dir = os.path.join(current_app.root_path, 'static', 'images', 'certificate_templates')
                    os.makedirs(dest_dir, exist_ok=True)
                    bg_file.save(os.path.join(dest_dir, bg_filename))

                orientation = request.form.get("orientation", "Landscape").strip()
                version_row = cur.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM certificate_templates WHERE template_name = ?", (name,)).fetchone()
                version = version_row["next_ver"]

                cur.execute(
                    """
                    INSERT INTO certificate_templates (
                        template_name, template_code, background_filename, version, effective_from, is_default, is_active,
                        authorized_signature_name, authorized_signature_designation, orientation, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, ?, datetime('now'))
                    """,
                    (name, code, bg_filename, version, datetime.date.today().isoformat(), sig_name, sig_desig, orientation)
                )
                template_id = cur.lastrowid
                
                # Copy standard coordinate mapping into the new fields
                default_fields = [
                    ('student_photo', '780px', '140px', '120px', '150px', 'Arial', '14px', 'normal', '#000000', 'left'),
                    ('certificate_number', '100px', '60px', None, None, 'Courier New', '14px', 'bold', '#1e293b', 'left'),
                    ('issue_date', '150px', '620px', None, None, 'Arial', '14px', 'normal', '#1e293b', 'left'),
                    ('student_name', '50%', '320px', '80%', None, 'Georgia', '32px', 'bold', '#1e3b8b', 'center'),
                    ('student_reg', '50%', '375px', '80%', None, 'Arial', '14px', 'normal', '#475569', 'center'),
                    ('course_name', '50%', '450px', '80%', None, 'Arial', '28px', 'bold', '#b45309', 'center'),
                    ('course_duration', '50%', '500px', '80%', None, 'Arial', '16px', 'normal', '#475569', 'center'),
                    ('grade', '50%', '535px', '80%', None, 'Arial', '18px', 'bold', '#1e293b', 'center'),
                    ('completion_date', '50%', '570px', '80%', None, 'Arial', '14px', 'normal', '#475569', 'center'),
                    ('qr_code', '780px', '550px', '100px', '100px', 'Arial', '14px', 'normal', '#000000', 'left')
                ]
                for f in default_fields:
                    cur.execute(
                        """
                        INSERT INTO certificate_template_fields (
                            template_id, field_name, left_position, top_position, width, height, font_family, font_size, font_weight, font_color, text_align, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (template_id, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], datetime.datetime.now().isoformat())
                    )
                conn.commit()
                flash("Template created successfully.", "success")

            elif action == "edit_template":
                template_id = request.form.get("template_id", type=int)
                name = request.form.get("template_name", "").strip()
                code = request.form.get("template_code", "").strip().upper()
                sig_name = request.form.get("authorized_signature_name", "").strip()
                sig_desig = request.form.get("authorized_signature_designation", "").strip()
                
                # Check template
                template = cur.execute("SELECT * FROM certificate_templates WHERE id = ?", (template_id,)).fetchone()
                if not template:
                    flash("Template not found.", "danger")
                    return redirect(url_for("certificates.admin_templates"))
                    
                bg_filename = template["background_filename"]
                bg_file = request.files.get("background_image")
                if bg_file and bg_file.filename:
                    import os
                    from werkzeug.utils import secure_filename
                    bg_filename = secure_filename(bg_file.filename)
                    dest_dir = os.path.join(current_app.root_path, 'static', 'images', 'certificate_templates')
                    os.makedirs(dest_dir, exist_ok=True)
                    bg_file.save(os.path.join(dest_dir, bg_filename))
                    
                sig_filename = template["authorized_signature_image"]
                sig_file = request.files.get("signature_image")
                if sig_file and sig_file.filename:
                    import os
                    from werkzeug.utils import secure_filename
                    sig_filename = secure_filename(sig_file.filename)
                    dest_dir = os.path.join(current_app.root_path, 'static', 'images', 'signatures')
                    os.makedirs(dest_dir, exist_ok=True)
                    sig_file.save(os.path.join(dest_dir, sig_filename))
                    
                seal_filename = template["seal_image"]
                seal_file = request.files.get("seal_image")
                if seal_file and seal_file.filename:
                    import os
                    from werkzeug.utils import secure_filename
                    seal_filename = secure_filename(seal_file.filename)
                    dest_dir = os.path.join(current_app.root_path, 'static', 'images', 'seals')
                    os.makedirs(dest_dir, exist_ok=True)
                    seal_file.save(os.path.join(dest_dir, seal_filename))
                    
                orientation = request.form.get("orientation", "Landscape").strip()

                cur.execute(
                    """
                    UPDATE certificate_templates
                    SET template_name = ?, template_code = ?, background_filename = ?,
                        authorized_signature_name = ?, authorized_signature_designation = ?,
                        authorized_signature_image = ?, seal_image = ?, orientation = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (name, code, bg_filename, sig_name, sig_desig, sig_filename, seal_filename, orientation, template_id)
                )
                conn.commit()
                flash("Template details updated successfully.", "success")
                return redirect(url_for("certificates.admin_templates", selected_id=template_id))

            elif action == "update_coordinates":
                template_id = request.form.get("template_id", type=int)
                field_name = request.form.get("field_name")
                left_pos = request.form.get("left_position", "").strip()
                top_pos = request.form.get("top_position", "").strip()
                width = request.form.get("width", "").strip() or None
                height = request.form.get("height", "").strip() or None
                font_fam = request.form.get("font_family", "Arial").strip()
                font_size = request.form.get("font_size", "14px").strip()
                font_weight = request.form.get("font_weight", "normal").strip()
                font_color = request.form.get("font_color", "#000000").strip()
                align = request.form.get("text_align", "left").strip()
                visible = 1 if request.form.get("is_visible") else 0
                rotation = request.form.get("rotation", type=int, default=0)

                cur.execute(
                    """
                    UPDATE certificate_template_fields
                    SET left_position = ?, top_position = ?, width = ?, height = ?,
                        font_family = ?, font_size = ?, font_weight = ?, font_color = ?,
                        text_align = ?, is_visible = ?, rotation = ?, updated_at = datetime('now')
                    WHERE template_id = ? AND field_name = ?
                    """,
                    (left_pos, top_pos, width, height, font_fam, font_size, font_weight, font_color, align, visible, rotation, template_id, field_name)
                )
                conn.commit()
                flash("Field position coordinates updated successfully.", "success")
                return redirect(url_for("certificates.admin_templates", selected_id=template_id))

        templates = cur.execute("SELECT * FROM certificate_templates ORDER BY template_name, version DESC").fetchall()
        
        selected_template_id = request.args.get("selected_id", type=int)
        if not selected_template_id and templates:
            selected_template_id = templates[0]["id"]
            
        selected_fields = []
        sel_template = None
        if selected_template_id:
            selected_fields = cur.execute("SELECT * FROM certificate_template_fields WHERE template_id = ?", (selected_template_id,)).fetchall()
            sel_template = cur.execute("SELECT * FROM certificate_templates WHERE id = ?", (selected_template_id,)).fetchone()

        return render_template("certificates/admin_templates.html", templates=templates, selected_id=selected_template_id, fields=selected_fields, sel_template=sel_template)
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Admin - Audit History Viewer
# ---------------------------------------------------------------------------
@certificates_bp.route("/lms_admin/certificates/<int:cert_id>/audit", methods=["GET"])
@lms_content_manager_required
def admin_audit(cert_id):
    conn = get_conn()
    try:
        cert = conn.execute("SELECT * FROM certificates WHERE id = ?", (cert_id,)).fetchone()
        if not cert:
            abort(404)
        logs = conn.execute(
            """
            SELECT l.*, u.username AS user_name
            FROM certificate_audit_logs l
            LEFT JOIN users u ON u.id = l.performed_by
            WHERE l.certificate_id = ?
            ORDER BY l.created_at DESC
            """,
            (cert_id,)
        ).fetchall()
        return render_template("certificates/admin_audit.html", cert=cert, logs=logs)
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# API - Drag and Drop Coordinates Auto-saving
# ---------------------------------------------------------------------------
@certificates_bp.route("/lms_admin/certificates/templates/api/save-coordinates", methods=["POST"])
@lms_content_manager_required
def api_save_coordinates():
    data = request.json
    template_id = data.get("template_id")
    field_name = data.get("field_name")
    left_pos = data.get("left_position")
    top_pos = data.get("top_position")
    width = data.get("width")
    height = data.get("height")
    font_size = data.get("font_size")
    
    if not template_id or not field_name:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
        
    conn = get_conn()
    try:
        cur = conn.cursor()
        
        # Build dynamic fields updates
        update_parts = []
        params = []
        if left_pos is not None:
            update_parts.append("left_position = ?")
            params.append(left_pos)
        if top_pos is not None:
            update_parts.append("top_position = ?")
            params.append(top_pos)
        if width is not None:
            update_parts.append("width = ?")
            params.append(width)
        if height is not None:
            update_parts.append("height = ?")
            params.append(height)
        if font_size is not None:
            update_parts.append("font_size = ?")
            params.append(font_size)
            
        if not update_parts:
            return jsonify({"success": True, "info": "No fields to update"})
            
        sql = f"UPDATE certificate_template_fields SET {', '.join(update_parts)}, updated_at = datetime('now') WHERE template_id = ? AND field_name = ?"
        params.extend([template_id, field_name])
        
        cur.execute(sql, params)
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
