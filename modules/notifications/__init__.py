from flask import Blueprint

notifications_bp = Blueprint(
    "notifications",
    __name__,
    url_prefix="/notifications",
    template_folder="../../templates/notifications",
)

from . import routes  # noqa: E402,F401
