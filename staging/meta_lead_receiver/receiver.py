"""Local-only Meta webhook receiver with a synthetic-ID allowlist.

This module stores notification metadata, never request bodies or lead answers.
It has no ERP, messaging, Meta-fetch, or production credential integration.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, request


MAX_BODY_BYTES = 64 * 1024
LEAD_ID_RE = re.compile(r"^[0-9]{1,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FIELD_NAME_RE = re.compile(r"^[a-zA-Z0-9_? -]{1,160}$")
logger = logging.getLogger("meta_staging_receiver")


class StorageError(RuntimeError):
    """Safe boundary for retryable storage failures."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Settings:
    db_path: str
    app_secret: str
    verify_token: str
    page_id: str
    form_id: str
    synthetic_lead_ids: frozenset[str]
    storage_backend: str = "sqlite"
    enabled: bool = False
    verify_enabled: bool = False
    max_attempts: int = 5
    retention_days: int = 30
    retry_base_seconds: int = 5
    processing_mode: str = "synthetic"

    def __post_init__(self):
        if self.storage_backend not in {"sqlite", "mysql"}:
            raise ValueError("Storage backend must be sqlite or mysql.")
        if self.storage_backend == "sqlite" and (not self.db_path or self.db_path == ":memory:"):
            raise ValueError("Use a durable local file path; in-memory storage is unsupported.")
        if not self.page_id.isdigit() or not self.form_id.isdigit():
            raise ValueError("Explicit numeric Page and Form IDs are required.")
        if any(not LEAD_ID_RE.fullmatch(value) for value in self.synthetic_lead_ids):
            raise ValueError("The synthetic allowlist must contain numeric Meta lead IDs only.")
        if self.max_attempts < 1 or self.retention_days < 1 or self.retry_base_seconds < 1:
            raise ValueError("Retry and retention settings must be positive.")
        if self.processing_mode not in {"synthetic", "production"}:
            raise ValueError("Processing mode must be synthetic or production.")

    def accepts_lead(self, lead_id: object) -> bool:
        if not isinstance(lead_id, str) or not LEAD_ID_RE.fullmatch(lead_id):
            return False
        return self.processing_mode == "production" or lead_id in self.synthetic_lead_ids


def settings_from_env(environ=None) -> Settings:
    env = os.environ if environ is None else environ
    try:
        lead_ids = json.loads(env.get("META_STAGING_SYNTHETIC_LEAD_IDS", "[]"))
    except json.JSONDecodeError as exc:
        raise ValueError("META_STAGING_SYNTHETIC_LEAD_IDS must be a JSON array.") from exc
    if not isinstance(lead_ids, list) or any(not isinstance(x, str) for x in lead_ids):
        raise ValueError("META_STAGING_SYNTHETIC_LEAD_IDS must be a JSON array of strings.")
    enabled = env.get("META_STAGING_ENABLED", "false").lower() == "true"
    verify_enabled = env.get("META_STAGING_VERIFY_ENABLED", "false").lower() == "true"
    return Settings(db_path=env.get("META_STAGING_DB_PATH", ""),
                    app_secret=env.get("META_STAGING_APP_SECRET", ""),
                    verify_token=env.get("META_STAGING_VERIFY_TOKEN", ""),
                    page_id=env.get("META_STAGING_PAGE_ID", ""),
                    form_id=env.get("META_STAGING_FORM_ID", ""),
                    synthetic_lead_ids=frozenset(lead_ids),
                    storage_backend=env.get("META_STAGING_STORAGE", "sqlite").lower(), enabled=enabled,
                    verify_enabled=verify_enabled,
                    processing_mode=env.get("META_PROCESSING_MODE", "synthetic").lower())


