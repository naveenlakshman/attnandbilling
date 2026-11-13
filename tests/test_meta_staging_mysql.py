import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymysql
import pytest

from staging.meta_lead_receiver.mysql_store import ERPMapping, MySQLConfig, MySQLStore
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
    migrations = [Path(path).read_text(encoding="utf8") for path in (
        "staging/meta_lead_receiver/migrations/001_inbox.sql",
        "staging/meta_lead_receiver/migrations/002_configurable_routing.sql",
    )]
    for _ in range(2):
        with store.connection() as db, db.cursor() as cur:
            for migration in migrations:
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
            "ad_id": "123", "created_time": 1794528000}


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


def _production_result(lead_id, phone="9876543210"):
    return {"lead_id": lead_id, "form_id": FORM, "created_time": "2026-11-18T06:30:00+00:00",
            "ad_id": "123", "campaign_id": "456", "adset_id": "789",
            "platform": "instagram", "name": "Meta Test Person", "phone": phone,
            "field_data": [{"name": "full_name", "values": ["Meta Test Person"]},
                           {"name": "phone_number", "values": [phone]},
                           {"name": "when_would_you_like_to_join?", "values": ["Immediately"]}]}


def _mapping(batch_id=50):
    return ERPMapping(database="erp_receiver_test", institute_id=1, branch_id=2, course_id=43,
                      batch_id=batch_id, counsellor_user_id=3)


