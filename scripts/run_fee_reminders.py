"""Cloud Run Job entry point for automatic fee reminders."""

import argparse
import json
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.billing.auto_reminders import send_automatic_fee_reminders


def _arguments():
    parser = argparse.ArgumentParser(description="Process automatic fee reminders.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate and report reminders without sending SMS messages.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--run-date", type=date.fromisoformat, default=None)
    return parser.parse_args()


def main():
    args = _arguments()
    run_date = args.run_date or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    summary = send_automatic_fee_reminders(
        run_date=run_date,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(summary, default=str, sort_keys=True))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
