import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from db import get_company_profile, get_conn

from .authorization import authorize_session
from .errors import SmartCounsellingError, validation_error
from .identification import identify_verified_mobile, inspect_unverified_mobile
from .otp_repository import (
    count_recent_challenges,
    get_challenge,
    get_latest_challenge,
    insert_challenge,
    invalidate_pending,
)
from .phone import mask_mobile, normalize_indian_mobile
from .repository import get_session, insert_event
from .sms_transport import SmsDeliveryError, get_sms_transport
from .state_machine import IDENTIFICATION_PENDING, IDENTIFIED, require_transition


OTP_OVERRIDE_REASONS = {
    "SMS_NOT_RECEIVED", "NETWORK_ISSUE", "PROSPECT_DECLINED", "NO_PHONE_ACCESS", "OTHER",
}


def get_otp_status(actor, session_id):
    conn = get_conn()
    now = _utcnow()
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        challenge = get_latest_challenge(conn, actor.institute_id, session_id)
        active = None
        if challenge and challenge["status"] == "PENDING" and challenge["delivery_status"] == "SENT":
            expires = max(0, int((_parse(challenge["expires_at"]) - now).total_seconds()))
            if expires > 0:
                active = {
                    "challengeId": int(challenge["id"]),
                    "mobileMasked": mask_mobile(challenge["mobile_normalized"]),
                    "expiresInSeconds": expires,
                    "resendAvailableInSeconds": max(
                        0, int((_parse(challenge["resend_available_at"]) - now).total_seconds())
                    ),
                }
        return {"sessionStatus": row["status"], "activeChallenge": active}
    finally:
        conn.close()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse(value):
    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")


def _hash_otp(challenge_id, otp):
    secret = current_app.config["SMART_COUNSELLING_OTP_SECRET"].encode("utf-8")
    return hmac.new(secret, f"smart-counselling:{challenge_id}:{otp}".encode(), hashlib.sha256).hexdigest()


def _ensure_identification_pending(row):
    if row["status"] != IDENTIFICATION_PENDING:
        raise SmartCounsellingError(
            "invalid_transition",
            "Mobile identification is not available in this session state.",
            409,
        )


def _rate_limit(conn, actor, session_id, mobile, now):
    since = _stamp(now - timedelta(hours=1))
    policies = (
        ("mobile_normalized", mobile, "SMART_COUNSELLING_OTP_MOBILE_HOURLY_LIMIT"),
        ("created_by_user_id", actor.id, "SMART_COUNSELLING_OTP_USER_HOURLY_LIMIT"),
        ("counselling_session_id", session_id, "SMART_COUNSELLING_OTP_SESSION_HOURLY_LIMIT"),
    )
    for column, value, config_key in policies:
        if count_recent_challenges(conn, column, value, actor.institute_id, since) >= int(current_app.config[config_key]):
            raise SmartCounsellingError(
                "rate_limited",
                "Too many verification messages have been requested. Please try again later.",
                429,
            )