class Store:
    """SQLite durable inbox. Connections are short-lived and transactions atomic."""

    def __init__(self, path: str):
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self):
        with self._init_lock, self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS notifications (
                    lead_id TEXT PRIMARY KEY,
                    page_id TEXT NOT NULL,
                    form_id TEXT NOT NULL,
                    ad_id TEXT,
                    submitted_at TEXT,
                    state TEXT NOT NULL CHECK(state IN ('PENDING','PROCESSING','RETRY','DONE','DEAD')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    lease_until REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error_code TEXT,
                    result_field_names_json TEXT,
                    result_answer_count INTEGER,
                    result_values_sha256 TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_notifications_ready
                    ON notifications(state, available_at, created_at);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    happened_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    counts_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_audit_time ON audit(happened_at);
            """)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(notifications)")}
            for name, column_type in {
                "result_field_names_json": "TEXT",
                "result_answer_count": "INTEGER",
                "result_values_sha256": "TEXT",
                "completed_at": "TEXT",
            }.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE notifications ADD COLUMN {name} {column_type}")

    @staticmethod
    def audit(conn, action: str, counts: dict[str, int]):
        # Counts only. Never store lead IDs, form answers, headers, or raw bodies.
        conn.execute("INSERT INTO audit(happened_at,action,counts_json) VALUES(?,?,?)",
                     (utc_now(), action, json.dumps(counts, sort_keys=True)))

    def ingest(self, events: list[dict], settings: Settings) -> dict[str, int]:
        counts = {"accepted": 0, "duplicate": 0, "ignored": 0}
        now = utc_now()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for event in events:
                lead_id = event.get("leadgen_id")
                if (event.get("page_id") != settings.page_id or event.get("form_id") != settings.form_id
                        or not settings.accepts_lead(lead_id)):
                    counts["ignored"] += 1
                    continue
                cur = conn.execute("""INSERT OR IGNORE INTO notifications
                    (lead_id,page_id,form_id,ad_id,submitted_at,state,attempts,available_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,'PENDING',0,?,?,?)""",
                    (lead_id, settings.page_id, settings.form_id, _optional_id(event.get("ad_id")),
                     _optional_time(event.get("created_time")), time.time(), now, now))
                if cur.rowcount:
                    counts["accepted"] += 1
                else:
                    counts["duplicate"] += 1
            self.audit(conn, "notification_batch", counts)
            conn.commit()
            return counts
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim(self, lease_seconds: int = 60):
        now = time.time()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT lead_id FROM notifications
                WHERE (state IN ('PENDING','RETRY') AND available_at<=?)
                   OR (state='PROCESSING' AND lease_until<?)
                ORDER BY created_at,lead_id LIMIT 1""", (now, now)).fetchone()
            if row is None:
                conn.commit()
                return None
            lead_id = row["lead_id"]
            conn.execute("UPDATE notifications SET state='PROCESSING', lease_until=?, updated_at=? WHERE lead_id=?",
                         (now + lease_seconds, utc_now(), lead_id))
            item = dict(conn.execute("SELECT lead_id,page_id,form_id,ad_id,submitted_at,attempts FROM notifications WHERE lead_id=?",
                                     (lead_id,)).fetchone())
            conn.commit()
            return item
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete(self, lead_id: str, result: dict | None = None):
        result = _validated_result(result)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = utc_now()
            cur = conn.execute("""UPDATE notifications SET state='DONE',lease_until=NULL,updated_at=?,completed_at=?,
                result_field_names_json=?,result_answer_count=?,result_values_sha256=?
                WHERE lead_id=? AND state='PROCESSING'""",
                (now, now, json.dumps(result["field_names"], separators=(",", ":")),
                 result["answer_count"], result["values_sha256"], lead_id))
            if cur.rowcount != 1:
                conn.rollback()
                raise RuntimeError("Notification claim was lost.")
            self.audit(conn, "worker_done", {"count": 1})
            conn.commit()

    def fail(self, lead_id: str, *, attempts: int, max_attempts: int, retry_base: int, error_code: str):
        dead = attempts + 1 >= max_attempts
        delay = min(retry_base * (2 ** attempts), 3600)
        state = "DEAD" if dead else "RETRY"
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("UPDATE notifications SET state=?,attempts=attempts+1,available_at=?,lease_until=NULL,updated_at=?,last_error_code=? WHERE lead_id=? AND state='PROCESSING'",
                               (state, time.time() + delay, utc_now(), _safe_error_code(error_code), lead_id))
            if cur.rowcount != 1:
                conn.rollback()
                raise RuntimeError("Notification claim was lost.")
            self.audit(conn, "worker_retry" if not dead else "worker_dead", {"count": 1})
            conn.commit()
        return state, delay

    def replay_dead(self, lead_id: str, allowlist: frozenset[str]):
        if lead_id not in allowlist:
            raise ValueError("Manual replay is restricted to configured synthetic IDs.")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("UPDATE notifications SET state='RETRY',attempts=0,available_at=?,lease_until=NULL,updated_at=?,last_error_code=NULL WHERE lead_id=? AND state='DEAD'",
                               (time.time(), utc_now(), lead_id))
            if cur.rowcount != 1:
                conn.rollback()
                return False
            self.audit(conn, "controlled_replay", {"count": 1})
            conn.commit()
            return True

    def prune(self, retention_days: int, now: datetime | None = None):
        cutoff = ((now or datetime.now(timezone.utc)).timestamp() - retention_days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat(timespec="seconds")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            notifications = conn.execute("DELETE FROM notifications WHERE state IN ('DONE','DEAD') AND updated_at<?",
                                         (cutoff_iso,)).rowcount
            audit = conn.execute("DELETE FROM audit WHERE happened_at<?", (cutoff_iso,)).rowcount
            conn.commit()
        return {"notifications": notifications, "audit": audit}

    def health(self):
        with self.connection() as conn:
            counts = {row["state"].lower(): row["n"] for row in conn.execute(
                "SELECT state,COUNT(*) AS n FROM notifications GROUP BY state")}
            audits = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        return {"storage": "ok", "queue": counts, "audit_rows": audits}


def _optional_id(value):
    return value if isinstance(value, str) and LEAD_ID_RE.fullmatch(value) else None


def _optional_time(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 0 <= value <= 4102444800:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
    return value[:64] if isinstance(value, str) and len(value) <= 64 else None


def _safe_error_code(value: str):
    return value if value in {"upstream_timeout", "upstream_unavailable", "rate_limited", "invalid_response", "unknown"} else "unknown"


def _validated_result(result: dict | None) -> dict:
    result = result or {"field_names": [], "answer_count": 0, "values_sha256": None}
    names = result.get("field_names")
    count = result.get("answer_count")
    digest = result.get("values_sha256")
    if (not isinstance(names, list) or any(not isinstance(name, str) or not FIELD_NAME_RE.fullmatch(name)
                                           for name in names)
            or not isinstance(count, int) or count < 0 or count != len(names)
            or (digest is not None and (not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)))):
        raise ValueError("Processor result must contain redacted field names, count and SHA-256 only.")
    return {"field_names": names, "answer_count": count, "values_sha256": digest}


def valid_signature(raw: bytes, header: str | None, secret: str) -> bool:
    if not isinstance(header, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", header):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def parse_events(payload) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("object") != "page" or not isinstance(payload.get("entry"), list):
        raise ValueError("Invalid webhook envelope.")
    events = []
    for entry in payload["entry"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes", []), list):
            raise ValueError("Invalid webhook entry.")
        for change in entry.get("changes", []):
            if not isinstance(change, dict):
                raise ValueError("Invalid webhook change.")
            if change.get("field") != "leadgen":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                raise ValueError("Invalid lead notification.")
            events.append({k: value.get(k) for k in ("leadgen_id", "page_id", "form_id", "ad_id", "created_time")})
    return events


def create_app(settings: Settings, *, store=None):
    if not settings.app_secret or not settings.verify_token:
        raise ValueError("Webhook secrets must be configured outside source control.")
    if store is None:
        if settings.storage_backend == "mysql":
            from .mysql_store import mysql_store_from_env
            store = mysql_store_from_env()
        else:
            store = Store(settings.db_path)
    db = store
    app = Flask("meta_staging_receiver")
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    app.extensions["meta_staging_store"] = db
    app.extensions["meta_staging_settings"] = settings

    @app.get("/webhook/meta")
    def verify_webhook():
        if not settings.verify_enabled:
            return "disabled", 503
        mode = request.args.get("hub.mode", "")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        if mode != "subscribe" or not challenge or not hmac.compare_digest(token, settings.verify_token):
            return "forbidden", 403
        return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.post("/webhook/meta")
    def receive_webhook():
        if not settings.enabled:
            return jsonify(error="disabled"), 503
        raw = request.get_data(cache=False, as_text=False)
        if len(raw) > MAX_BODY_BYTES:
            return jsonify(error="payload_too_large"), 413
        if not valid_signature(raw, request.headers.get("X-Hub-Signature-256"), settings.app_secret):
            return jsonify(error="invalid_signature"), 401
        try:
            payload = json.loads(raw)
            events = parse_events(payload)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return jsonify(error="invalid_payload"), 400
        try:
            counts = db.ingest(events, settings)
        except (sqlite3.Error, StorageError):
            return jsonify(error="storage_unavailable"), 503
        logger.info(json.dumps({"event": "notification_batch", **counts}, sort_keys=True))
        return jsonify(accepted=counts["accepted"], duplicate=counts["duplicate"], ignored=counts["ignored"]), 200

    @app.get("/health")
    @app.get("/healthz")
    def health():
        try:
            return jsonify(ingest_enabled=settings.enabled,
                           verify_enabled=settings.verify_enabled, **db.health()), 200
        except (sqlite3.Error, StorageError):
            return jsonify(ingest_enabled=settings.enabled,
                           verify_enabled=settings.verify_enabled, storage="error"), 503

    return app


def run_once(store, settings: Settings, processor: Callable[[dict], dict | None]):
    """Process at most one approved notification; processor receives IDs only."""
    item = store.claim()
    if item is None:
        return "idle"
    if not settings.accepts_lead(item["lead_id"]):
        store.fail(item["lead_id"], attempts=item["attempts"], max_attempts=settings.max_attempts,
                   retry_base=settings.retry_base_seconds, error_code="unknown")
        return "blocked"
    try:
        result = processor({k: item[k] for k in ("lead_id", "page_id", "form_id", "ad_id", "submitted_at")})
    except Exception as exc:
        code = getattr(exc, "safe_code", "unknown")
        store.fail(item["lead_id"], attempts=item["attempts"], max_attempts=settings.max_attempts,
                   retry_base=settings.retry_base_seconds, error_code=code)
        return "dead" if item["attempts"] + 1 >= settings.max_attempts else "retry"
    # A completion failure is not converted into a processing failure. If commit
    # did not occur the lease expires; if it did, the row is already DONE.
    store.complete(item["lead_id"], result)
    return "done"
