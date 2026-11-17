"""Tenant-scoped data helpers for the invoice creation form."""


def load_booking_branches(conn, institute_id):
    rows = conn.execute(
        """
        SELECT id, branch_name
        FROM branches
        WHERE institute_id = ? AND is_active = 1
        ORDER BY branch_name
        """,
        (institute_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def require_booking_branch(conn, institute_id, raw_branch_id):
    try:
        branch_id = int(raw_branch_id)
    except (TypeError, ValueError):
        raise ValueError("Choose an invoice booking branch.") from None

    row = conn.execute(
        """
        SELECT id
        FROM branches
        WHERE id = ? AND institute_id = ? AND is_active = 1
        """,
        (branch_id, institute_id),
    ).fetchone()
    if not row:
        raise ValueError("Choose an active invoice booking branch for this institute.")
    return branch_id
