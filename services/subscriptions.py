"""Subscription entitlements and transactional tenant limit enforcement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing", "grace"}
RESOURCE_COLUMNS = {
    "branches": ("branch_limit", "branch_limit_override"),
    "staff": ("staff_limit", "staff_limit_override"),
    "students": ("student_limit", "student_limit_override"),
    "storage": ("storage_limit_bytes", "storage_limit_bytes_override"),
}
RESOURCE_COUNT_SQL = {
    "branches": "SELECT COUNT(*) AS n FROM branches WHERE institute_id = ? AND is_active = 1",
    "staff": (
        "SELECT COUNT(*) AS n FROM users "
        "WHERE institute_id = ? AND platform_role IS NULL AND is_active = 1"
    ),
    "students": "SELECT COUNT(*) AS n FROM students WHERE institute_id = ? AND status = 'active'",
    "storage": (
        "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM tenant_storage_objects "
        "WHERE institute_id = ?"
    ),
}


class SubscriptionError(RuntimeError):
    """Base class for subscription enforcement failures."""


class SubscriptionAccessDenied(SubscriptionError):
    """Raised when an institute is not allowed to use the application."""


class PlanLimitExceeded(SubscriptionError):
    def __init__(self, resource, used, limit, requested=1):
        self.resource = resource
        self.used = int(used or 0)
        self.limit = int(limit)
        self.requested = int(requested)
        super().__init__(
            f"{resource.replace('_', ' ').title()} limit reached "
            f"({self.used}/{self.limit}). Contact the platform owner to change the plan."
        )


@dataclass(frozen=True)
class Entitlement:
    institute_id: int
    subscription_id: int
    plan_code: str
    plan_name: str
    status: str
    grace_ends_at: object
    limits: dict
    features: dict


def _json_object(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def get_entitlement(conn, institute_id, *, for_update=False):
    lock = " FOR UPDATE" if for_update else ""
    row = conn.execute(
        """
        SELECT s.id AS subscription_id, s.institute_id, s.status,
               s.trial_ends_at, s.grace_ends_at,
               s.branch_limit_override, s.staff_limit_override,
               s.student_limit_override, s.storage_limit_bytes_override,
               s.feature_overrides_json,
               p.code AS plan_code, p.name AS plan_name,
               p.branch_limit, p.staff_limit, p.student_limit,
               p.storage_limit_bytes, p.features_json
        FROM institute_subscriptions s
        JOIN subscription_plans p ON p.id = s.plan_id
        WHERE s.institute_id = ?
        LIMIT 1
        """ + lock,
        (int(institute_id),),
    ).fetchone()
    if not row:
        raise SubscriptionAccessDenied("This institute has no subscription assigned.")

    status = row["status"]
    if status == "trialing" and row["trial_ends_at"]:
        trial_value = row["trial_ends_at"]
        if isinstance(trial_value, str):
            trial_value = datetime.fromisoformat(trial_value)
        if trial_value < datetime.now():
            status = "suspended"
    if status == "grace" and row["grace_ends_at"]:
        grace_value = row["grace_ends_at"]
        if isinstance(grace_value, str):
            grace_value = datetime.fromisoformat(grace_value)
        if grace_value < datetime.now():
            status = "suspended"

    limits = {}
    for resource, (plan_column, override_column) in RESOURCE_COLUMNS.items():
        override = row[override_column]
        limits[resource] = override if override is not None else row[plan_column]

    features = _json_object(row["features_json"])
    features.update(_json_object(row["feature_overrides_json"]))
    return Entitlement(
        institute_id=int(row["institute_id"]),
        subscription_id=int(row["subscription_id"]),
        plan_code=row["plan_code"],
        plan_name=row["plan_name"],
        status=status,
        grace_ends_at=row["grace_ends_at"],
        limits=limits,
        features={str(key): bool(value) for key, value in features.items()},
    )


def assert_subscription_access(conn, institute_id):
    entitlement = get_entitlement(conn, institute_id)
    if entitlement.status not in ACTIVE_SUBSCRIPTION_STATUSES:
        raise SubscriptionAccessDenied(
            "This institute is suspended. Contact the platform owner to reactivate access."
        )
    return entitlement


def assert_feature_enabled(conn, institute_id, feature):
    entitlement = assert_subscription_access(conn, institute_id)
    if not entitlement.features.get(feature, False):
        raise SubscriptionAccessDenied(
            f"The {feature.replace('_', ' ')} feature is not included in this institute's plan."
        )
    return entitlement


def lock_and_check_limit(conn, institute_id, resource, requested=1):
    """Serialize writers on the subscription row and verify a resource limit.

    The caller must use this function and perform its INSERT in the same database
    transaction, committing only after the INSERT succeeds.
    """
    if resource not in RESOURCE_COUNT_SQL:
        raise ValueError(f"Unsupported subscription resource: {resource}")
    requested = int(requested)
    if requested < 0:
        raise ValueError("requested must not be negative")
    entitlement = get_entitlement(conn, institute_id, for_update=True)
    if entitlement.status not in ACTIVE_SUBSCRIPTION_STATUSES:
        raise SubscriptionAccessDenied(
            "This institute is suspended. Contact the platform owner to reactivate access."
        )
    limit = entitlement.limits[resource]
    row = conn.execute(RESOURCE_COUNT_SQL[resource], (int(institute_id),)).fetchone()
    used = int(row["n"] or 0)
    if limit is not None and used + requested > int(limit):
        raise PlanLimitExceeded(resource, used, int(limit), requested)
    return used, limit


def usage_summary(conn, institute_id):
    entitlement = get_entitlement(conn, institute_id)
    usage = {}
    for resource, sql in RESOURCE_COUNT_SQL.items():
        usage[resource] = int(
            conn.execute(sql, (int(institute_id),)).fetchone()["n"] or 0
        )
    return entitlement, usage
