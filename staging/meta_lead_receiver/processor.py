"""Synthetic-only Meta processor. It returns redacted evidence, never answer values."""
from __future__ import annotations

import hashlib
import json
import re

import requests

from .receiver import Settings


class ProcessingError(RuntimeError):
    def __init__(self, safe_code: str):
        self.safe_code = safe_code
        super().__init__(safe_code)


class MetaSyntheticProcessor:
    def __init__(self, settings: Settings, system_user_token: str, graph_version: str,
                 *, session=None, timeout: int = 20):
        if not system_user_token:
            raise ValueError("A system-user token is required.")
        if not re.fullmatch(r"v\d+\.\d+", graph_version):
            raise ValueError("Use an explicit Graph API version.")
        self.settings = settings
        self.system_user_token = system_user_token
        self.base = f"https://graph.facebook.com/{graph_version}"
        self.session = session or requests.Session()
        self.timeout = timeout
        self._page_token = None

    def _get(self, path: str, token: str, **params):
        try:
            response = self.session.get(f"{self.base}/{path}",
                headers={"Authorization": f"Bearer {token}"}, params=params, timeout=self.timeout)
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProcessingError("upstream_unavailable") from exc
        if response.status_code == 429:
            raise ProcessingError("rate_limited")
        if response.status_code >= 500:
            raise ProcessingError("upstream_unavailable")
        if response.status_code != 200 or not isinstance(body, dict) or body.get("error"):
            raise ProcessingError("invalid_response")
        return body

    def _derived_page_token(self):
        if self._page_token:
            return self._page_token
        body = self._get(self.settings.page_id, self.system_user_token, fields="id,access_token")
        if str(body.get("id")) != self.settings.page_id or not isinstance(body.get("access_token"), str):
            raise ProcessingError("invalid_response")
        self._page_token = body["access_token"]
        return self._page_token

    def __call__(self, item: dict) -> dict:
        lead_id = item.get("lead_id")
        if (lead_id not in self.settings.synthetic_lead_ids
                or item.get("page_id") != self.settings.page_id
                or item.get("form_id") != self.settings.form_id):
            raise ProcessingError("invalid_response")
        body = self._get(lead_id, self._derived_page_token(),
                         fields="id,form_id,created_time,field_data")
        if str(body.get("id")) != lead_id or str(body.get("form_id")) != self.settings.form_id:
            raise ProcessingError("invalid_response")
        fields = body.get("field_data")
        if not isinstance(fields, list) or not fields:
            raise ProcessingError("invalid_response")
        names = []
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                raise ProcessingError("invalid_response")
            names.append(field["name"])
        digest = hashlib.sha256(json.dumps(fields, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        return {"field_names": names, "answer_count": len(names), "values_sha256": digest}
