from typing import Optional, Tuple


def can_access_lead(user_id: int, role: str, lead_assigned_to_id: Optional[int]) -> bool:
    """Return whether the current user can access a lead by assignment policy."""
    if role == "admin":
        return True

    # For staff, unassigned leads are restricted by default.
    if lead_assigned_to_id is None:
        return False

    return int(user_id or 0) == int(lead_assigned_to_id)


def get_lead_or_404_with_access(conn, lead_id: int, session_obj, include_deleted: bool = False) -> Tuple[Optional[object], Optional[str]]:
    """
    Fetch a lead by ID and verify assignment-based access.

    Returns:
        (lead_row, None) when accessible
        (None, "not_found") when lead doesn't exist for requested deleted scope
        (None, "forbidden") when user lacks permission
    """
    from services.tenant_context import get_current_institute_id

    current_institute_id = get_current_institute_id(default=1)
    cur = conn.cursor()

    if include_deleted:
        cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
    else:
        cur.execute("SELECT * FROM leads WHERE id = ? AND is_deleted = 0", (lead_id,))

    lead = cur.fetchone()
    if not lead:
        return None, "not_found"

    lead_inst = lead["institute_id"] if "institute_id" in lead.keys() else 1
    if int(lead_inst or 1) != int(current_institute_id):
        return None, "not_found"

    if not can_access_lead(
        user_id=session_obj.get("user_id"),
        role=session_obj.get("role"),
        lead_assigned_to_id=lead["assigned_to_id"],
    ):
        return None, "forbidden"

    # Normalize sqlite3.Row to plain dict so callers can safely use both
    # lead["field"] and lead.get("field") access styles.
    return dict(lead), None
