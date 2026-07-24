import os
import mimetypes
from io import BytesIO

from flask import Flask, send_file, send_from_directory, session, abort, redirect, url_for, request
from werkzeug.middleware.proxy_fix import ProxyFix
from extensions import csrf, limiter
from config import Config
from db import get_conn
from db import init_db, get_company_profile
from services.storage import get_storage_service
from modules.leads.routes import leads_bp
from modules.billing.routes import billing_bp
from modules.assets.routes import assets_bp
from modules.reports.routes import reports_bp
from modules.import_export.routes import import_export_bp
from modules.baddebt.routes import baddebt_bp
from modules.attendance.routes import attendance_bp
from modules.lms_admin import lms_admin_bp
from modules.exams.routes import exams_bp
from modules.students import students_bp
from modules.website import website_bp
from modules.platform_admin import platform_admin_bp
from modules.core.utils import login_required
from services.tenant_context import init_tenant_context
from datetime import datetime, timedelta, timezone

def format_datetime(value):
    """Jinja2 filter to format ISO datetime to user-friendly format"""
    if not value:
        return ""
    try:
        # Handle ISO format datetime (2026-03-23T12:32:00)
        if 'T' in str(value):
            dt = datetime.fromisoformat(value)
            return dt.strftime("%d-%b-%Y %I:%M %p")  # 23-Mar-2026 12:32 PM
        # Handle date-only format (2026-03-23)
        else:
            dt = datetime.strptime(str(value), "%Y-%m-%d")
            return dt.strftime("%d-%b-%Y")  # 23-Mar-2026
    except (ValueError, AttributeError):
        return str(value)

def to_ist_time(value):
    """Jinja2 filter: convert a UTC datetime string to IST HH:MM (adds +5:30)"""
    if not value:
        return ""
    try:
        if 'T' in str(value):
            dt = datetime.fromisoformat(str(value))
        else:
            dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        ist = dt + timedelta(hours=5, minutes=30)
        return ist.strftime("%I:%M %p")  # e.g. 12:23 PM
    except (ValueError, AttributeError):
        return str(value)[11:16]

IST = timezone(timedelta(hours=5, minutes=30))

