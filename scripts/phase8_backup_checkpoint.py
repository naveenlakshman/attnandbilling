"""Create a named SQLite backup checkpoint for Phase 8 operations.

Usage:
  python scripts/phase8_backup_checkpoint.py
  python scripts/phase8_backup_checkpoint.py --label phase8_cp1_pre_archive
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

# Allow standalone execution: python scripts/phase8_backup_checkpoint.py
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import DB_PATH


def create_backup(label: str) -> str:
    backup_dir = os.path.join(os.path.dirname(DB_PATH), "backup")
    os.makedirs(backup_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"{label}_{stamp}.db")

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Phase 8 backup checkpoint")
    parser.add_argument(
        "--label",
        default="phase8_checkpoint",
        help="checkpoint label prefix",
    )
    args = parser.parse_args()

    backup_path = create_backup(args.label)
    size_bytes = os.path.getsize(backup_path)
    print(f"phase8_backup_ok=True")
    print(f"backup_path={backup_path}")
    print(f"backup_size_bytes={size_bytes}")


if __name__ == "__main__":
    main()
