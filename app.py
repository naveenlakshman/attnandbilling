from flask import Flask
from extensions import csrf, limiter
from config import Config
from db import init_db, get_company_profile
from modules.leads.routes import leads_bp
from modules.billing.routes import billing_bp
from modules.assets.routes import assets_bp
from modules.reports.routes import reports_bp
from modules.import_export.routes import import_export_bp
from modules.baddebt.routes import baddebt_bp
from modules.attendance.routes import attendance_bp
from datetime import datetime, timedelta

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

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    csrf.init_app(app)
    limiter.init_app(app)

    init_db()

    from modules.core.routes import core_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(leads_bp, url_prefix="/leads")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(assets_bp, url_prefix="/assets")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(import_export_bp, url_prefix="/import-export")
    app.register_blueprint(baddebt_bp, url_prefix="/baddebt")
    app.register_blueprint(attendance_bp, url_prefix="/attendance")

    # Register Jinja2 filters
    app.jinja_env.filters['format_datetime'] = format_datetime
    app.jinja_env.filters['to_ist_time'] = to_ist_time

    @app.context_processor
    def inject_company():
        return {"company": get_company_profile()}

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)