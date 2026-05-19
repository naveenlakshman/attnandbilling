from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
)


def public_auth_limit():
    return limiter.limit("10 per minute")


def public_form_limit():
    return limiter.limit("5 per minute")
