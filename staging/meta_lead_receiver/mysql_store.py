"""MySQL 8 durable inbox for the isolated Meta staging receiver."""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pymysql
from pymysql.cursors import DictCursor

from .receiver import Settings, StorageError, _safe_error_code, _validated_result


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class MySQLConfig:
    database: str
    user: str
    password: str
    host: str = "127.0.0.1"
    port: int = 3306
    unix_socket: str | None = None

    def __post_init__(self):
        if not self.database or not self.user or not self.password:
            raise ValueError("Dedicated staging database credentials are required.")
        if not self.unix_socket and (not self.host or not 1 <= self.port <= 65535):
            raise ValueError("A valid MySQL host and port are required.")


@dataclass(frozen=True)
class ERPMapping:
    database: str
    institute_id: int
    branch_id: int
    course_id: int
    batch_id: int
    counsellor_user_id: int
    followup_delay_days: int = 0

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", self.database):
            raise ValueError("ERP database name is invalid.")
        if any(value < 1 for value in (self.institute_id, self.branch_id, self.course_id,
                                       self.batch_id, self.counsellor_user_id)):
            raise ValueError("Explicit positive ERP mapping IDs are required.")
        if self.followup_delay_days not in range(0, 31):
            raise ValueError("Follow-up delay must be between 0 and 30 days.")

    @classmethod
    def from_item(cls, item: dict, environ=None):
        env = os.environ if environ is None else environ
        return cls(
            database=env.get("META_ERP_DATABASE", "global_it_erp_production"),
            institute_id=int(item.get("institute_id") or 0),
            branch_id=int(item.get("branch_id") or 0),
            course_id=int(item.get("course_id") or 0),
            batch_id=int(item.get("batch_id") or 0),
            counsellor_user_id=int(item.get("counsellor_user_id") or 0),
            followup_delay_days=int(env.get("META_ERP_FOLLOWUP_DELAY_DAYS", "0")),
        )


