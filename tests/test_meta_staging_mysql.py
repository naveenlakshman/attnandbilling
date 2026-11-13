import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymysql
import pytest

from staging.meta_lead_receiver.mysql_store import MySQLConfig, MySQLStore
from staging.meta_lead_receiver.receiver import Settings, StorageError, run_once


PAGE = "300480973645515"
FORM = "1806095097277660"
LEADS = [f"900000000000{i:03d}" for i in range(1, 51)]


def _admin_config():
    if os.environ.get("META_TEST_MYSQL_ENABLED") != "true":
        pytest.skip("isolated MySQL integration environment not configured")
    return dict(host=os.environ.get("META_TEST_MYSQL_HOST", "127.0.0.1"),
                port=int(os.environ.get("META_TEST_MYSQL_PORT", "33345")),
                user=os.environ.get("META_TEST_MYSQL_USER", "root"),
                password=os.environ.get("META_TEST_MYSQL_PASSWORD", ""),
                charset="utf8mb4", autocommit=True)


@pytest.fixture
def mysql_store():
    admin = _admin_config()
    database = "meta_receiver_test"
    conn = pymysql.connect(**admin)
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {database}")
        cur.execute(f"CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    conn.close()
    config = MySQLConfig(database=database, user=admin["user"], password=admin["password"],
                         host=admin["host"], port=admin["port"])
    store = MySQLStore(config)
    migration = Path("staging/meta_lead_receiver/migrations/001_inbox.sql").read_text(encoding="utf8")
    for _ in range(2):
        with store.connection() as db, db.cursor() as cur:
            for statement in (part.strip() for part in migration.split(";")):
                if statement:
                    cur.execute(statement)
            db.commit()
    yield store
    conn = pymysql.connect(**admin)
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {database}")
    conn.close()


@pytest.fixture
def settings():
    return Settings("", "app-secret", "verify", PAGE, FORM, frozenset(LEADS),
                    storage_backend="mysql", enabled=True, max_attempts=3, retry_base_seconds=1)


def _event(lead):
    return {"leadgen_id": lead, "page_id": PAGE, "form_id": FORM,
            "ad_id": "123", "created_time": "2026-11-13T00:00:00+00:00"}


def test_migration_repeatable_and_concurrent_duplicate_insert_is_atomic(mysql_store, settings):
    barrier = threading.Barrier(16)
    def submit(_):
        barrier.wait()
        return mysql_store.ingest([_event(LEADS[0])], settings)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(submit, range(16)))
    assert sum(x["accepted"] for x in results) == 1
    assert sum(x["duplicate"] for x in results) == 15
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM notifications")
        assert cur.fetchone()["n"] == 1


def test_batch_transaction_failure_rolls_back_all_rows(mysql_store, settings):
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("""CREATE TRIGGER reject_second BEFORE INSERT ON notifications FOR EACH ROW
            BEGIN IF NEW.lead_id=%s THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='forced'; END IF; END""",
                    (LEADS[2],))
        conn.commit()
    with pytest.raises(StorageError):
        mysql_store.ingest([_event(LEADS[1]), _event(LEADS[2])], settings)
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("DROP TRIGGER reject_second")
        cur.execute("SELECT COUNT(*) AS n FROM notifications")
        assert cur.fetchone()["n"] == 0
        conn.commit()


def test_concurrent_workers_claim_each_row_once(mysql_store, settings):
    expected = set(LEADS[:24])
    assert mysql_store.ingest([_event(x) for x in expected], settings)["accepted"] == len(expected)
    seen = []
    lock = threading.Lock()
    def consume():
        while True:
            item = mysql_store.claim(lease_seconds=30)
            if item is None:
                return
            with lock:
                seen.append(item["lead_id"])
            mysql_store.complete(item["lead_id"], {"field_names": ["full_name"],
                "answer_count": 1, "values_sha256": "a" * 64})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: consume(), range(8)))
    assert len(seen) == len(expected)
    assert set(seen) == expected
    assert mysql_store.health()["queue"] == {"done": len(expected)}


def test_lease_recovery_retry_dead_letter_and_controlled_replay(mysql_store, settings):
    mysql_store.ingest([_event(LEADS[0])], settings)
    first = mysql_store.claim(lease_seconds=60)
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE notifications SET lease_until=%s WHERE lead_id=%s",
                    (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1), LEADS[0]))
        conn.commit()
    recovered = mysql_store.claim(lease_seconds=60)
    assert recovered["lead_id"] == first["lead_id"]
    mysql_store.fail(LEADS[0], attempts=0, max_attempts=1, retry_base=1, error_code="upstream_timeout")
    assert mysql_store.health()["queue"] == {"dead": 1}
    with pytest.raises(ValueError):
        mysql_store.replay_dead("123", settings.synthetic_lead_ids)
    assert mysql_store.replay_dead(LEADS[0], settings.synthetic_lead_ids)
    assert mysql_store.health()["queue"] == {"retry": 1}


def test_worker_completion_failure_does_not_mark_processing_failure(mysql_store, settings, monkeypatch):
    mysql_store.ingest([_event(LEADS[0])], settings)
    def completion_failure(*args, **kwargs):
        raise StorageError("commit outcome unknown")
    monkeypatch.setattr(mysql_store, "complete", completion_failure)
    with pytest.raises(StorageError):
        run_once(mysql_store, settings, lambda _: {"field_names": [], "answer_count": 0,
                                                   "values_sha256": None})
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT state,attempts FROM notifications WHERE lead_id=%s", (LEADS[0],))
        row = cur.fetchone()
    assert row == {"state": "PROCESSING", "attempts": 0}


def test_connection_failure_is_safe_storage_error(settings):
    store = MySQLStore(MySQLConfig(database="missing", user="nobody", password="invalid",
                                   host="127.0.0.1", port=1))
    with pytest.raises(StorageError, match="connection unavailable"):
        store.health()