def send_otp(actor, session_id, mobile_input):
    mobile = normalize_indian_mobile(mobile_input)
    conn = get_conn()
    now = _utcnow()
    ttl = int(current_app.config["SMART_COUNSELLING_OTP_TTL_SECONDS"])
    cooldown = int(current_app.config["SMART_COUNSELLING_OTP_RESEND_COOLDOWN_SECONDS"])
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        _ensure_identification_pending(row)
        _rate_limit(conn, actor, session_id, mobile, now)
        latest = get_latest_challenge(conn, actor.institute_id, session_id)
        if latest and latest["status"] == "PENDING" and latest["delivery_status"] == "SENT":
            remaining = int((_parse(latest["resend_available_at"]) - now).total_seconds())
            if remaining > 0:
                raise SmartCounsellingError(
                    "resend_cooldown",
                    f"Wait {remaining} seconds before requesting another OTP.",
                    429,
                    {"resendAvailableInSeconds": remaining},
                )

        invalidate_pending(conn, actor.institute_id, session_id, _stamp(now))
        otp = f"{secrets.randbelow(1_000_000):06d}"
        challenge_id = insert_challenge(
            conn,
            institute_id=actor.institute_id,
            session_id=session_id,
            mobile=mobile,
            otp_hash="0" * 64,
            max_attempts=int(current_app.config["SMART_COUNSELLING_OTP_MAX_ATTEMPTS"]),
            send_sequence=(int(latest["send_sequence"]) + 1) if latest else 1,
            expires_at=_stamp(now + timedelta(seconds=ttl)),
            resend_available_at=_stamp(now + timedelta(seconds=cooldown)),
            actor_user_id=actor.id,
            now=_stamp(now),
        )
        conn.execute(
            "UPDATE counselling_otp_challenges SET otp_hash = ? WHERE id = ?",
            (_hash_otp(challenge_id, otp), challenge_id),
        )
        insert_event(
            conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
            actor_user_id=actor.id, event_type="mobile_submitted",
            metadata={"mobileMasked": mask_mobile(mobile)}, now=_stamp(now),
        )
        company = get_company_profile(actor.institute_id)
        brand = company.get("company_name") or "Global IT Education"
        message = (
            f"Your {brand} counselling verification OTP is {otp}. "
            f"Valid for {max(1, ttl // 60)} minutes. Do not share it except with the authorised counsellor assisting you."
        )
        try:
            receipt = get_sms_transport().send(mobile, message)
        except SmsDeliveryError:
            failed_at = _stamp(_utcnow())
            conn.execute(
                """
                UPDATE counselling_otp_challenges
                SET status = 'INVALIDATED', delivery_status = 'FAILED', invalidated_at = ?, updated_at = ?
                WHERE id = ? AND institute_id = ?
                """,
                (failed_at, failed_at, challenge_id, actor.institute_id),
            )
            insert_event(
                conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
                actor_user_id=actor.id, event_type="otp_delivery_failed", metadata={}, now=failed_at,
            )
            conn.commit()
            raise
        conn.execute(
            """
            UPDATE counselling_otp_challenges
            SET delivery_status = 'SENT', provider_message_id = ?, updated_at = ?
            WHERE id = ? AND institute_id = ?
            """,
            (receipt.message_id, _stamp(_utcnow()), challenge_id, actor.institute_id),
        )
        insert_event(
            conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
            actor_user_id=actor.id,
            event_type="otp_resent" if latest else "otp_sent",
            metadata={"challengeId": challenge_id}, now=_stamp(now),
        )
        conn.commit()
        return {
            "challengeId": challenge_id,
            "mobileMasked": mask_mobile(mobile),
            "expiresInSeconds": ttl,
            "resendAvailableInSeconds": cooldown,
        }
    except SmartCounsellingError:
        conn.rollback()
        raise
    except SmsDeliveryError as exc:
        raise SmartCounsellingError("sms_delivery_failed", str(exc), 503) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _identification_dto(result, verified, method, mobile):
    return {
        "verification": {"verified": verified, "method": method, "mobileMasked": mask_mobile(mobile)},
        "prospect": {
            "status": result["status"],
            "lead": result.get("lead"),
            "matches": result.get("matches", []),
        },
        "nextStep": "PROFILE" if result["status"] in {"NEW", "EXISTING_LEAD", "UNVERIFIED_NEW"} else "RESOLUTION",
    }


