"""Fast regression checks for the DNS domain ownership service."""

import os
import sys

import dns.resolver

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.domain_verification import (
    verification_record_name,
    verification_record_value,
    verify_dns_challenge,
)


def main():
    record_name = verification_record_name(
        "Test.GlobalITerp.com.", "_globaliterp-verification"
    )
    assert record_name == "_globaliterp-verification.test.globaliterp.com"
    assert verification_record_value("abc") == "globaliterp-verification=abc"

    verified, _ = verify_dns_challenge(
        record_name,
        "globaliterp-verification=abc",
        resolver=lambda _: {"globaliterp-verification=abc"},
    )
    assert verified

    verified, message = verify_dns_challenge(
        record_name,
        "globaliterp-verification=abc",
        resolver=lambda _: {"globaliterp-verification=wrong"},
    )
    assert not verified
    assert "does not match" in message

    def missing(_):
        raise dns.resolver.NXDOMAIN

    verified, message = verify_dns_challenge(
        record_name, "globaliterp-verification=abc", resolver=missing
    )
    assert not verified
    assert "does not exist" in message
    print("Domain verification regression checks passed.")


if __name__ == "__main__":
    main()
