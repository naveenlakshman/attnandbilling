from flask import Flask
from config import Config
from db import init_db
from modules.leads.routes import leads_bp
from modules.billing.routes import billing_bp
from modules.assets.routes import assets_bp
from modules.reports.routes import reports_bp
from modules.import_export.routes import import_export_bp
from modules.baddebt.routes import baddebt_bp
from datetime import datetime

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

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db()

    from modules.core.routes import core_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(leads_bp, url_prefix="/leads")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(assets_bp, url_prefix="/assets")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(import_export_bp, url_prefix="/import-export")
    app.register_blueprint(baddebt_bp, url_prefix="/baddebt")

    # Register Jinja2 filters
    app.jinja_env.filters['format_datetime'] = format_datetime

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)