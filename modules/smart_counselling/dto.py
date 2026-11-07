from .phone import mask_mobile


def session_dto(row):
    prospect = None
    if row.get("lead_id"):
        prospect = {"id": int(row["lead_id"]), "name": row.get("lead_name") or "Prospect"}

    return {
        "id": int(row["id"]),
        "status": row["status"],
        "branch": {"id": int(row["branch_id"]), "name": row.get("branch_name") or "Branch"},
        "counsellor": {
            "id": int(row["counsellor_user_id"]),
            "name": row.get("counsellor_name") or "Counsellor",
        },
        "prospect": prospect,
        "mobileVerified": bool(row["mobile_verified"]),
        "verificationMethod": row.get("verification_method"),
        "mobileMasked": mask_mobile(row.get("verified_mobile_normalized")) if row.get("verified_mobile_normalized") else None,
        "identityMobileMasked": mask_mobile(row.get("identity_mobile_normalized")) if row.get("identity_mobile_normalized") else None,
        "identificationStatus": row.get("identification_status"),
        "startedAt": row["started_at"],
        "completedAt": row.get("completed_at"),
        "abandonedAt": row.get("abandoned_at"),
        "updatedAt": row["updated_at"],
        "canResume": row["status"] not in {"COMPLETED", "ABANDONED"},
    }


def dashboard_session_dto(row):
    data = session_dto(row)
    return {
        "id": data["id"],
        "status": data["status"],
        "branch": data["branch"],
        "counsellor": data["counsellor"],
        "prospect": data["prospect"],
        "startedAt": data["startedAt"],
        "updatedAt": data["updatedAt"],
        "canResume": data["canResume"],
    }
