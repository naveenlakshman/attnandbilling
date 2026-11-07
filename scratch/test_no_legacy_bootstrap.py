"""Regression check: startup must not contain legacy credentials/branch seeds."""

from __future__ import annotations

import inspect

import db


source = inspect.getsource(db.init_db)

for forbidden_value in (
    "admin123",
    "Global IT Education Head Office",
    "Global IT Education – Hoskote Branch",
    '("HO",)',
    '("HB",)',
):
    assert forbidden_value not in source, (
        f"init_db contains forbidden legacy bootstrap value: {forbidden_value}"
    )

assert "INSERT INTO users" not in source[source.index("# ---------- BACKFILL OLD DATA ----------"):source.index("INSERT OR IGNORE INTO institutes")]
assert "INSERT INTO branches" not in source[source.index("# ---------- BACKFILL OLD DATA ----------"):source.index("INSERT OR IGNORE INTO institutes")]

print("legacy_bootstrap_disabled=OK")
