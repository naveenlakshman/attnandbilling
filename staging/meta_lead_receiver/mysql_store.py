"""MySQL 8 durable inbox for the isolated Meta staging receiver."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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

    @staticmethod
    def _audit(cur, action: str, counts: dict[str, int]):
        cur.execute("INSERT INTO audit(happened_at,action,counts_json) VALUES(%s,%s,%s)",
                    (_now(), action, json.dumps(counts, sort_keys=True, separators=(",", ":"))))

    def ingest(self, events: list[dict], settings: Settings) -> dict[str, int]:
        counts = {"accepted": 0, "duplicate": 0, "ignored": 0}
        now = _now()
        try:
            with self.connection() as conn, conn.cursor() as cur:
                conn.begin()
                for event in events:
                    lead_id = event.get("leadgen_id")
                    if (event.get("page_id") != settings.page_id or event.get("form_id") != settings.form_id
                            or not isinstance(lead_id, str) or lead_id not in settings.synthetic_lead_ids):
                        counts["ignored"] += 1
                        continue
                    cur.execute("""INSERT IGNORE INTO notifications
                        (lead_id,page_id,form_id,ad_id,submitted_at,state,attempts,available_at,created_at,updated_at)
                        VALUES(%s,%s,%s,%s,%s,'PENDING',0,%s,%s,%s)""",
                        (lead_id, settings.page_id, settings.form_id, _numeric_or_none(event.get("ad_id")),
                         _time_or_none(event.get("created_time")), now, now, now))
                    counts["accepted" if cur.rowcount == 1 else "duplicate"] += 1
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
                cur.execute("""SELECT lead_id,page_id,form_id,ad_id,submitted_at,attempts
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
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None
