from flask import Blueprint

website_bp = Blueprint("website", __name__)

from modules.website import routes  # noqa
