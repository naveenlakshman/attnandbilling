import hmac
from hashlib import sha256

from flask import current_app


def make_certificate_verification_token(cert_id, certificate_number):
    payload = f"{int(cert_id)}:{certificate_number}"
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), sha256).hexdigest()


def is_certificate_verification_token_valid(cert_id, certificate_number, token):
    if not token:
        return False
    expected = make_certificate_verification_token(cert_id, certificate_number)
    return hmac.compare_digest(expected, token)


def build_certificate_verification_url(base_url, cert_id, certificate_number):
    token = make_certificate_verification_token(cert_id, certificate_number)
    return f"{base_url.rstrip('/')}/verify-certificate/{int(cert_id)}/{token}"
