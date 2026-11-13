"""Cloud Run Job entry point for the isolated synthetic-only staging worker."""
from __future__ import annotations

import argparse
import json
import logging
import os

from .mysql_store import mysql_store_from_env
from .processor import MetaSyntheticProcessor
from .receiver import run_once, settings_from_env


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(message)s")
logger = logging.getLogger("meta_staging_worker")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-items", type=int, default=100)
    parser.add_argument("--replay-dead")
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
    if args.replay_dead:
        replayed = store.replay_dead(args.replay_dead, settings.synthetic_lead_ids)
        logger.info(json.dumps({"event": "controlled_replay", "replayed": bool(replayed)}))
        return 0 if replayed else 2
    processor = MetaSyntheticProcessor(settings,
        os.environ.get("META_STAGING_SYSTEM_USER_TOKEN", ""),
        os.environ.get("META_GRAPH_VERSION", ""))
    counts = {"done": 0, "retry": 0, "dead": 0, "blocked": 0, "idle": 0}
    for _ in range(args.max_items):
        outcome = run_once(store, settings, processor)
        counts[outcome] += 1
        if outcome == "idle":
            break
    logger.info(json.dumps({"event": "worker_run", **counts}, sort_keys=True))
    return 1 if counts["dead"] or counts["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
