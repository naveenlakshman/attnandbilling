"""
SMS Gateway helper using api.sms-gate.app (cloud relay).
Reads credentials from app config / environment variables.
"""
import logging
import os

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

# Read credentials from environment — set these in your .env file.
_GATEWAY_URL = "https://api.sms-gate.app/3rdparty/v1/message"
_GATEWAY_USER = os.environ.get("SMS_GATEWAY_USER", "DP4VDN")
_GATEWAY_PASSWORD = os.environ.get("SMS_GATEWAY_PASSWORD", "qrbwcqfz-gwayf")


def normalize_sms_phone(phone_number: str) -> str:
    phone = (phone_number or "").strip()
    if not phone:
        return ""

    if phone.startswith("+"):
        digits = "".join(ch for ch in phone[1:] if ch.isdigit())
        return f"+{digits}" if digits else ""

    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    return f"+{digits}" if digits else ""


def send_sms(phone_number: str, message_text: str) -> dict:
    """
    Send an SMS via the SMS-Gate cloud relay.

    Args:
        phone_number: E.164 format, e.g. "+919071717162"
        message_text: Plain text message body.

    Returns:
        dict with keys:
            success (bool)
            message_id (str) — present on success
            status (str)     — present on success
            error (str)      — present on failure
    """
    if not phone_number or not message_text:
        return {"success": False, "error": "phone_number and message_text are required"}

    payload = {
        "textMessage": {"text": message_text},
        "phoneNumbers": [phone_number],
    }

    try:
        response = requests.post(
            _GATEWAY_URL,
            json=payload,
            auth=HTTPBasicAuth(_GATEWAY_USER, _GATEWAY_PASSWORD),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )

        if response.status_code in (200, 202):
            data = response.json()
            logger.info("SMS sent to %s — id: %s", phone_number, data.get("id"))
            return {
                "success": True,
                "message_id": data.get("id"),
                "status": data.get("state"),
            }

        logger.warning(
            "SMS gateway returned %s for %s: %s",
            response.status_code,
            phone_number,
            response.text,
        )
        return {"success": False, "error": response.text}

    except requests.exceptions.Timeout:
        logger.error("SMS gateway timeout for %s", phone_number)
        return {"success": False, "error": "Request timeout — phone may be offline"}
    except requests.exceptions.ConnectionError:
        logger.error("SMS gateway connection error for %s", phone_number)
        return {"success": False, "error": "Connection error — gateway not reachable"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected SMS error for %s", phone_number)
        return {"success": False, "error": str(exc)}
