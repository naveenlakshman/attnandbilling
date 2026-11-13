import hashlib
import hmac
import json

import pytest

from staging.meta_lead_receiver.receiver import Settings, Store, create_app, run_once


SECRET = "staging-test-app-secret"
VERIFY = "staging-test-verify-token"
PAGE = "300480973645515"
FORM = "1806095097277660"
LEAD = "900000000000001"


@pytest.fixture
def settings(tmp_path):
    return Settings(str(tmp_path / "isolated.db"), SECRET, VERIFY, PAGE, FORM, frozenset({LEAD}),
                    enabled=True, verify_enabled=True, max_attempts=3, retry_base_seconds=2, retention_days=30)


@pytest.fixture
def client(settings):
    return create_app(settings).test_client()


def event(lead=LEAD, page=PAGE, form=FORM, **extra):
    value = {"leadgen_id": lead, "page_id": page, "form_id": form, "ad_id": "12345",
             "created_time": "2026-11-13T10:00:00+00:00", "field_data": [{"name": "phone", "values": ["DO_NOT_STORE"]}]}
    value.update(extra)
    return {"field": "leadgen", "value": value}


def body(*changes):
    return json.dumps({"object": "page", "entry": [{"id": PAGE, "changes": list(changes)}]}, separators=(",", ":")).encode()


def signature(raw):
    return "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


_DEFAULT_SIGNATURE = object()


def post(client, raw, sig=_DEFAULT_SIGNATURE):
    headers = {"Content-Type": "application/json"}
    if sig is _DEFAULT_SIGNATURE:
        headers["X-Hub-Signature-256"] = signature(raw)
    elif sig is not None:
        headers["X-Hub-Signature-256"] = sig
    return client.post("/webhook/meta", data=raw, headers=headers)


def test_verification_challenge_and_bad_token(client):
    good = client.get("/webhook/meta?hub.mode=subscribe&hub.verify_token=" + VERIFY + "&hub.challenge=abc123")
    bad = client.get("/webhook/meta?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=abc123")
    assert (good.status_code, good.text) == (200, "abc123")
    assert bad.status_code == 403


def test_disabled_switch_blocks_verification_and_intake(tmp_path):
    app = create_app(Settings(str(tmp_path / "off.db"), SECRET, VERIFY, PAGE, FORM, frozenset({LEAD})))
    client = app.test_client()
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json["ingest_enabled"] is False
    assert health.json["verify_enabled"] is False
    assert client.get("/webhook/meta?hub.mode=subscribe&hub.verify_token=" + VERIFY + "&hub.challenge=abc").status_code == 503
    assert client.post("/webhook/meta", data=b"{}").status_code == 503


def test_verification_can_be_enabled_while_ingestion_stays_disabled(tmp_path):
    app = create_app(Settings(str(tmp_path / "verify-only.db"), SECRET, VERIFY, PAGE, FORM,
                              frozenset({LEAD}), verify_enabled=True))
    client = app.test_client()
    response = client.get("/webhook/meta?hub.mode=subscribe&hub.verify_token=" + VERIFY +
                          "&hub.challenge=verify-only")
    assert (response.status_code, response.text) == (200, "verify-only")
    assert post(client, body(event())).status_code == 503
    assert Store(str(tmp_path / "verify-only.db")).health()["queue"] == {}


@pytest.mark.parametrize("header", [None, "", "sha256=" + "0" * 64, "SHA256=" + "0" * 64, "sha256=bad"])
def test_invalid_signature_never_stores(client, settings, header):
    raw = body(event())
    response = post(client, raw, header)
    assert response.status_code == 401
    assert Store(settings.db_path).health()["queue"] == {}


def test_raw_bytes_must_match_signature(client, settings):
    raw = body(event())
    response = post(client, raw + b" ", signature(raw))
    assert response.status_code == 401
    assert Store(settings.db_path).health()["queue"] == {}


def test_oversized_body_is_rejected_before_storage(client, settings):
    raw = b" " * (64 * 1024 + 1)
    response = post(client, raw)
    assert response.status_code == 413
    assert Store(settings.db_path).health()["queue"] == {}


