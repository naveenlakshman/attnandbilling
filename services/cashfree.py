"""Cashfree HTTP client and raw-body webhook authentication."""

import base64
import hashlib
import hmac
from decimal import Decimal, InvalidOperation

import requests
from flask import current_app

API_URLS = {'sandbox':'https://sandbox.cashfree.com/pg', 'production':'https://api.cashfree.com/pg'}


def mode():
    return current_app.config.get('CASHFREE_MODE', 'sandbox')


def valid_configuration(config):
    environment = config.get('CASHFREE_MODE', 'sandbox')
    secret = config.get('CASHFREE_SECRET_KEY', '')
    app_id = config.get('CASHFREE_APP_ID', '')
    return bool(
        environment in API_URLS and app_id and secret
        and 'xxxxxxxx' not in secret.lower()
        and config.get('CASHFREE_API_URL', '').rstrip('/') == API_URLS[environment]
        and (environment != 'production' or not app_id.upper().startswith('TEST'))
        and (config.get('APP_ENV') != 'production' or environment == 'production')
    )


class CashfreeError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def checkout_content_security_policy(policy):
    """Permit the SDK's exact form POST destination without broadening other directives."""
    destination = API_URLS.get(mode(), API_URLS['sandbox']) + '/view/sessions/checkout'
    directives = policy.split(';')
    for index, directive in enumerate(directives):
        parts = directive.split()
        if parts and parts[0].lower() == 'form-action':
            sources = [source for source in parts[1:] if source != "'none'"]
            if destination not in sources:
                sources.append(destination)
            directives[index] = 'form-action ' + ' '.join(sources)
            return ';'.join(directives)
    # Without form-action, CSP does not restrict form destinations.
    return policy


def amount_paise(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 1 or amount > Decimal("99999999.99"):
            raise ValueError
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError
        return int(amount * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise CashfreeError("Amount must be at least INR 1 with at most two decimal places.", 400)


def configured():
    return valid_configuration(current_app.config)


def require_config():
    if not configured():
        raise CashfreeError("Cashfree is not configured for this environment. Check the payment mode and credentials.", 503)


def api_request(method, path, payload=None, idempotency_key=None):
    require_config()
    config = current_app.config
    headers = {
        "x-client-id": config["CASHFREE_APP_ID"],
        "x-client-secret": config["CASHFREE_SECRET_KEY"],
        "x-api-version": "2023-08-01",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if idempotency_key:
        headers["x-idempotency-key"] = idempotency_key
    try:
        response = requests.request(
            method, API_URLS[mode()] + path,
            headers=headers, json=payload, timeout=(5, 20), allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            # Provider responses may contain customer data. Do not echo them.
            if response.status_code in (401, 403):
                raise CashfreeError("Cashfree rejected the configured credentials.", 503)
            raise CashfreeError("Cashfree could not process the request. Retry with the same request key.")
        return response.json()
    except (requests.RequestException, ValueError):
        raise CashfreeError("Cashfree is temporarily unavailable. Retry with the same request key.")


def valid_webhook(raw_body, timestamp, signature):
    require_config()
    if not timestamp or not signature or not timestamp.isdigit():
        return False
    signed = timestamp.encode("utf-8") + raw_body
    digest = hmac.new(
        current_app.config["CASHFREE_SECRET_KEY"].encode("utf-8"), signed, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)
