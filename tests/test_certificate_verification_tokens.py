from flask import Flask

from modules.certificates.verification_tokens import (
    build_certificate_verification_url,
    is_certificate_verification_token_valid,
    make_certificate_verification_token,
)


def test_certificate_verification_token_is_bound_to_certificate_row():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "certificate-test-secret"

    with app.app_context():
        token = make_certificate_verification_token(21, "GIT-CERT-2026-0021")

        assert is_certificate_verification_token_valid(
            21,
            "GIT-CERT-2026-0021",
            token,
        )
        assert not is_certificate_verification_token_valid(
            20,
            "GIT-CERT-2026-0021",
            token,
        )
        assert not is_certificate_verification_token_valid(
            21,
            "GIT-CERT-2026-0011",
            token,
        )
        assert not is_certificate_verification_token_valid(
            21,
            "GIT-CERT-2026-0021",
            "not-a-valid-token",
        )


def test_certificate_verification_url_uses_signed_id_route():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "certificate-test-secret"

    with app.app_context():
        url = build_certificate_verification_url(
            "https://www.globaliterp.com/",
            21,
            "GIT-CERT-2026-0021",
        )

    assert url.startswith("https://www.globaliterp.com/verify-certificate/21/")
    assert "GIT-CERT-2026-0021" not in url
