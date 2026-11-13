"""Cloud Run Job entry point for the isolated synthetic-only staging worker."""
from __future__ import annotations

import argparse
import json
import logging
import os

from .mysql_store import ERPMapping, mysql_store_from_env
from .processor import MetaLeadRetriever, MetaSyntheticProcessor
from .receiver import run_once, settings_from_env


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("meta_staging_worker")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-items", type=int, default=100)
    parser.add_argument("--replay-dead")
    parser.add_argument("--prune", action="store_true")
    args = parser.parse_args(argv)
    if args.max_items < 1 or args.max_items > 1000:
        raise SystemExit("--max-items must be between 1 and 1000")
    settings = settings_from_env()
    if not settings.enabled:
        logger.info(json.dumps({"event": "worker_disabled"}))
        return 0
    if settings.storage_backend != "mysql":
        raise SystemExit("Packaged staging worker requires MySQL storage.")
    store = mysql_store_from_env()
    with store.worker_lock() as acquired:
        if not acquired:
            logger.info(json.dumps({"event": "worker_overlap_skipped"}))
            return 0
        if args.prune:
            deleted = store.prune(settings.retention_days)
            logger.info(json.dumps({"event": "retention_prune", **deleted}, sort_keys=True))
            return 0
        if args.replay_dead:
            try:
                reviewed = json.loads(os.environ.get("META_CONTROLLED_REPLAY_LEAD_IDS", "[]"))
            except json.JSONDecodeError as exc:
                raise SystemExit("META_CONTROLLED_REPLAY_LEAD_IDS must be JSON.") from exc
            allowlist = settings.synthetic_lead_ids | frozenset(reviewed)
            replayed = store.replay_dead(args.replay_dead, allowlist)
            logger.info(json.dumps({"event": "controlled_replay", "replayed": bool(replayed)}))
            return 0 if replayed else 2
        token = os.environ.get("META_STAGING_SYSTEM_USER_TOKEN", "")
        version = os.environ.get("META_GRAPH_VERSION", "")
        processor = (MetaSyntheticProcessor(settings, token, version)
                     if settings.processing_mode == "synthetic"
                     else MetaLeadRetriever(settings, token, version))
        mapping = ERPMapping.from_env() if settings.processing_mode == "production" else None
        counts = {"done": 0, "retry": 0, "dead": 0, "blocked": 0, "idle": 0}
        for _ in range(args.max_items):
            outcome = (_run_production_once(store, settings, processor, mapping)
                       if mapping else run_once(store, settings, processor))
            counts[outcome] += 1
            if outcome == "idle":
                break
        logger.info(json.dumps({"event": "worker_run", **counts}, sort_keys=True))
        return 1 if counts["dead"] or counts["blocked"] else 0


def _run_production_once(store, settings, retriever, mapping):
    item = store.claim()
    if item is None:
        return "idle"
    if not settings.accepts_lead(item["lead_id"]):
        store.fail(item["lead_id"], attempts=item["attempts"], max_attempts=settings.max_attempts,
                   retry_base=settings.retry_base_seconds, error_code="unknown")
        return "blocked"
    try:
        lead = retriever.retrieve(item, require_synthetic=False)
    except Exception as exc:
        code = getattr(exc, "safe_code", "unknown")
        store.fail(item["lead_id"], attempts=item["attempts"], max_attempts=settings.max_attempts,
                   retry_base=settings.retry_base_seconds, error_code=code)
        return "dead" if item["attempts"] + 1 >= settings.max_attempts else "retry"
    # ERP insert and inbox completion commit atomically on the same Cloud SQL instance.
    # A database error is allowed to fail the job and the lease will be recovered.
    store.complete_production(item, lead.as_production_result(), mapping)
    return "done"


if __name__ == "__main__":
    raise SystemExit(main())