def test_batched_events_allowlist_dedup_and_durable_reopen(client, settings):
    raw = body(event(), event(), event(lead="900000000000099"), event(page="2"),
               {"field": "feed", "value": {"message": "ignore"}})
    response = post(client, raw)
    assert response.status_code == 200
    assert response.json == {"accepted": 1, "duplicate": 1, "ignored": 2}
    reopened = Store(settings.db_path)
    with reopened.connect() as conn:
        rows = conn.execute("SELECT lead_id,state FROM notifications").fetchall()
        audit = [row[0] for row in conn.execute("SELECT counts_json FROM audit")]
        db_text = " ".join(str(x) for row in conn.execute("SELECT * FROM notifications") for x in row)
    assert [(r["lead_id"], r["state"]) for r in rows] == [(LEAD, "PENDING")]
    assert "DO_NOT_STORE" not in db_text
    assert "field_data" not in db_text
    assert all(LEAD not in line for line in audit)


def test_production_mode_accepts_matching_real_notification_but_not_wrong_form(tmp_path):
    settings = Settings(str(tmp_path / "production.db"), SECRET, VERIFY, PAGE, FORM,
                        frozenset({LEAD}), enabled=True, processing_mode="production")
    client = create_app(settings).test_client()
    real_id = "900000000000099"
    response = post(client, body(event(lead=real_id), event(lead="900000000000098", form="2")))
    assert response.json == {"accepted": 1, "duplicate": 0, "ignored": 1}
    with Store(settings.db_path).connect() as conn:
        assert conn.execute("SELECT lead_id FROM notifications").fetchone()[0] == real_id


def test_invalid_envelope_is_rejected(client):
    raw = json.dumps({"object": "user", "entry": []}).encode()
    assert post(client, raw).status_code == 400


def test_storage_failure_returns_retryable_response(settings, monkeypatch):
    app = create_app(settings)
    store = app.extensions["meta_staging_store"]
    def fail(*args, **kwargs):
        raise __import__("sqlite3").OperationalError("private db detail")
    monkeypatch.setattr(store, "ingest", fail)
    response = post(app.test_client(), body(event()))
    assert response.status_code == 503
    assert response.json == {"error": "storage_unavailable"}
    assert "private db detail" not in response.get_data(as_text=True)


def _enqueue(settings):
    s = Store(settings.db_path)
    assert s.ingest([{"leadgen_id": LEAD, "page_id": PAGE, "form_id": FORM,
                      "ad_id": None, "created_time": None}], settings)["accepted"] == 1
    return s


def test_worker_retry_backoff_and_success(settings, monkeypatch):
    import staging.meta_lead_receiver.receiver as receiver
    now = [1000.0]
    monkeypatch.setattr(receiver.time, "time", lambda: now[0])
    store = _enqueue(settings)
    seen = []
    def transient(_item):
        raise RuntimeError("raw exception must not be persisted")
    assert run_once(store, settings, transient) == "retry"
    with store.connect() as conn:
        row = conn.execute("SELECT state,attempts,last_error_code,available_at FROM notifications").fetchone()
    assert (row["state"], row["attempts"], row["last_error_code"]) == ("RETRY", 1, "unknown")
    assert row["available_at"] == 1002.0
    now[0] = 1003.0
    assert run_once(store, settings, lambda item: seen.append(item)) == "done"
    assert seen == [{"lead_id": LEAD, "page_id": PAGE, "form_id": FORM,
                     "ad_id": None, "submitted_at": None}]
    assert store.health()["queue"] == {"done": 1}


def test_worker_dead_letter_and_allowlisted_controlled_replay(settings, monkeypatch):
    import staging.meta_lead_receiver.receiver as receiver
    now = [2000.0]
    monkeypatch.setattr(receiver.time, "time", lambda: now[0])
    store = _enqueue(settings)
    def fail(*_):
        raise RuntimeError("untrusted details")
    assert run_once(store, settings, fail) == "retry"
    now[0] = 2005
    assert run_once(store, settings, fail) == "retry"
    now[0] = 2015
    assert run_once(store, settings, fail) == "dead"
    with pytest.raises(ValueError):
        store.replay_dead("123456", settings.synthetic_lead_ids)
    assert store.replay_dead(LEAD, settings.synthetic_lead_ids)
    assert store.health()["queue"] == {"retry": 1}


def test_health_is_redacted_and_retention_prunes_old_terminal_and_audit(settings):
    store = _enqueue(settings)
    store.complete(store.claim()["lead_id"])
    health = store.health()
    assert health == {"storage": "ok", "queue": {"done": 1}, "audit_rows": 2}
    assert LEAD not in json.dumps(health)
    old = __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    assert store.prune(30, now=old) == {"notifications": 0, "audit": 0}
    future = __import__("datetime").datetime(2027, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    assert store.prune(30, now=future) == {"notifications": 1, "audit": 2}
