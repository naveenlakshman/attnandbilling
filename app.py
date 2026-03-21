from flask import Flask
from config import Config
from db import init_db
from modules.leads.routes import leads_bp
from modules.billing.routes import billing_bp
from modules.reports.routes import reports_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db()

    from modules.core.routes import core_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(leads_bp, url_prefix="/leads")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(reports_bp, url_prefix="/reports")

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)