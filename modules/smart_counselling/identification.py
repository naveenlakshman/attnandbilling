from modules.leads.helpers import can_access_lead

from .phone import mask_mobile, try_normalize_indian_mobile


def _matching_leads(conn, institute_id, mobile):
    rows = conn.execute(
        """
        SELECT l.id, l.name, l.phone, l.whatsapp, l.stage, l.status, l.is_deleted,
               l.assigned_to_id, l.branch_id, l.created_at,
               u.full_name AS assigned_to_name, b.branch_name,
               s.id AS student_id, s.student_code
        FROM leads l
        LEFT JOIN users u ON u.id = l.assigned_to_id AND u.institute_id = l.institute_id
        LEFT JOIN branches b ON b.id = l.branch_id AND b.institute_id = l.institute_id
        LEFT JOIN students s ON s.lead_id = l.id AND s.institute_id = l.institute_id
        WHERE l.institute_id = ?
        ORDER BY l.id ASC
        """,
        (int(institute_id),),
    ).fetchall()
    matches = {}
    for row in rows:
        # Primary phone is the CRM identity key. WhatsApp is deliberately only
        # supporting contact data because it may be shared by families or teams.
        if mobile == try_normalize_indian_mobile(row["phone"]):
            matches.setdefault(int(row["id"]), dict(row))
    return list(matches.values())


def _lead_summary(row, *, include_assignment=False):
    summary = {
        "id": int(row["id"]),
        "name": row.get("name") or "Prospect",
        "mobileMasked": mask_mobile(try_normalize_indian_mobile(row.get("phone"))),
        "stage": row.get("stage"),
    }
    if include_assignment:
        summary.update({
            "branch": row.get("branch_name"),
            "assignedCounsellor": row.get("assigned_to_name"),
            "createdAt": row.get("created_at"),
        })
    return summary


def identify_verified_mobile(conn, actor, mobile):
    matches = _matching_leads(conn, actor.institute_id, mobile)
    active = [row for row in matches if not bool(row.get("is_deleted"))]
    deleted = [row for row in matches if bool(row.get("is_deleted"))]

    if not active and deleted:
        return {"status": "SOFT_DELETED_MATCH", "lead": None, "matches": [], "linkLeadId": None}
    if not active:
        return {"status": "NEW", "lead": None, "matches": [], "linkLeadId": None}
    if len(active) > 1:
        visible = [
            _lead_summary(row, include_assignment=True)
            for row in active
            if can_access_lead(actor.id, actor.role, row.get("assigned_to_id"))
        ]
        return {"status": "MULTIPLE_MATCHES", "lead": None, "matches": visible, "linkLeadId": None}

    lead = active[0]
    if not can_access_lead(actor.id, actor.role, lead.get("assigned_to_id")):
        return {"status": "EXISTING_LEAD_RESTRICTED", "lead": None, "matches": [], "linkLeadId": None}
    if lead.get("student_id") or str(lead.get("status") or "").lower() == "converted":
        summary = _lead_summary(lead)
        summary["studentCode"] = lead.get("student_code")
        return {"status": "EXISTING_STUDENT", "lead": summary, "matches": [], "linkLeadId": int(lead["id"])}
    return {
        "status": "EXISTING_LEAD",
        "lead": _lead_summary(lead),
        "matches": [],
        "linkLeadId": int(lead["id"]),
    }


def inspect_unverified_mobile(conn, actor, mobile):
    result = identify_verified_mobile(conn, actor, mobile)
    return {
        "status": "UNVERIFIED_MATCH_REQUIRES_CONFIRMATION" if result["status"] != "NEW" else "UNVERIFIED_NEW",
        "lead": None,
        "matches": [],
        "linkLeadId": None,
    }
