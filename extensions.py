from flask import request
from flask_wtf.csrf import CSRFProtect
# pyrefly: ignore [missing-import]
from flask_limiter import Limiter

def get_client_ip():
    # Extract client IP behind Google Cloud Run proxy / load balancer
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    return ip or "127.0.0.1"

def get_auth_rate_limit_key():
    ip = get_client_ip()
    if request.method == "POST":
        username = (
            request.form.get("username")
            or request.form.get("email")
            or request.form.get("student_code")
            or ""
        ).strip().lower()
        if username:
            return f"{ip}:{username}"
    return ip

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_client_ip,
)


def public_auth_limit():
    return limiter.limit(
        "10 per minute",
        methods=["POST"],
        key_func=get_auth_rate_limit_key
    )


def public_form_limit():
    return limiter.limit("5 per minute", methods=["POST"])