def format_ist_datetime(value, output_format=None):
    """Convert a stored UTC datetime to IST with an optional strftime format."""
    if not value:
        return ""

    raw = str(value).strip()
    parsed = None

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if not parsed:
        return raw

    if len(raw) <= 10:
        return parsed.strftime(output_format or "%d-%m-%Y")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(IST)
    return parsed.strftime(output_format or "%d-%m-%Y %I:%M %p")

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    Config.validate()
    if any((Config.PROXY_FIX_X_FOR, Config.PROXY_FIX_X_PROTO, Config.PROXY_FIX_X_HOST)):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=Config.PROXY_FIX_X_FOR,
            x_proto=Config.PROXY_FIX_X_PROTO,
            x_host=Config.PROXY_FIX_X_HOST,
        )

    csrf.init_app(app)
    limiter.init_app(app)

    init_db()

    from modules.core.routes import core_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(website_bp)
    app.register_blueprint(leads_bp, url_prefix="/leads")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(assets_bp, url_prefix="/assets")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(import_export_bp, url_prefix="/import-export")
    app.register_blueprint(baddebt_bp, url_prefix="/baddebt")
    app.register_blueprint(attendance_bp, url_prefix="/attendance")
    app.register_blueprint(lms_admin_bp)
    app.register_blueprint(exams_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(platform_admin_bp)
    from modules.certificates.routes import certificates_bp
    app.register_blueprint(certificates_bp)
    init_tenant_context(app)

    secondary_tenant_safe_endpoints = {
        "core.home",
        "core.login",
        "core.logout",
        "core.dashboard",
        "core.users",
        "core.user_new",
        "core.user_edit",
        "core.user_toggle_status",
        "core.branches",
        "core.branch_new",
        "core.branch_edit",
        "core.branch_toggle_status",
        "core.tenant_branding",
        "healthz",
        "static",
        "tenant_file",
    }

    @app.before_request
    def contain_unmigrated_secondary_tenant_modules():
        """Prevent secondary tenants from reading legacy Global IT tables."""
        from services.tenant_context import get_current_institute_id

        institute_id = get_current_institute_id()
        if institute_id in (None, 1):
            return None
        if app.config.get("TESTING") and request.path.startswith("/__phase"):
            return None
        if request.endpoint in secondary_tenant_safe_endpoints:
            return None
        if request.endpoint and (request.endpoint.startswith("leads.") or request.endpoint.startswith("students.") or request.endpoint.startswith("website.") or request.endpoint.startswith("billing.")):
            return None
        abort(403)

    # Register storage_url global in Jinja templates
    def storage_url(path):
        if not path:
            return ""
        try:
            storage_service = get_storage_service()
            return storage_service.generate_public_url(path)
        except Exception:
            return f"/static/{path}"
            
    app.jinja_env.globals['storage_url'] = storage_url

    @app.get("/tenant-files/<path:object_path>")
    def tenant_file(object_path):
        from services.storage import parse_tenant_storage_path
        from services.tenant_context import get_current_institute_id

        tenant_id, relative_path = parse_tenant_storage_path(object_path)
        if tenant_id is None:
            abort(404)
        is_public_branding = relative_path.startswith("branding/")
        current_institute_id = get_current_institute_id()
        platform_owner = False
        if is_public_branding and session.get("platform_role") == "platform_owner":
            conn = get_conn()
            try:
                platform_owner = bool(
                    conn.execute(
                        """SELECT id FROM users
                           WHERE id = ? AND platform_role = 'platform_owner'
                             AND is_active = 1""",
                        (session.get("user_id"),),
                    ).fetchone()
                )
            finally:
                conn.close()
        if current_institute_id != tenant_id and not platform_owner:
            abort(404)
        authenticated_tenant = session.get("institute_id") or session.get(
            "student_institute_id"
        )
        if (not is_public_branding or authenticated_tenant is not None) and not platform_owner:
            if int(authenticated_tenant or 0) != tenant_id:
                abort(404)
        storage_service = get_storage_service()
        canonical_path = f"tenants/{tenant_id}/{relative_path}"
        if not storage_service.file_exists(canonical_path):
            abort(404)
        data = storage_service.download_file(canonical_path)
        filename = os.path.basename(relative_path)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return send_file(
            BytesIO(data),
            mimetype=mime_type,
            download_name=filename,
            as_attachment=request.args.get("download") == "1",
            max_age=300 if is_public_branding else 0,
        )

    # Backward compatibility fallback routes to redirect old static file URLs to GCS
    def redirect_with_query(url):
        if request.query_string:
            qs = request.query_string.decode('utf-8')
            url += ("&" if "?" in url else "?") + qs
        return redirect(url)

    @app.route('/static/images/student_photos/<path:filename>')
    def serve_fallback_student_photos(filename):
        if filename.startswith("student_photos/"):
            filename = filename.replace("student_photos/", "", 1)
        try:
            storage_service = get_storage_service()
            dest_path = f"student_photos/{filename}"
            if storage_service.file_exists(dest_path):
                url = storage_service.generate_public_url(dest_path)
                if url.startswith("http"):
                    return redirect_with_query(url)
        except Exception:
            pass
        return send_from_directory(os.path.join(app.root_path, 'static', 'images', 'student_photos'), filename)

    @app.route('/static/lms/images/<path:filename>')
    def serve_fallback_lms_images(filename):
        try:
            storage_service = get_storage_service()
            dest_path = f"lms/images/{filename}"
            if storage_service.file_exists(dest_path):
                url = storage_service.generate_public_url(dest_path)
                if url.startswith("http"):
                    return redirect_with_query(url)
        except Exception:
            pass
        return send_from_directory(os.path.join(app.root_path, 'static', 'lms', 'images'), filename)


    @app.route('/static/images/student_signatures/<path:filename>')
    def serve_fallback_student_signatures(filename):
        if filename.startswith("signatures/"):
            filename = filename.replace("signatures/", "", 1)
        try:
            storage_service = get_storage_service()
            dest_path = f"signatures/{filename}"
            if storage_service.file_exists(dest_path):
                url = storage_service.generate_public_url(dest_path)
                if url.startswith("http"):
                    return redirect_with_query(url)
        except Exception:
            pass
        return send_from_directory(os.path.join(app.root_path, 'static', 'images', 'student_signatures'), filename)

    @app.route('/static/images/company_logo/<path:filename>')
    def serve_fallback_company_logo(filename):
        if filename.startswith("logos/"):
            filename = filename.replace("logos/", "", 1)
        try:
            storage_service = get_storage_service()
            dest_path = f"logos/{filename}"
            if storage_service.file_exists(dest_path):
                url = storage_service.generate_public_url(dest_path)
                if url.startswith("http"):
                    return redirect_with_query(url)
        except Exception:
            pass
        return send_from_directory(os.path.join(app.root_path, 'static', 'images', 'company_logo'), filename)

    @app.route('/static/images/certificate_templates/<path:filename>')
    def serve_fallback_certificate_templates(filename):
        if filename.startswith("certificates/"):
            filename = filename.replace("certificates/", "", 1)
        try:
            storage_service = get_storage_service()
            dest_path = f"certificates/{filename}"
            if storage_service.file_exists(dest_path):
                url = storage_service.generate_public_url(dest_path)
                if url.startswith("http"):
                    return redirect_with_query(url)
        except Exception:
            pass
        return send_from_directory(os.path.join(app.root_path, 'static', 'images', 'certificate_templates'), filename)

    @app.route('/uploads/student_documents/<path:filename>')
    def serve_fallback_student_documents(filename):
        if filename.startswith("documents/"):
            filename = filename.replace("documents/", "", 1)
        try:
            storage_service = get_storage_service()
            dest_path = f"documents/{filename}"
            if storage_service.file_exists(dest_path):
                url = storage_service.generate_public_url(dest_path)
                if url.startswith("http"):
                    return redirect_with_query(url)
        except Exception:
            pass
        return send_from_directory(os.path.join(app.root_path, 'uploads', 'student_documents'), filename)

    # File serving route for uploaded content
    @app.route('/uploads/content/<path:filename>')
    def serve_content(filename):
        """Serve uploaded content files"""
        try:
            # Security: only serve from the uploads/content directory
            upload_path = os.path.join(Config.UPLOAD_FOLDER)
            return send_from_directory(upload_path, filename)
        except Exception as e:
            return f"File not found: {str(e)}", 404

    @app.route('/uploads/leave_docs/<path:filename>')
    @login_required
    def serve_leave_doc(filename):
        """Serve student leave request document uploads"""
        try:
            from config import LEAVE_DOCS_DIR
            if session.get('role') not in ('admin', 'staff'):
                student_id = session.get('student_id')
                if not student_id:
                    abort(403)

                conn = get_conn()
                try:
                    row = conn.execute(
                        "SELECT 1 FROM leave_requests WHERE student_id = ? AND document_filename = ?",
                        (student_id, filename),
                    ).fetchone()
                finally:
                    conn.close()

                if not row:
                    abort(403)

            return send_from_directory(LEAVE_DOCS_DIR, filename)
        except Exception:
            abort(404)

    # Register Jinja2 filters
    app.jinja_env.filters['format_datetime'] = format_datetime
    app.jinja_env.filters['to_ist_time'] = to_ist_time
    app.jinja_env.filters['format_ist_datetime'] = format_ist_datetime
    app.jinja_env.filters['basename'] = os.path.basename

    import json as _json
    def _from_json_len(val):
        try:
            return len(_json.loads(val)) if val else 0
        except Exception:
            return 0
    app.jinja_env.filters['from_json_len'] = _from_json_len

    def _from_json(val):
        try:
            return _json.loads(val) if val else {}
        except Exception:
            return {}
    app.jinja_env.filters['from_json'] = _from_json

    @app.context_processor
    def inject_company():
        return {"company": get_company_profile()}

    @app.context_processor
    def inject_student_profile_score():
        student_id = session.get('student_id')
        if not student_id:
            return {}
        try:
            from modules.students.routes import calculate_profile_score
            conn = get_conn()
            try:
                student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
                uploaded_docs = conn.execute("SELECT category FROM student_uploaded_documents WHERE student_id = ?", (student_id,)).fetchall()
                score = calculate_profile_score(student, uploaded_docs)
                return {"student_profile_score": score}
            finally:
                conn.close()
        except Exception:
            return {}

    @app.after_request
    def add_cors_headers_to_static(response):
        if request.path.startswith('/static/') or request.path.startswith('/uploads/'):
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        if app.config["SECURITY_HEADERS_ENABLED"]:
            response.headers.setdefault("Content-Security-Policy", app.config["CONTENT_SECURITY_POLICY"])
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault(
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=(), payment=()",
            )
            if request.is_secure:
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    f"max-age={app.config['HSTS_MAX_AGE']}; includeSubDomains",
                )
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "environment": app.config["APP_ENV"]}

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=Config.DEBUG_MODE)
