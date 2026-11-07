"""DNS ownership challenges for tenant custom domains."""

from __future__ import annotations

import secrets

import dns.exception
import dns.resolver


TOKEN_VALUE_PREFIX = "globaliterp-verification="


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def verification_record_name(hostname: str, prefix: str) -> str:
    return f"{prefix.strip().strip('.')}.{hostname.strip().strip('.').lower()}"


def verification_record_value(token: str) -> str:
    return f"{TOKEN_VALUE_PREFIX}{token}"


def resolve_txt_values(record_name: str) -> set[str]:
    answers = dns.resolver.resolve(record_name, "TXT", lifetime=8.0)
    values = set()
    for answer in answers:
        if hasattr(answer, "strings"):
            values.add(b"".join(answer.strings).decode("utf-8"))
        else:
            values.add(str(answer).strip('"').replace('" "', ""))
    return values


def verify_dns_challenge(record_name: str, expected_value: str, resolver=None):
    lookup = resolver or resolve_txt_values
    try:
        values = lookup(record_name)
    except dns.resolver.NXDOMAIN:
        return False, "DNS record does not exist yet."
    except dns.resolver.NoAnswer:
        return False, "The hostname exists, but no TXT verification record was found."
    except dns.resolver.NoNameservers:
        return False, "DNS nameservers could not answer the verification request."
    except (dns.exception.Timeout, TimeoutError):
        return False, "DNS lookup timed out. Please try again."
    except Exception:
        return False, "DNS verification could not be completed. Please try again."

    if expected_value in values:
        return True, "Domain ownership verified."
    return False, "TXT record was found, but its value does not match this domain challenge."
