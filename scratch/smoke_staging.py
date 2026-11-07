"""Authenticated smoke test for the isolated staging deployment."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests


base_url = os.environ["STAGING_BASE_URL"].rstrip("/")
password = os.environ["STAGING_ADMIN_PASSWORD"]
session = requests.Session()

login_page = session.get(f"{base_url}/login", timeout=30)
login_page.raise_for_status()
match = re.search(
    r'<meta name="csrf-token" content="([^"]+)"',
    login_page.text,
)
if not match:
    raise RuntimeError("Login page did not contain a CSRF token")

response = session.post(
    f"{base_url}/login",
    data={
        "username": "staging_admin",
        "password": password,
        "csrf_token": match.group(1),
    },
    headers={"Referer": f"{base_url}/login"},
    timeout=30,
    allow_redirects=True,
)
response.raise_for_status()

final_path = urlparse(response.url).path
if final_path != "/dashboard" or "Dashboard" not in response.text:
    raise RuntimeError(f"Staging login failed; final path was {final_path!r}")

print("staging_login=OK")
print(f"staging_dashboard={final_path}")