@pytest.fixture
def erp_schema(mysql_store):
    admin = _admin_config()
    conn = pymysql.connect(**admin)
    with conn.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS erp_receiver_test")
        cur.execute("CREATE DATABASE erp_receiver_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cur.execute("""CREATE TABLE erp_receiver_test.institutes(
            id BIGINT PRIMARY KEY,status VARCHAR(20),timezone VARCHAR(64))""")
        cur.execute("""CREATE TABLE erp_receiver_test.branches(
            id INT PRIMARY KEY,institute_id BIGINT,is_active INT)""")
        cur.execute("""CREATE TABLE erp_receiver_test.courses(
            id INT PRIMARY KEY,institute_id BIGINT,is_active INT,course_name VARCHAR(255))""")
        cur.execute("""CREATE TABLE erp_receiver_test.batches(
            id INT PRIMARY KEY,course_id INT,branch_id INT,start_date VARCHAR(32),end_date VARCHAR(32),
            start_time VARCHAR(32),end_time VARCHAR(32),status VARCHAR(32))""")
        cur.execute("""CREATE TABLE erp_receiver_test.users(
            id INT PRIMARY KEY,institute_id BIGINT,branch_id INT,can_view_all_branches INT,is_active INT)""")
        cur.execute("""CREATE TABLE erp_receiver_test.institute_memberships(
            user_id INT,institute_id BIGINT,is_active INT)""")
        cur.execute("""CREATE TABLE erp_receiver_test.leads(
            id INT AUTO_INCREMENT PRIMARY KEY,institute_id BIGINT,name VARCHAR(255),phone VARCHAR(255),
            whatsapp VARCHAR(255),interested_courses VARCHAR(255),lead_source VARCHAR(255),
            decision_maker VARCHAR(255),branch_id INT,parent_discussion_status VARCHAR(255),
            visit_status VARCHAR(255),lead_score INT,stage VARCHAR(255),last_contact_date VARCHAR(255),
            next_followup_date VARCHAR(255),notes TEXT,status VARCHAR(255),is_deleted INT,
            assigned_to_id INT,followup_count INT,created_at VARCHAR(255),updated_at VARCHAR(255))""")
        cur.execute("""CREATE TABLE erp_receiver_test.activity_logs(
            id INT AUTO_INCREMENT PRIMARY KEY,user_id INT,branch_id INT,action_type VARCHAR(255),
            module_name VARCHAR(255),record_id INT,description TEXT,created_at VARCHAR(255),institute_id INT)""")
        cur.execute("INSERT INTO erp_receiver_test.institutes VALUES(1,'active','Asia/Kolkata')")
        cur.execute("INSERT INTO erp_receiver_test.branches VALUES(2,1,1)")
        cur.execute("INSERT INTO erp_receiver_test.courses VALUES(43,1,1,'DFA 2026 With AI for Accounting')")
        cur.execute("INSERT INTO erp_receiver_test.batches VALUES(50,43,2,'2026-11-18','2027-04-10','12:00','14:00','active')")
        cur.execute("INSERT INTO erp_receiver_test.users VALUES(3,1,1,1,1)")
        cur.execute("INSERT INTO erp_receiver_test.institute_memberships VALUES(3,1,1)")
    with mysql_store.connection() as inbox, inbox.cursor() as cur:
        cur.execute("""INSERT INTO routes(institute_id,page_id,form_id,course_id,batch_id,branch_id,
            counsellor_user_id,is_active,created_by_user_id,updated_by_user_id,created_at,updated_at)
            VALUES(1,%s,%s,43,50,2,3,1,1,1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""", (PAGE, FORM))
        inbox.commit()
    conn.close()
    yield
    conn = pymysql.connect(**admin)
    with conn.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS erp_receiver_test")
    conn.close()


def test_production_completion_atomically_creates_enquiry_and_pending_task(mysql_store, erp_schema):
    production = Settings("", "secret", "verify", PAGE, FORM, frozenset(), storage_backend="mysql",
                          enabled=True, processing_mode="production")
    lead_id = "800000000000001"
    event = _event(lead_id)
    event["ad_id"] = None
    event["created_time"] = None
    assert mysql_store.ingest([event], production)["accepted"] == 1
    item = mysql_store.claim()
    result = mysql_store.complete_production(item, _production_result(lead_id), _mapping())
    assert result == {"erp_lead_id": 1, "phone_match": False}
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT stage,last_contact_date,next_followup_date,followup_count,assigned_to_id,branch_id,lead_source FROM erp_receiver_test.leads")
        row = cur.fetchone()
        assert row == {"stage": "New Lead", "last_contact_date": None, "next_followup_date": "2026-11-18",
                       "followup_count": 0, "assigned_to_id": 3, "branch_id": 2, "lead_source": "Instagram"}
        cur.execute("""SELECT state,erp_lead_id,answers_json,batch_id,ad_id,campaign_id,adset_id,submitted_at
                    FROM notifications WHERE lead_id=%s""", (lead_id,))
        inbox = cur.fetchone()
        assert inbox["state"] == "DONE" and inbox["erp_lead_id"] == 1 and inbox["batch_id"] == 50
        assert inbox["ad_id"] == "123"
        assert inbox["campaign_id"] == "456" and inbox["adset_id"] == "789"
        assert inbox["submitted_at"].isoformat() == "2026-11-18T06:30:00"
        assert "Meta Test Person" in str(inbox["answers_json"])
        cur.execute("SELECT COUNT(*) AS n FROM erp_receiver_test.activity_logs")
        assert cur.fetchone()["n"] == 1


def test_production_phone_match_is_visible_without_overwriting_history(mysql_store, erp_schema):
    production = Settings("", "secret", "verify", PAGE, FORM, frozenset(), storage_backend="mysql",
                          enabled=True, processing_mode="production")
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO erp_receiver_test.leads(institute_id,name,phone,is_deleted) VALUES(1,'Existing','98765-43210',0)")
        conn.commit()
    lead_id = "800000000000002"
    mysql_store.ingest([_event(lead_id)], production)
    result = mysql_store.complete_production(mysql_store.claim(), _production_result(lead_id), _mapping())
    assert result["phone_match"] is True and result["erp_lead_id"] == 2
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name,notes FROM erp_receiver_test.leads ORDER BY id")
        rows = cur.fetchall()
        assert rows[0]["name"] == "Existing" and "Possible matching phone enquiry IDs: 1" in rows[1]["notes"]


def test_invalid_production_mapping_rolls_back_enquiry(mysql_store, erp_schema):
    production = Settings("", "secret", "verify", PAGE, FORM, frozenset(), storage_backend="mysql",
                          enabled=True, processing_mode="production")
    lead_id = "800000000000003"
    mysql_store.ingest([_event(lead_id)], production)
    item = mysql_store.claim()
    with pytest.raises(RuntimeError, match="mapping"):
        mysql_store.complete_production(item, _production_result(lead_id), _mapping(batch_id=999))
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM erp_receiver_test.leads")
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT state,erp_lead_id FROM notifications WHERE lead_id=%s", (lead_id,))
        assert cur.fetchone() == {"state": "PROCESSING", "erp_lead_id": None}


def test_unknown_production_mapping_remains_review_and_is_not_claimed(mysql_store):
    production = Settings("", "secret", "verify", PAGE, FORM, frozenset(), storage_backend="mysql",
                          enabled=True, processing_mode="production")
    result = mysql_store.ingest([_event("800000000000099")], production)
    assert result == {"accepted": 1, "duplicate": 0, "ignored": 0, "review": 1}
    assert mysql_store.claim() is None
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT state,route_id,course_id FROM notifications")
        assert cur.fetchone() == {"state": "REVIEW", "route_id": None, "course_id": None}


def test_route_snapshot_is_preserved_when_route_changes(mysql_store, erp_schema):
    production = Settings("", "secret", "verify", PAGE, FORM, frozenset(), storage_backend="mysql",
                          enabled=True, processing_mode="production")
    lead_id = "800000000000098"
    assert mysql_store.ingest([_event(lead_id)], production)["accepted"] == 1
    with mysql_store.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE routes SET course_id=99,batch_id=99 WHERE page_id=%s AND form_id=%s", (PAGE, FORM))
        cur.execute("SELECT course_id,batch_id,mapping_snapshot_json FROM notifications WHERE lead_id=%s", (lead_id,))
        row = cur.fetchone()
        assert row["course_id"] == 43 and row["batch_id"] == 50
        assert json.loads(row["mapping_snapshot_json"])["course_id"] == 43
        conn.rollback()
