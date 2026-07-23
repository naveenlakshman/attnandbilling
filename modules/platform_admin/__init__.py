from flask import Blueprint


platform_admin_bp = Blueprint(
    "platform_admin",
    __name__,
    url_prefix="/platform",
)

from . import routes  # noqa: E402,F401
