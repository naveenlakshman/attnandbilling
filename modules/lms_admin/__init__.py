from flask import Blueprint

lms_admin_bp = Blueprint('lms_admin', __name__, url_prefix='/lms_admin', template_folder='../../templates/lms_admin')

from . import routes
