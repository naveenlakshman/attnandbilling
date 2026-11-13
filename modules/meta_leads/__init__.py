from flask import Blueprint

meta_leads_bp = Blueprint("meta_leads", __name__, url_prefix="/admin/meta-leads")

from . import routes  # noqa: E402,F401

