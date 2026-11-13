import json

from staging.meta_lead_receiver import worker


PAGE = "300480973645515"
FORM = "1806095097277660"
LEAD = "900000000000001"


def _env(monkeypatch, tmp_path, *, enabled):
    values = {
        "META_STAGING_DB_PATH": str(tmp_path / "worker.db"),
        "META_STAGING_STORAGE": "mysql" if enabled else "sqlite",
        "META_STAGING_PAGE_ID": PAGE,
        "META_STAGING_FORM_ID": FORM,
        "META_STAGING_SYNTHETIC_LEAD_IDS": json.dumps([LEAD]),
        "META_STAGING_ENABLED": "true" if enabled else "false",
        "META_STAGING_SYSTEM_USER_TOKEN": "private-system-token",
        "META_GRAPH_VERSION": "v27.0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_disabled_worker_exits_without_opening_storage(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, enabled=False)
    monkeypatch.setattr(worker, "mysql_store_from_env",
                        lambda: (_ for _ in ()).throw(AssertionError("storage must not open")))
    assert worker.main(["--max-items", "1"]) == 0


def test_worker_drains_until_idle_and_reports_no_ids(monkeypatch, tmp_path, caplog):
    _env(monkeypatch, tmp_path, enabled=True)
    outcomes = iter(["done", "retry", "idle"])
    fake_store = object()
    monkeypatch.setattr(worker, "mysql_store_from_env", lambda: fake_store)
    monkeypatch.setattr(worker, "MetaSyntheticProcessor", lambda *args, **kwargs: object())
    monkeypatch.setattr(worker, "run_once", lambda store, settings, processor: next(outcomes))
    with caplog.at_level("INFO"):
        assert worker.main(["--max-items", "10"]) == 0
    output = " ".join(record.message for record in caplog.records)
    assert '"done": 1' in output
    assert '"retry": 1' in output
    assert LEAD not in output
    assert "private-system-token" not in output


def test_controlled_replay_delegates_to_allowlist_guard(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, enabled=True)
    class Store:
        def replay_dead(self, lead_id, allowlist):
            assert lead_id == LEAD
            assert lead_id in allowlist
            return True
    monkeypatch.setattr(worker, "mysql_store_from_env", Store)
    assert worker.main(["--replay-dead", LEAD]) == 0
