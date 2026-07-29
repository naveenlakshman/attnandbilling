"""Transaction-safe, tenant-owned financial document numbering."""

from datetime import datetime

from config import Config


DOCUMENT_TYPES = {"invoice", "receipt", "writeoff"}


def normalize_document_prefix(prefix):
    value = (prefix or "").strip().strip("/")
    if not value:
        raise ValueError("A document prefix is required.")
    return f"{value}/"


def derive_writeoff_prefix(invoice_prefix):
    """Derive a tenant's write-off series from its invoice series.

    MCT/INV becomes MCT/WO. Less conventional invoice prefixes retain their
    complete prefix and receive a WO suffix.
    """
    parts = [part for part in (invoice_prefix or "").strip().strip("/").split("/") if part]
    if not parts:
        return "WO"
    if parts[-1].upper() in {"INV", "INVOICE"}:
        parts[-1] = "WO"
    else:
        parts.append("WO")
    return "/".join(parts)


def allocate_document_number(cursor, institute_id, document_type, prefix):
    """Reserve and return the next number using the caller's transaction.

    A separate series is maintained for every institute, document type, and
    normalized prefix. MySQL locks the sequence row until the surrounding
    invoice/receipt transaction commits, preventing duplicate allocations.
    """
    if document_type not in DOCUMENT_TYPES:
        raise ValueError("Unsupported document type.")

    normalized_prefix = normalize_document_prefix(prefix)
    institute_id = int(institute_id)

    if getattr(Config, "DB_TYPE", "sqlite") == "mysql":
        cursor.execute(
            """
            INSERT INTO institute_document_sequences (
                institute_id, document_type, series_prefix, next_value,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 1, NOW(), NOW())
            ON DUPLICATE KEY UPDATE updated_at = updated_at
            """,
            (institute_id, document_type, normalized_prefix),
        )
        cursor.execute(
            """
            SELECT next_value
            FROM institute_document_sequences
            WHERE institute_id = ?
              AND document_type = ?
              AND series_prefix = ?
            FOR UPDATE
            """,
            (institute_id, document_type, normalized_prefix),
        )
    else:
        cursor.execute(
            """
            INSERT OR IGNORE INTO institute_document_sequences (
                institute_id, document_type, series_prefix, next_value,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            (institute_id, document_type, normalized_prefix),
        )
        cursor.execute(
            """
            SELECT next_value
            FROM institute_document_sequences
            WHERE institute_id = ?
              AND document_type = ?
              AND series_prefix = ?
            """,
            (institute_id, document_type, normalized_prefix),
        )

    row = cursor.fetchone()
    if not row:
        raise RuntimeError("Document number sequence could not be initialized.")

    next_value = int(row["next_value"])
    cursor.execute(
        """
        UPDATE institute_document_sequences
        SET next_value = ?, updated_at = ?
        WHERE institute_id = ?
          AND document_type = ?
          AND series_prefix = ?
          AND next_value = ?
        """,
        (
            next_value + 1,
            datetime.now().isoformat(timespec="seconds"),
            institute_id,
            document_type,
            normalized_prefix,
            next_value,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("Document number sequence allocation conflicted.")

    return f"{normalized_prefix}{next_value:03d}"
