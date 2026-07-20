from flask import request
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter

def get_client_ip():
    # Extract client IP behind Google Cloud Run proxy / load balancer
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    return ip or "127.0.0.1"

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_client_ip,
)


def public_auth_limit():
    return limiter.limit("10 per minute")


def public_form_limit():
    return limiter.limit("5 per minute")
