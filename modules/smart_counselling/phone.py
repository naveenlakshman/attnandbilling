import re

from .errors import validation_error


_ALLOWED_PHONE_INPUT = re.compile(r"^[0-9+()\-\s]+$")
_INDIAN_MOBILE = re.compile(r"^[6-9][0-9]{9}$")


def normalize_indian_mobile(value):
    """Return one canonical E.164 Indian mobile value or raise validation_error."""
    raw = str(value or "").strip()
    if not raw or not _ALLOWED_PHONE_INPUT.fullmatch(raw):
        raise validation_error(
            "Enter a valid Indian mobile number.",
            {"mobile": "Use a 10-digit Indian mobile number."},
        )
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not _INDIAN_MOBILE.fullmatch(digits):
        raise validation_error(
            "Enter a valid Indian mobile number.",
            {"mobile": "Use a 10-digit Indian mobile number beginning with 6–9."},
        )
    return f"+91{digits}"


def try_normalize_indian_mobile(value):
    try:
        return normalize_indian_mobile(value)
    except Exception:
        return None


def mask_mobile(normalized):
    national = str(normalized or "")[-10:]
    if len(national) != 10:
        return ""
    return f"+91 {national[:2]}••••••{national[-2:]}"
