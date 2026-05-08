from flask import Blueprint

students_bp = Blueprint('students', __name__, url_prefix='/student', template_folder='../../templates/students')

from . import routes
