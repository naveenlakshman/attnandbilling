"""Meta lead retrieval with a synthetic evidence wrapper and production validation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

import requests

from .receiver import Settings


class ProcessingError(RuntimeError):
    def __init__(self, safe_code: str):
        self.safe_code = safe_code
        super().__init__(safe_code)


@dataclass(frozen=True)
class RetrievedLead:
    lead_id: str
    form_id: str
    created_time: str
    ad_id: str | None
    campaign_id: str | None
    adset_id: str | None
    platform: str | None
    name: str
    phone: str
    field_data: tuple[dict, ...]

    def as_production_result(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "form_id": self.form_id,
            "created_time": self.created_time,
            "ad_id": self.ad_id,
            "campaign_id": self.campaign_id,
            "adset_id": self.adset_id,
            "platform": self.platform,
            "name": self.name,
            "phone": self.phone,
            "field_data": list(self.field_data),
        }


class MetaLeadRetriever:
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
        self._page_tokens = {}

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

    def _derived_page_token(self, page_id: str):
        if page_id in self._page_tokens:
            return self._page_tokens[page_id]
        body = self._get(page_id, self.system_user_token, fields="id,access_token")
        if str(body.get("id")) != page_id or not isinstance(body.get("access_token"), str):
            raise ProcessingError("invalid_response")
        self._page_tokens[page_id] = body["access_token"]
        return self._page_tokens[page_id]

    def retrieve(self, item: dict, *, require_synthetic: bool) -> RetrievedLead:
        lead_id = item.get("lead_id")
        page_id = item.get("page_id")
        form_id = item.get("form_id")
        if (not isinstance(page_id, str) or not page_id.isdigit()
                or not isinstance(form_id, str) or not form_id.isdigit()
                or (require_synthetic and (lead_id not in self.settings.synthetic_lead_ids
                    or page_id != self.settings.page_id or form_id != self.settings.form_id))):
            raise ProcessingError("invalid_response")
        body = self._get(lead_id, self._derived_page_token(page_id),
                         fields="id,form_id,created_time,ad_id,adset_id,campaign_id,platform,field_data")
        if str(body.get("id")) != lead_id or str(body.get("form_id")) != form_id:
            raise ProcessingError("invalid_response")
        fields = body.get("field_data")
        if not isinstance(fields, list) or not fields or len(fields) > 100:
            raise ProcessingError("invalid_response")
        cleaned = []
        answers = {}
        for field in fields:
            name = field.get("name") if isinstance(field, dict) else None
            values = field.get("values") if isinstance(field, dict) else None
            if (not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_? -]{1,160}", name)
                    or not isinstance(values, list) or not values or len(values) > 20
                    or any(not isinstance(value, str) or len(value) > 4096 for value in values)):
                raise ProcessingError("invalid_response")
            normalized_values = [value.strip() for value in values]
            cleaned.append({"name": name, "values": normalized_values})
            answers[name] = normalized_values
        encoded = json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > 64 * 1024:
            raise ProcessingError("invalid_response")
        if require_synthetic:
            name = (answers.get("full_name") or [""])[0].strip()
            try:
                phone = _normalize_phone((answers.get("phone_number") or [""])[0])
            except ProcessingError:
                phone = ""
        else:
            name = _one(answers, "full_name")
            phone = _normalize_phone(_one(answers, "phone_number"))
        created_time = body.get("created_time")
        if ((not require_synthetic and (not isinstance(name, str) or not 1 <= len(name) <= 255))
                or not isinstance(created_time, str)):
            raise ProcessingError("invalid_response")
        ad_id = body.get("ad_id")
        campaign_id = body.get("campaign_id")
        adset_id = body.get("adset_id")
        platform = body.get("platform")
        return RetrievedLead(
            lead_id=lead_id,
            form_id=form_id,
            created_time=created_time[:64],
            ad_id=str(ad_id) if ad_id is not None and str(ad_id).isdigit() else None,
            campaign_id=(str(campaign_id) if campaign_id is not None
                         and str(campaign_id).isdigit() else None),
            adset_id=(str(adset_id) if adset_id is not None and str(adset_id).isdigit() else None),
            platform=str(platform)[:32] if isinstance(platform, str) else None,
            name=name.strip(),
            phone=phone,
            field_data=tuple(cleaned),
        )


class MetaSyntheticProcessor(MetaLeadRetriever):
    def __call__(self, item: dict) -> dict:
        lead = self.retrieve(item, require_synthetic=True)
        fields = list(lead.field_data)
        names = [field["name"] for field in fields]
        digest = hashlib.sha256(json.dumps(fields, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        return {"field_names": names, "answer_count": len(names), "values_sha256": digest}


def _one(answers: dict[str, list[str]], key: str) -> str:
    values = answers.get(key)
    if not values or len(values) != 1 or not values[0].strip():
        raise ProcessingError("invalid_response")
    return values[0].strip()


def _normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ProcessingError("invalid_response")
    return digits
