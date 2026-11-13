import hashlib
import json

import pytest

from staging.meta_lead_receiver.processor import MetaLeadRetriever, MetaSyntheticProcessor, ProcessingError
from staging.meta_lead_receiver.receiver import Settings


PAGE = "300480973645515"
FORM = "1806095097277660"
LEAD = "900000000000001"


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture
def settings(tmp_path):
    return Settings(str(tmp_path / "unused.db"), "secret", "verify", PAGE, FORM,
                    frozenset({LEAD}), enabled=True)


def test_processor_derives_page_token_and_returns_redacted_result(settings):
    fields = [{"name": "full_name", "values": ["Synthetic Person"]},
              {"name": "phone_number", "values": ["0000000000"]}]
    session = Session([
        Response(200, {"id": PAGE, "access_token": "derived-private-token"}),
        Response(200, {"id": LEAD, "form_id": FORM, "created_time": "2026-11-13T00:00:00+0000",
                       "field_data": fields}),
    ])
    processor = MetaSyntheticProcessor(settings, "system-private-token", "v27.0", session=session)
    result = processor({"lead_id": LEAD, "page_id": PAGE, "form_id": FORM,
                        "ad_id": None, "submitted_at": None})
    assert result == {
        "field_names": ["full_name", "phone_number"],
        "answer_count": 2,
        "values_sha256": hashlib.sha256(json.dumps(fields, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(),
    }
    assert "Synthetic Person" not in json.dumps(result)
    assert "0000000000" not in json.dumps(result)
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer system-private-token"
    assert session.calls[1][1]["headers"]["Authorization"] == "Bearer derived-private-token"


def test_processor_blocks_unallowlisted_id_before_network(settings):
    session = Session([])
    processor = MetaSyntheticProcessor(settings, "token", "v27.0", session=session)
    with pytest.raises(ProcessingError) as exc:
        processor({"lead_id": "999", "page_id": PAGE, "form_id": FORM})
    assert exc.value.safe_code == "invalid_response"
    assert session.calls == []


def test_production_retrieval_accepts_real_id_and_validates_identity(settings):
    real_id = "900000000000099"
    session = Session([
        Response(200, {"id": PAGE, "access_token": "page-token"}),
        Response(200, {"id": real_id, "form_id": FORM, "created_time": "2026-11-13T00:00:00+0000",
                       "platform": "instagram", "ad_id": "123", "campaign_id": "456", "adset_id": "789",
                       "field_data": [{"name": "full_name", "values": ["Test Person"]},
                                      {"name": "phone_number", "values": ["+91 98765 43210"]},
                                      {"name": "when_would_you_like_to_join?", "values": ["Immediately"]}]}),
    ])
    result = MetaLeadRetriever(settings, "token", "v27.0", session=session).retrieve(
        {"lead_id": real_id, "page_id": PAGE, "form_id": FORM}, require_synthetic=False)
    assert result.name == "Test Person" and result.phone == "9876543210"
    assert result.platform == "instagram" and result.ad_id == "123"
    assert result.campaign_id == "456" and result.adset_id == "789"


def test_production_retrieval_uses_routed_page_and_form_not_defaults(settings):
    page = "400000000000001"
    form = "500000000000001"
    lead = "900000000000099"
    session = Session([
        Response(200, {"id": page, "access_token": "routed-page-token"}),
        Response(200, {"id": lead, "form_id": form, "created_time": "2026-11-13T00:00:00+0000",
                       "field_data": [{"name": "full_name", "values": ["Routed Person"]},
                                      {"name": "phone_number", "values": ["9876543210"]}]}),
    ])
    result = MetaLeadRetriever(settings, "token", "v27.0", session=session).retrieve(
        {"lead_id": lead, "page_id": page, "form_id": form}, require_synthetic=False)
    assert result.form_id == form
    assert session.calls[0][0].endswith("/" + page)


def test_production_retrieval_rejects_missing_phone(settings):
    real_id = "900000000000099"
    session = Session([
        Response(200, {"id": PAGE, "access_token": "page-token"}),
        Response(200, {"id": real_id, "form_id": FORM, "created_time": "2026-11-13T00:00:00+0000",
                       "field_data": [{"name": "full_name", "values": ["Test Person"]}]}),
    ])
    with pytest.raises(ProcessingError):
        MetaLeadRetriever(settings, "token", "v27.0", session=session).retrieve(
            {"lead_id": real_id, "page_id": PAGE, "form_id": FORM}, require_synthetic=False)


@pytest.mark.parametrize(("status", "code"), [(429, "rate_limited"), (503, "upstream_unavailable"),
                                               (400, "invalid_response")])
def test_processor_maps_upstream_failures_to_safe_codes(settings, status, code):
    session = Session([Response(status, {"error": {"message": "private detail"}})])
    processor = MetaSyntheticProcessor(settings, "token", "v27.0", session=session)
    with pytest.raises(ProcessingError) as exc:
        processor({"lead_id": LEAD, "page_id": PAGE, "form_id": FORM})
    assert exc.value.safe_code == code
    assert "private detail" not in str(exc.value)
