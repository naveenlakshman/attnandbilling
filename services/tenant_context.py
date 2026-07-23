"""Request-local institute resolution for the additive multi-institute foundation."""

from __future__ import annotations

import contextvars
import ipaddress
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from flask import abort, current_app, g, request, session

from db import get_conn


logger = logging.getLogger("app.tenant")
_active_tenant = contextvars.ContextVar("active_tenant", default=None)
_cache_lock = threading.RLock()
_domain_cache = {}
_CACHE_TTL_SECONDS = 300
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


@dataclass(frozen=True)
class TenantContext:
    institute_id: int
    name: str
    short_name: str
    slug: str
    status: str
    timezone: str
    locale: str
    currency_code: str
    hostname: str
    resolution_source: str

    def to_dict(self):
        return asdict(self)


def normalize_hostname(raw_host):
    """Return a lower-case ASCII hostname without a port, or an empty string."""
    value = (raw_host or "").strip().lower().rstrip(".")
    if not value:
        return ""
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    elif value.count(":") == 1:
        value = value.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    return value if _HOST_RE.fullmatch(value) else ""


def clear_tenant_cache(hostname=None):
    with _cache_lock:
        if hostname:
            normalized = normalize_hostname(hostname)
            for key in [key for key in _domain_cache if key[0] == normalized]:
                _domain_cache.pop(key, None)
        else:
            _domain_cache.clear()


def tenant_cache_key(namespace, *parts, institute_id=None):
    resolved_id = institute_id if institute_id is not None else get_current_institute_id()
    if resolved_id is None:
        raise RuntimeError("Tenant context is required to build a tenant cache key")
    clean_parts = [str(part).replace(":", "_") for part in parts]
    suffix = ":".join(clean_parts)
    return f"tenant:{int(resolved_id)}:{namespace}" + (f":{suffix}" if suffix else "")


def _row_to_context(row, hostname, source):
    if not row:
        return None
    return TenantContext(
        institute_id=int(row["id"]),
        name=row["name"],
        short_name=row["short_name"],
        slug=row["slug"],
        status=row["status"],
        timezone=row["timezone"],
        locale=row["locale"],
        currency_code=row["currency_code"],
        hostname=hostname,
        resolution_source=source,
    )


def _fetch_domain_tenant(hostname):
    conn = get_conn()
    try:
        return conn.execute(
            """
            SELECT i.id, i.name, i.short_name, i.slug, i.status,
                   i.timezone, i.locale, i.currency_code
            FROM institute_domains d
            JOIN institutes i ON i.id = d.institute_id
            WHERE d.hostname = ? AND d.status = 'active'
            LIMIT 1
            """,
            (hostname,),
        ).fetchone()
    finally:
        conn.close()


def _fetch_default_tenant():
    conn = get_conn()
    try:
        return conn.execute(
            """
            SELECT id, name, short_name, slug, status, timezone, locale, currency_code
            FROM institutes WHERE id = 1 LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()


def resolve_tenant(raw_host, allow_compatibility_fallback=False):
    hostname = normalize_hostname(raw_host)
    if not hostname:
        return None
    cache_key = (hostname, bool(allow_compatibility_fallback))
    now = time.monotonic()
    with _cache_lock:
        cached = _domain_cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    row = _fetch_domain_tenant(hostname)
    source = "verified_domain"
    if not row and hostname in {"localhost", "127.0.0.1", "::1"}:
        row = _fetch_default_tenant()
        source = "development_fallback"
    elif not row and allow_compatibility_fallback:
        row = _fetch_default_tenant()
        source = "compatibility_fallback"

    context = _row_to_context(row, hostname, source)
    with _cache_lock:
        _domain_cache[cache_key] = (now, context)
    return context


def get_current_tenant():
    return _active_tenant.get()


def get_current_institute_id(default=None):
    tenant = get_current_tenant()
    return tenant.institute_id if tenant else default


def require_tenant():
    tenant = get_current_tenant()
    if tenant is None:
        raise RuntimeError("A verified tenant context is required")
    return tenant


def _record_security_event(event_type, tenant=None, details=None):
    """Best-effort security audit; never replace the request's deny decision."""
    conn = None
    try:
        conn = get_conn()
        conn.execute(
            """
            INSERT INTO tenant_security_audit (
                institute_id, user_id, student_id, event_type, request_host,
                request_path, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant.institute_id if tenant else None,
                session.get("user_id"),
                session.get("student_id"),
                event_type,
                normalize_hostname(request.host),
                request.path[:1000],
                json.dumps(details or {}, sort_keys=True),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to record tenant security event %s", event_type)
    finally:
        if conn is not None:
            conn.close()


def _bind_request_tenant():
    mode = current_app.config.get("TENANT_RESOLUTION_MODE", "observe")
    if mode == "off":
        return None

    tenant = resolve_tenant(
        request.host,
        allow_compatibility_fallback=(mode == "observe"),
    )
    if tenant is None:
        if request.endpoint in current_app.config.get("TENANT_STRICT_EXEMPT_ENDPOINTS", {"healthz", "static"}):
            return None
        if mode == "strict":
            _record_security_event("unknown_tenant_host_denied")
            abort(404)
        logger.warning("Tenant could not be resolved for host %s", normalize_hostname(request.host))
        return None

    token = _active_tenant.set(tenant)
    g.tenant = tenant
    g.tenant_context_token = token

    session_tenant = session.get("institute_id")
    authenticated = session.get("user_id") is not None or session.get("student_id") is not None
    if authenticated and session_tenant is None:
        session["institute_id"] = tenant.institute_id
    elif authenticated and int(session_tenant or 0) != tenant.institute_id:
        logger.warning(
            "Tenant/session mismatch host=%s resolved=%s session=%s",
            tenant.hostname,
            tenant.institute_id,
            session_tenant,
        )
        if mode == "strict":
            _record_security_event(
                "tenant_session_mismatch_denied",
                tenant,
                {"resolved_institute_id": tenant.institute_id, "session_institute_id": session_tenant},
            )
            abort(403)
        _record_security_event(
            "tenant_session_mismatch_observed",
            tenant,
            {"resolved_institute_id": tenant.institute_id, "session_institute_id": session_tenant},
        )
    return None


def _clear_request_tenant(_exception=None):
    token = getattr(g, "tenant_context_token", None)
    if token is not None:
        try:
            _active_tenant.reset(token)
        except (LookupError, RuntimeError, ValueError):
            _active_tenant.set(None)


def init_tenant_context(app):
    mode = app.config.get("TENANT_RESOLUTION_MODE", "observe")
    if mode not in {"off", "observe", "strict"}:
        raise RuntimeError("TENANT_RESOLUTION_MODE must be off, observe, or strict")
    app.before_request(_bind_request_tenant)
    app.teardown_request(_clear_request_tenant)
