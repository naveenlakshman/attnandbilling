"""Regression checks for tenant-owned invoice and receipt series."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from services.document_numbers import allocate_document_number, derive_writeoff_prefix


SCHEMA = """
CREATE TABLE institute_document_sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institute_id INTEGER NOT NULL,
    document_type TEXT NOT NULL,
    series_prefix TEXT NOT NULL,
    next_value INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE (institute_id, document_type, series_prefix)
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def run():
    original_db_type = Config.DB_TYPE
    Config.DB_TYPE = "sqlite"
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = connect(path)
        conn.executescript(SCHEMA)
        cur = conn.cursor()

        assert derive_writeoff_prefix("MCT/INV") == "MCT/WO"
        assert derive_writeoff_prefix("HCT/INVOICE/") == "HCT/WO"
        assert derive_writeoff_prefix("GIT/B") == "GIT/B/WO"

        assert allocate_document_number(cur, 1, "invoice", "MCT/INV") == "MCT/INV/001"
        assert allocate_document_number(cur, 1, "invoice", "MCT/INV/") == "MCT/INV/002"
        assert allocate_document_number(cur, 1, "receipt", "MCT/RCP") == "MCT/RCP/001"
        assert allocate_document_number(cur, 7, "invoice", "HCT/INV") == "HCT/INV/001"
        assert allocate_document_number(cur, 7, "receipt", "HCT/RCP") == "HCT/RCP/001"
        assert allocate_document_number(cur, 1, "writeoff", "MCT/WO") == "MCT/WO/001"
        assert allocate_document_number(cur, 7, "writeoff", "HCT/WO") == "HCT/WO/001"

        # A changed prefix starts a distinct series without affecting the old one.
        assert allocate_document_number(cur, 1, "invoice", "NEW/INV") == "NEW/INV/001"
        assert allocate_document_number(cur, 1, "invoice", "MCT/INV") == "MCT/INV/003"
        conn.rollback()
        conn.close()
        print("Tenant document sequence checks passed.")
    finally:
        Config.DB_TYPE = original_db_type
        os.remove(path)


if __name__ == "__main__":
    run()
