import argparse
import json
import os
import sys
from datetime import date


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from modules.billing.auto_reminders import send_automatic_fee_reminders  # noqa: E402


def _parse_date(value):
    if not value:
        return None
    return date.fromisoformat(value)


def main():
    parser = argparse.ArgumentParser(
        description="Send automatic fee reminder SMS messages."
    )
    parser.add_argument(
        "--date",
        help="Run for a specific date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which reminders would be sent without sending SMS.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum eligible reminders to process. Useful for testing.",
    )
    args = parser.parse_args()

    summary = send_automatic_fee_reminders(
        run_date=_parse_date(args.date),
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