def verify_otp(actor, session_id, challenge_id, otp_input):
    otp = str(otp_input or "").strip()
    if len(otp) != 6 or not otp.isdigit():
        raise validation_error("Enter the six-digit OTP.", {"otp": "Six digits are required."})
    conn = get_conn()
    now = _utcnow()
    stamp = _stamp(now)
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        _ensure_identification_pending(row)
        challenge = get_challenge(conn, actor.institute_id, session_id, challenge_id)
        if not challenge:
            raise SmartCounsellingError("challenge_not_found", "The OTP challenge was not found.", 404)
        if challenge["status"] != "PENDING" or challenge["delivery_status"] != "SENT":
            code = "otp_locked" if challenge["status"] == "LOCKED" else "otp_not_active"
            raise SmartCounsellingError(code, "This OTP is no longer active. Request a new OTP.", 409)
        if _parse(challenge["expires_at"]) <= now:
            conn.execute(
                "UPDATE counselling_otp_challenges SET status = 'EXPIRED', updated_at = ? WHERE id = ? AND status = 'PENDING'",
                (stamp, challenge_id),
            )
            insert_event(
                conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
                actor_user_id=actor.id, event_type="otp_expired", metadata={"challengeId": challenge_id}, now=stamp,
            )
            conn.commit()
            raise SmartCounsellingError("otp_expired", "This OTP has expired. Request a new OTP.", 409)
        if not hmac.compare_digest(challenge["otp_hash"], _hash_otp(challenge_id, otp)):
            conn.execute(
                """
                UPDATE counselling_otp_challenges
                SET attempt_count = attempt_count + 1,
                    status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'LOCKED' ELSE status END,
                    updated_at = ?
                WHERE id = ? AND institute_id = ? AND status = 'PENDING'
                """,
                (stamp, challenge_id, actor.institute_id),
            )
            failed = get_challenge(conn, actor.institute_id, session_id, challenge_id)
            locked = failed["status"] == "LOCKED"
            insert_event(
                conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
                actor_user_id=actor.id, event_type="otp_locked" if locked else "otp_failed",
                metadata={"challengeId": challenge_id, "attemptCount": int(failed["attempt_count"])}, now=stamp,
            )
            conn.commit()
            raise SmartCounsellingError(
                "otp_locked" if locked else "otp_invalid",
                "Too many incorrect attempts. Request a new OTP." if locked else "The OTP is incorrect.",
                409 if locked else 400,
            )

        updated = conn.execute(
            """
            UPDATE counselling_otp_challenges
            SET status = 'VERIFIED', verified_at = ?, updated_at = ?
            WHERE id = ? AND institute_id = ? AND status = 'PENDING'
            """,
            (stamp, stamp, challenge_id, actor.institute_id),
        )
        if updated.rowcount != 1:
            raise SmartCounsellingError("otp_not_active", "This OTP is no longer active.", 409)
        mobile = challenge["mobile_normalized"]
        result = identify_verified_mobile(conn, actor, mobile)
        link_id = result.get("linkLeadId")
        identified = result["status"] in {"NEW", "EXISTING_LEAD", "EXISTING_STUDENT"}
        if identified:
            require_transition(row["status"], IDENTIFIED)
        conn.execute(
            """
            UPDATE counselling_sessions
            SET mobile_verified = 1, verification_method = 'OTP', verified_mobile_normalized = ?,
                identity_mobile_normalized = ?, identification_status = ?,
                lead_id = CASE WHEN ? IS NOT NULL THEN ? ELSE lead_id END,
                status = CASE WHEN ? = 1 THEN 'IDENTIFIED' ELSE status END, updated_at = ?
            WHERE id = ? AND institute_id = ?
            """,
            (mobile, mobile, result["status"], link_id, link_id, 1 if identified else 0, stamp, session_id, actor.institute_id),
        )
        insert_event(
            conn, institute_id=actor.institute_id, session_id=session_id, lead_id=link_id,
            actor_user_id=actor.id, event_type="otp_verified", metadata={"challengeId": challenge_id}, now=stamp,
        )
        event_by_status = {
            "NEW": "new_prospect_identified",
            "EXISTING_LEAD": "existing_lead_identified",
            "EXISTING_LEAD_RESTRICTED": "lead_access_restricted",
            "MULTIPLE_MATCHES": "multiple_lead_matches",
            "EXISTING_STUDENT": "existing_student_identified",
            "SOFT_DELETED_MATCH": "soft_deleted_lead_match",
        }
        insert_event(
            conn, institute_id=actor.institute_id, session_id=session_id, lead_id=link_id,
            actor_user_id=actor.id, event_type=event_by_status[result["status"]], metadata={}, now=stamp,
        )
        if link_id:
            insert_event(
                conn, institute_id=actor.institute_id, session_id=session_id, lead_id=link_id,
                actor_user_id=actor.id, event_type="lead_linked", metadata={}, now=stamp,
            )
        conn.commit()
        return _identification_dto(result, True, "OTP", mobile)
    except SmartCounsellingError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def change_mobile(actor, session_id):
    conn = get_conn()
    now = _stamp(_utcnow())
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        _ensure_identification_pending(row)
        invalidate_pending(conn, actor.institute_id, session_id, now)
        conn.execute(
            """
            UPDATE counselling_sessions
            SET mobile_verified = 0, verification_method = NULL,
                verified_mobile_normalized = NULL, identity_mobile_normalized = NULL,
                identification_status = NULL, updated_at = ?
            WHERE id = ? AND institute_id = ?
            """,
            (now, session_id, actor.institute_id),
        )
        insert_event(
            conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
            actor_user_id=actor.id, event_type="mobile_changed", metadata={}, now=now,
        )
        conn.commit()
        return {"changed": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def override_otp(actor, session_id, mobile_input, reason, note=None):
    if actor.role != "admin":
        raise SmartCounsellingError("forbidden", "Only an administrator can authorize an OTP override.", 403)
    reason = str(reason or "").strip().upper()
    note = str(note or "").strip()
    if reason not in OTP_OVERRIDE_REASONS:
        raise validation_error("Choose a valid override reason.", {"reason": "A reason is required."})
    if reason == "OTHER" and not note:
        raise validation_error("Add a note for the override.", {"note": "A note is required for Other."})
    if len(note) > 500:
        raise validation_error("The override note is too long.", {"note": "Use 500 characters or fewer."})
    mobile = normalize_indian_mobile(mobile_input)
    conn = get_conn()
    now = _stamp(_utcnow())
    try:
        row = authorize_session(actor, get_session(conn, actor.institute_id, session_id))
        _ensure_identification_pending(row)
        invalidate_pending(conn, actor.institute_id, session_id, now)
        result = inspect_unverified_mobile(conn, actor, mobile)
        conn.execute(
            """
            UPDATE counselling_sessions
            SET mobile_verified = 0, verification_method = 'OVERRIDE',
                verified_mobile_normalized = NULL, identity_mobile_normalized = ?,
                identification_status = ?, updated_at = ?
            WHERE id = ? AND institute_id = ?
            """,
            (mobile, result["status"], now, session_id, actor.institute_id),
        )
        insert_event(
            conn, institute_id=actor.institute_id, session_id=session_id, lead_id=None,
            actor_user_id=actor.id, event_type="otp_override",
            metadata={"reason": reason, "note": note or None, "mobileMasked": mask_mobile(mobile)}, now=now,
        )
        conn.commit()
        return _identification_dto(result, False, "OVERRIDE", mobile)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