def mysql_config_from_env(environ=None) -> MySQLConfig:
    env = os.environ if environ is None else environ
    return MySQLConfig(
        database=env.get("META_STAGING_MYSQL_DATABASE", ""),
        user=env.get("META_STAGING_MYSQL_USER", ""),
        password=env.get("META_STAGING_MYSQL_PASSWORD", ""),
        host=env.get("META_STAGING_MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("META_STAGING_MYSQL_PORT", "3306")),
        unix_socket=env.get("META_STAGING_MYSQL_UNIX_SOCKET") or None,
    )


class MySQLStore:
    """Transactional MySQL store. Schema migration is intentionally separate."""

    def __init__(self, config: MySQLConfig, *, connect=None):
        self.config = config
        self._connect_override = connect

    def connect(self):
        if self._connect_override:
            return self._connect_override()
        kwargs = dict(
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
            read_timeout=20,
            write_timeout=20,
        )
        if self.config.unix_socket:
            kwargs["unix_socket"] = self.config.unix_socket
        else:
            kwargs.update(host=self.config.host, port=self.config.port)
        return pymysql.connect(**kwargs)

    @contextmanager
    def connection(self):
        try:
            conn = self.connect()
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL connection unavailable.") from exc
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def worker_lock(self):
        """Instance-wide advisory lock prevents overlapping worker executions."""
        try:
            conn = self.connect()
            with conn.cursor() as cur:
                cur.execute("SELECT GET_LOCK('meta_leads_worker_v1',0) AS acquired")
                row = cur.fetchone()
                acquired = bool(row and row["acquired"] == 1)
            try:
                yield acquired
            finally:
                if acquired:
                    with conn.cursor() as cur:
                        cur.execute("SELECT RELEASE_LOCK('meta_leads_worker_v1')")
        except pymysql.MySQLError as exc:
            raise StorageError("Worker lock unavailable.") from exc
        finally:
            if 'conn' in locals():
                conn.close()

    @staticmethod
    def _audit(cur, action: str, counts: dict[str, int]):
        cur.execute("INSERT INTO audit(happened_at,action,counts_json) VALUES(%s,%s,%s)",
                    (_now(), action, json.dumps(counts, sort_keys=True, separators=(",", ":"))))

    def ingest(self, events: list[dict], settings: Settings) -> dict[str, int]:
        counts = {"accepted": 0, "duplicate": 0, "ignored": 0, "review": 0}
        now = _now()
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                for event in events:
                    lead_id = event.get("leadgen_id")
                    page_id = event.get("page_id")
                    form_id = event.get("form_id")
                    if (not settings.accepts_lead(lead_id)
                            or not _numeric_or_none(page_id) or not _numeric_or_none(form_id)
                            or (settings.processing_mode == "synthetic"
                                and (page_id != settings.page_id or form_id != settings.form_id))):
                        counts["ignored"] += 1
                        continue
                    route = None
                    if settings.processing_mode == "production":
                        cur.execute("""SELECT id,institute_id,branch_id,course_id,batch_id,
                            counsellor_user_id,updated_at FROM routes
                            WHERE page_id=%s AND form_id=%s AND is_active=1 ORDER BY id LIMIT 2""",
                            (page_id, form_id))
                        matches = cur.fetchall()
                        route = matches[0] if len(matches) == 1 else None
                    state = "PENDING" if settings.processing_mode == "synthetic" or route else "REVIEW"
                    snapshot = None
                    if route:
                        snapshot = json.dumps({key: (value.isoformat() if isinstance(value, datetime) else value)
                            for key, value in route.items()}, sort_keys=True, separators=(",", ":"))
                    cur.execute("""INSERT IGNORE INTO notifications
                        (lead_id,page_id,form_id,route_id,ad_id,campaign_id,adset_id,submitted_at,state,
                         attempts,available_at,created_at,updated_at,institute_id,branch_id,course_id,
                         batch_id,counsellor_user_id,mapping_snapshot_json)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (lead_id, page_id, form_id, route["id"] if route else None,
                         _numeric_or_none(event.get("ad_id")), _numeric_or_none(event.get("campaign_id")),
                         _numeric_or_none(event.get("adset_id")), _time_or_none(event.get("created_time")),
                         state, now, now, now, route["institute_id"] if route else None,
                         route["branch_id"] if route else None, route["course_id"] if route else None,
                         route["batch_id"] if route else None, route["counsellor_user_id"] if route else None,
                         snapshot))
                    if cur.rowcount == 1:
                        counts["accepted"] += 1
                        counts["review"] += int(state == "REVIEW")
                    else:
                        counts["duplicate"] += 1
                self._audit(cur, "notification_batch", counts)
                conn.commit()
                return counts
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL inbox transaction failed.") from exc

    def claim(self, lease_seconds: int = 60):
        now = _now()
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                cur.execute("""SELECT lead_id FROM notifications
                    WHERE (state IN ('PENDING','RETRY') AND available_at<=%s)
                       OR (state='PROCESSING' AND lease_until<%s)
                    ORDER BY created_at,lead_id LIMIT 1 FOR UPDATE SKIP LOCKED""", (now, now))
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return None
                lead_id = row["lead_id"]
                cur.execute("UPDATE notifications SET state='PROCESSING',lease_until=%s,updated_at=%s WHERE lead_id=%s",
                            (now + timedelta(seconds=lease_seconds), now, lead_id))
                cur.execute("""SELECT lead_id,page_id,form_id,ad_id,campaign_id,adset_id,submitted_at,
                    attempts,route_id,institute_id,branch_id,course_id,batch_id,counsellor_user_id
                    FROM notifications WHERE lead_id=%s""", (lead_id,))
                item = cur.fetchone()
                conn.commit()
                return item
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL claim failed.") from exc

    def complete(self, lead_id: str, result: dict | None = None):
        result = _validated_result(result)
        now = _now()
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                cur.execute("""UPDATE notifications SET state='DONE',lease_until=NULL,updated_at=%s,completed_at=%s,
                    result_field_names_json=%s,result_answer_count=%s,result_values_sha256=%s
                    WHERE lead_id=%s AND state='PROCESSING'""",
                    (now, now, json.dumps(result["field_names"], separators=(",", ":")),
                     result["answer_count"], result["values_sha256"], lead_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    raise RuntimeError("Notification claim was lost.")
                self._audit(cur, "worker_done", {"count": 1})
                conn.commit()
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL completion failed.") from exc

    def complete_production(self, item: dict, result: dict, mapping: ERPMapping):
        """Create the ERP enquiry and complete the inbox row in one instance transaction."""
        lead = _validated_production_result(item, result)
        now = _now()
        erp = f"`{mapping.database}`"
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                cur.execute("SELECT state,erp_lead_id FROM notifications WHERE lead_id=%s FOR UPDATE",
                            (item["lead_id"],))
                notification = cur.fetchone()
                if not notification or notification["state"] != "PROCESSING":
                    conn.rollback()
                    raise RuntimeError("Notification claim was lost.")
                if notification.get("erp_lead_id"):
                    conn.rollback()
                    raise RuntimeError("Notification already has an ERP enquiry.")
                institute, branch, course, batch, counsellor = self._validate_mapping(cur, erp, mapping)
                cur.execute(f"""SELECT id FROM {erp}.leads
                    WHERE institute_id=%s AND COALESCE(is_deleted,0)=0
                      AND RIGHT(REGEXP_REPLACE(phone,'[^0-9]',''),10)=%s
                    ORDER BY id LIMIT 20""", (mapping.institute_id, lead["phone"]))
                duplicate_ids = [int(row["id"]) for row in cur.fetchall()]
                source = _lead_source(lead.get("platform"))
                score = 15 if source in {"Facebook", "Instagram"} else 10
                submitted = _parse_meta_time(lead["created_time"])
                followup_date = (submitted.astimezone(ZoneInfo(institute["timezone"])).date()
                                 + timedelta(days=mapping.followup_delay_days)).isoformat()
                duplicate_note = (" Possible matching phone enquiry IDs: "
                                  + ", ".join(str(value) for value in duplicate_ids)) if duplicate_ids else ""
                notes = "Imported from Meta Instant Form; no contact recorded." + duplicate_note
                cur.execute(f"""INSERT INTO {erp}.leads
                    (institute_id,name,phone,whatsapp,interested_courses,lead_source,
                     decision_maker,branch_id,parent_discussion_status,visit_status,
                     lead_score,stage,last_contact_date,next_followup_date,notes,status,
                     is_deleted,assigned_to_id,followup_count,created_at,updated_at)
                    VALUES(%s,%s,%s,NULL,%s,%s,'Self',%s,'Pending','Not Visited',%s,
                           'New Lead',NULL,%s,%s,'active',0,%s,0,%s,%s)""",
                    (mapping.institute_id, lead["name"], lead["phone"], course["course_name"], source,
                     mapping.branch_id, score, followup_date, notes, mapping.counsellor_user_id,
                     now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")))
                erp_lead_id = int(cur.lastrowid)
                cur.execute(f"""INSERT INTO {erp}.activity_logs
                    (user_id,branch_id,action_type,module_name,record_id,description,created_at,institute_id)
                    VALUES(%s,%s,'lead_created','leads',%s,%s,%s,%s)""",
                    (mapping.counsellor_user_id, mapping.branch_id, erp_lead_id,
                     f"Meta Instant Form enquiry created - Stage: New Lead, Source: {source}",
                     now.isoformat(timespec="seconds"), mapping.institute_id))
                field_names = [field["name"] for field in lead["field_data"]]
                values_json = json.dumps(lead["field_data"], sort_keys=True, separators=(",", ":"))
                values_sha256 = __import__("hashlib").sha256(values_json.encode()).hexdigest()
                cur.execute("""UPDATE notifications SET state='DONE',lease_until=NULL,updated_at=%s,
                    completed_at=%s,result_field_names_json=%s,result_answer_count=%s,
                    result_values_sha256=%s,answers_json=%s,phone_normalized=%s,platform=%s,
                    ad_id=COALESCE(ad_id,%s),campaign_id=COALESCE(campaign_id,%s),
                    adset_id=COALESCE(adset_id,%s),submitted_at=COALESCE(submitted_at,%s),
                    duplicate_lead_ids_json=%s,erp_lead_id=%s,erp_followup_due_date=%s,
                    institute_id=%s,branch_id=%s,course_id=%s,batch_id=%s,counsellor_user_id=%s
                    WHERE lead_id=%s AND state='PROCESSING'""",
                    (now, now, json.dumps(field_names, separators=(",", ":")), len(field_names),
                     values_sha256, values_json, lead["phone"], lead.get("platform"),
                     lead.get("ad_id"), lead.get("campaign_id"), lead.get("adset_id"),
                     _time_or_none(lead["created_time"]),
                     json.dumps(duplicate_ids, separators=(",", ":")), erp_lead_id, followup_date,
                     mapping.institute_id, mapping.branch_id, mapping.course_id, mapping.batch_id,
                     mapping.counsellor_user_id, item["lead_id"]))
                if cur.rowcount != 1:
                    conn.rollback()
                    raise RuntimeError("Notification completion was lost.")
                self._audit(cur, "worker_production_done", {"count": 1, "phone_match": int(bool(duplicate_ids))})
                conn.commit()
                return {"erp_lead_id": erp_lead_id, "phone_match": bool(duplicate_ids)}
        except (StorageError, RuntimeError):
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("Atomic ERP enquiry creation failed.") from exc

    @staticmethod
    def _validate_mapping(cur, erp: str, mapping: ERPMapping):
        cur.execute(f"SELECT id,timezone FROM {erp}.institutes WHERE id=%s AND status='active'",
                    (mapping.institute_id,))
        institute = cur.fetchone()
        cur.execute(f"SELECT id FROM {erp}.branches WHERE id=%s AND institute_id=%s AND is_active=1",
                    (mapping.branch_id, mapping.institute_id))
        branch = cur.fetchone()
        cur.execute(f"SELECT id,course_name FROM {erp}.courses WHERE id=%s AND institute_id=%s AND is_active=1",
                    (mapping.course_id, mapping.institute_id))
        course = cur.fetchone()
        cur.execute(f"""SELECT id FROM {erp}.batches WHERE id=%s AND course_id=%s AND branch_id=%s
            AND status='active'""", (mapping.batch_id, mapping.course_id, mapping.branch_id))
        batch = cur.fetchone()
        cur.execute(f"""SELECT u.id FROM {erp}.users u
            JOIN {erp}.institute_memberships im ON im.user_id=u.id AND im.institute_id=u.institute_id
            WHERE u.id=%s AND u.institute_id=%s AND (u.branch_id=%s OR u.can_view_all_branches=1)
              AND u.is_active=1 AND im.is_active=1""",
                    (mapping.counsellor_user_id, mapping.institute_id, mapping.branch_id))
        counsellor = cur.fetchone()
        if not all((institute, branch, course, batch, counsellor)):
            raise RuntimeError("Configured ERP mapping is no longer valid.")
        return institute, branch, course, batch, counsellor

    def fail(self, lead_id: str, *, attempts: int, max_attempts: int, retry_base: int, error_code: str):
        dead = attempts + 1 >= max_attempts
        delay = min(retry_base * (2 ** attempts), 3600)
        state = "DEAD" if dead else "RETRY"
        now = _now()
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                cur.execute("""UPDATE notifications SET state=%s,attempts=attempts+1,available_at=%s,
                    lease_until=NULL,updated_at=%s,last_error_code=%s
                    WHERE lead_id=%s AND state='PROCESSING'""",
                    (state, now + timedelta(seconds=delay), now, _safe_error_code(error_code), lead_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    raise RuntimeError("Notification claim was lost.")
                self._audit(cur, "worker_dead" if dead else "worker_retry", {"count": 1})
                conn.commit()
            return state, delay
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL retry update failed.") from exc

    def replay_dead(self, lead_id: str, allowlist: frozenset[str]):
        if lead_id not in allowlist:
            raise ValueError("Manual replay is restricted to configured synthetic IDs.")
        now = _now()
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                cur.execute("""UPDATE notifications SET state='RETRY',attempts=0,available_at=%s,
                    lease_until=NULL,updated_at=%s,last_error_code=NULL
                    WHERE lead_id=%s AND state='DEAD'""", (now, now, lead_id))
                if cur.rowcount != 1:
                    conn.rollback()
                    return False
                self._audit(cur, "controlled_replay", {"count": 1})
                conn.commit()
                return True
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL replay failed.") from exc

    def prune(self, retention_days: int, now: datetime | None = None):
        cutoff = (now or datetime.now(timezone.utc)).replace(tzinfo=None) - timedelta(days=retention_days)
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                cur.execute("DELETE FROM notifications WHERE state IN ('DONE','DEAD') AND updated_at<%s", (cutoff,))
                notifications = cur.rowcount
                cur.execute("DELETE FROM audit WHERE happened_at<%s", (cutoff,))
                audit = cur.rowcount
                conn.commit()
                return {"notifications": notifications, "audit": audit}
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL retention cleanup failed.") from exc

    def health(self):
        try:
            with self.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT state,COUNT(*) AS n FROM notifications GROUP BY state")
                counts = {row["state"].lower(): row["n"] for row in cur.fetchall()}
                cur.execute("SELECT COUNT(*) AS n FROM audit")
                audits = cur.fetchone()["n"]
                return {"storage": "ok", "queue": counts, "audit_rows": audits}
        except StorageError:
            raise
        except pymysql.MySQLError as exc:
            raise StorageError("MySQL health query failed.") from exc


def mysql_store_from_env(environ=None) -> MySQLStore:
    return MySQLStore(mysql_config_from_env(environ))


def _numeric_or_none(value):
    return value if isinstance(value, str) and value.isdigit() and len(value) <= 40 else None


def _time_or_none(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 0 <= value <= 4102444800:
        return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        if value.isdigit():
            seconds = int(value)
            return (datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None)
                    if 0 <= seconds <= 4102444800 else None)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except (OSError, OverflowError, ValueError):
        return None


def _validated_production_result(item: dict, result: dict) -> dict:
    if (not isinstance(result, dict) or result.get("lead_id") != item.get("lead_id")
            or result.get("form_id") != item.get("form_id")
            or not isinstance(result.get("name"), str) or not 1 <= len(result["name"].strip()) <= 255
            or not isinstance(result.get("phone"), str) or not re.fullmatch(r"[6-9][0-9]{9}", result["phone"])
            or not isinstance(result.get("created_time"), str)
            or not isinstance(result.get("field_data"), list)):
        raise ValueError("Retrieved production lead is invalid.")
    encoded = json.dumps(result["field_data"], sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > 64 * 1024:
        raise ValueError("Retrieved lead answers exceed the storage limit.")
    return result


def _parse_meta_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Meta submission time is invalid.") from exc


def _lead_source(platform: str | None) -> str:
    value = (platform or "").strip().lower()
    if "instagram" in value or value == "ig":
        return "Instagram"
    if "facebook" in value or value == "fb":
        return "Facebook"
    return "Meta Instant Form"
