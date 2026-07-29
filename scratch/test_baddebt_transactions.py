"""Regression checks for database-specific bad-debt transactions."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from modules.baddebt.routes import _begin_write_transaction, _for_update_clause


class RecordingCursor:
    def __init__(self):
        self.statements = []

    def execute(self, statement, args=None):
        self.statements.append((statement, args))


def run():
    original_db_type = Config.DB_TYPE
    try:
        mysql_cursor = RecordingCursor()
        Config.DB_TYPE = "mysql"
        _begin_write_transaction(mysql_cursor)
        assert mysql_cursor.statements == [("START TRANSACTION", None)]
        assert _for_update_clause() == " FOR UPDATE"

        sqlite_cursor = RecordingCursor()
        Config.DB_TYPE = "sqlite"
        _begin_write_transaction(sqlite_cursor)
        assert sqlite_cursor.statements == [("BEGIN IMMEDIATE", None)]
        assert _for_update_clause() == ""
    finally:
        Config.DB_TYPE = original_db_type

    print("Bad-debt transaction dialect checks passed.")


if __name__ == "__main__":
    run()
