from datetime import date

from flask import Blueprint, current_app, jsonify, render_template, request, session
from flask_wtf.csrf import CSRFError
from flask_limiter.errors import RateLimitExceeded

from db import get_company_profile, get_conn
from services.subscriptions import SubscriptionError, get_entitlement
from services.tenant_context import get_current_institute_id, require_tenant
from extensions import limiter

from .auth import current_actor, error_response, smart_counselling_staff_required
from .errors import SmartCounsellingError, validation_error
from .session_service import (
    abandon_counselling_session,
    counselling_dashboard,
    create_counselling_session,
    list_resumable_sessions,
    load_counselling_session,
    resume_counselling_session,
)
from .otp_service import change_mobile, get_otp_status, override_otp, send_otp, verify_otp
from .assessment_service import (
    get_assessment, get_profile, questionnaire, save_assessment, save_profile,
)
from .course_intelligence import (
    get_course_profile, list_course_profiles, save_course_profile, taxonomy,
)
from .recommendation_service import generate_recommendations, get_current_recommendations
from .course_experience import (
    compare_courses, get_course_details, get_course_syllabus,
    list_course_interests, set_course_interest,
)
from .outcome_service import (
    complete_session, get_outcome, get_summary, open_admission_handoff, save_outcome,
)
from .analytics_service import get_analytics
from .insights_service import get_lead_history
from .identity_resolution_service import confirm_identity_resolution, get_identity_resolution


smart_counselling_bp = Blueprint("smart_counselling", __name__)


def _success(data, status=200):
    return jsonify({"success": True, "data": data, "error": None}), status


@smart_counselling_bp.errorhandler(SmartCounsellingError)
def handle_smart_counselling_error(exc):
    return error_response(exc.code, exc.message, exc.status, exc.fields)


@smart_counselling_bp.errorhandler(CSRFError)
def handle_smart_counselling_csrf_error(exc):
    return error_response("validation_error", "The security token is missing or invalid.", 400)


@smart_counselling_bp.errorhandler(RateLimitExceeded)
def handle_smart_counselling_rate_limit(_exc):
    return error_response("rate_limited", "Too many requests. Please try again shortly.", 429)


def _feature_enabled():
    institute_id = get_current_institute_id()
    if not institute_id or not session.get("user_id"):
        return False
    conn = get_conn()
    try:
        entitlement = get_entitlement(conn, institute_id)
        return bool(entitlement.features.get("smart_counselling", False))
    except SubscriptionError:
        return False
    finally:
        conn.close()


@smart_counselling_bp.app_context_processor
def inject_smart_counselling_navigation():
    return {"smart_counselling_enabled": _feature_enabled()}


@smart_counselling_bp.get("/smart-counselling", strict_slashes=False)
@smart_counselling_bp.get("/smart-counselling/<path:client_path>", strict_slashes=False)
@smart_counselling_staff_required
def host(client_path=""):
    return render_template("smart_counselling/index.html")


@smart_counselling_bp.get("/api/smart-counselling/bootstrap")
@smart_counselling_staff_required
def bootstrap():
    tenant = require_tenant()
    actor = current_actor()
    company = get_company_profile(tenant.institute_id)
    conn = get_conn()
    try:
        branch_rows = conn.execute(
            """
            SELECT id, branch_name
            FROM branches
            WHERE institute_id = ? AND is_active = 1
            ORDER BY branch_name, id
            """,
            (actor.institute_id,),
        ).fetchall()
    finally:
        conn.close()
    active_branches = [
        {"id": int(branch["id"]), "name": branch["branch_name"]}
        for branch in branch_rows
        if actor.can_view_all_branches or int(branch["id"]) == int(actor.branch_id or 0)
    ]
    return _success({
        "apiVersion": "v1",
        "modulePhase": 9,
        "tenant": {
            "id": int(tenant.institute_id),
            "name": company.get("company_name") or tenant.name,
            "shortName": company.get("company_short_name") or tenant.short_name,
            "primaryColor": company.get("primary_color") or "#4a5bdb",
        },
        "staff": {
            "id": actor.id,
            "name": actor.full_name or actor.username or "Staff",
            "role": actor.role,
            "branchId": actor.branch_id,
            "canViewAllBranches": actor.can_view_all_branches,
        },
        "activeBranches": active_branches,
        "navigation": {
            "dashboard": "/smart-counselling",
            "start": "/smart-counselling/start",
        },
        "csrf": {"headerName": "X-CSRFToken"},
        "otp": {
            "length": 6,
            "overrideReasons": [
                "SMS_NOT_RECEIVED", "NETWORK_ISSUE", "PROSPECT_DECLINED",
                "NO_PHONE_ACCESS", "OTHER",
            ],
            "canOverride": actor.role == "admin",
        },
    })


@smart_counselling_bp.get("/api/smart-counselling/dashboard")
@smart_counselling_staff_required
def dashboard():
    result = counselling_dashboard(current_actor(), date.today().isoformat())
    return _success({
        "asOfDate": date.today().isoformat(),
        **result,
        "availability": {"readyForAdmission": "available", "managementAnalytics": "available"},
    })


@smart_counselling_bp.route("/api/smart-counselling/sessions", methods=["GET", "POST"])
@smart_counselling_staff_required
def sessions_collection():
    actor = current_actor()
    if request.method == "GET":
        requested_status = (request.args.get("status") or "open").strip().lower()
        if requested_status != "open":
            raise validation_error(
                "Only open counselling sessions can be listed in Phase 2.",
                {"status": "Use status=open."},
            )
        limit = request.args.get("limit", default=25, type=int) or 25
        return _success({"sessions": list_resumable_sessions(actor, limit)})

    payload = request.get_json(silent=True) or {}
    branch_id = payload.get("branchId")
    if branch_id is not None:
        try:
            branch_id = int(branch_id)
        except (TypeError, ValueError):
            raise validation_error("Choose a valid branch.", {"branchId": "Invalid branch."})
    created = create_counselling_session(actor, branch_id)
    return _success({"session": created}, 201)


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>")
@smart_counselling_staff_required
def session_detail(session_id):
    return _success({"session": load_counselling_session(current_actor(), session_id)})


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/resume")
@smart_counselling_staff_required
def session_resume(session_id):
    resumed = resume_counselling_session(current_actor(), session_id)
    return _success({"session": resumed})


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/abandon")
@smart_counselling_staff_required
def session_abandon(session_id):
    payload = request.get_json(silent=True) or {}
    abandoned = abandon_counselling_session(current_actor(), session_id, payload.get("reason"))
    return _success({"session": abandoned})


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/otp/send")
@limiter.limit(lambda: current_app.config.get("SMART_COUNSELLING_OTP_SEND_IP_LIMIT", "10 per minute"))
@smart_counselling_staff_required
def session_otp_send(session_id):
    payload = request.get_json(silent=True) or {}
    return _success(send_otp(current_actor(), session_id, payload.get("mobile")), 201)


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>/otp/status")
@smart_counselling_staff_required
def session_otp_status(session_id):
    return _success(get_otp_status(current_actor(), session_id))


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/otp/verify")
@limiter.limit(lambda: current_app.config.get("SMART_COUNSELLING_OTP_VERIFY_IP_LIMIT", "30 per minute"))
@smart_counselling_staff_required
def session_otp_verify(session_id):
    payload = request.get_json(silent=True) or {}
    try:
        challenge_id = int(payload.get("challengeId"))
    except (TypeError, ValueError):
        raise validation_error("Choose a valid OTP challenge.", {"challengeId": "Invalid challenge."})
    return _success(verify_otp(current_actor(), session_id, challenge_id, payload.get("otp")))


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/otp/change-mobile")
@smart_counselling_staff_required
def session_otp_change_mobile(session_id):
    return _success(change_mobile(current_actor(), session_id))


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/otp/override")
@smart_counselling_staff_required
def session_otp_override(session_id):
    payload = request.get_json(silent=True) or {}
    return _success(override_otp(
        current_actor(), session_id, payload.get("mobile"), payload.get("reason"), payload.get("note"),
    ))


@smart_counselling_bp.route(
    "/api/smart-counselling/sessions/<int:session_id>/identity-resolution",
    methods=["GET", "POST"],
)
@smart_counselling_staff_required
def session_identity_resolution(session_id):
    actor = current_actor()
    if request.method == "GET":
        return _success(get_identity_resolution(actor, session_id))
    payload = request.get_json(silent=True) or {}
    return _success(confirm_identity_resolution(actor, session_id, payload.get("leadId")))


@smart_counselling_bp.get("/api/smart-counselling/questionnaire")
@smart_counselling_staff_required
def counselling_questionnaire():
    return _success(questionnaire())


@smart_counselling_bp.route("/api/smart-counselling/sessions/<int:session_id>/profile", methods=["GET", "PUT"])
@smart_counselling_staff_required
def session_profile(session_id):
    actor = current_actor()
    if request.method == "GET":
        return _success(get_profile(actor, session_id))
    return _success(save_profile(actor, session_id, request.get_json(silent=True) or {}))


@smart_counselling_bp.route("/api/smart-counselling/sessions/<int:session_id>/assessment", methods=["GET", "PUT"])
@smart_counselling_staff_required
def session_assessment(session_id):
    actor = current_actor()
    if request.method == "GET":
        return _success(get_assessment(actor, session_id))
    return _success(save_assessment(actor, session_id, request.get_json(silent=True) or {}))


@smart_counselling_bp.route("/api/smart-counselling/sessions/<int:session_id>/recommendations", methods=["GET", "POST"])
@smart_counselling_staff_required
def session_recommendations(session_id):
    actor = current_actor()
    if request.method == "GET":
        return _success(get_current_recommendations(actor, session_id))
    return _success(generate_recommendations(actor, session_id), 201)


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>/courses/<int:course_id>")
@smart_counselling_staff_required
def session_course_details(session_id,course_id):
    return _success(get_course_details(current_actor(),session_id,course_id))


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>/courses/<int:course_id>/syllabus")
@smart_counselling_staff_required
def session_course_syllabus(session_id,course_id):
    return _success(get_course_syllabus(current_actor(),session_id,course_id))


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>/compare")
@smart_counselling_staff_required
def session_course_compare(session_id):
    raw=(request.args.get("course_ids") or "").split(",")
    try: course_ids=[int(value) for value in raw if value.strip()]
    except ValueError: raise validation_error("Choose valid courses to compare.",{"course_ids":"Invalid course ID."})
    return _success(compare_courses(current_actor(),session_id,course_ids))


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>/course-interests")
@smart_counselling_staff_required
def session_course_interests(session_id):
    return _success(list_course_interests(current_actor(),session_id))


@smart_counselling_bp.put("/api/smart-counselling/sessions/<int:session_id>/course-interests/<int:course_id>")
@smart_counselling_staff_required
def session_course_interest_update(session_id,course_id):
    return _success(set_course_interest(current_actor(),session_id,course_id,request.get_json(silent=True) or {}))


@smart_counselling_bp.route("/api/smart-counselling/sessions/<int:session_id>/outcome", methods=["GET", "PUT"])
@smart_counselling_staff_required
def session_outcome(session_id):
    actor = current_actor()
    if request.method == "GET": return _success(get_outcome(actor, session_id))
    return _success(save_outcome(actor, session_id, request.get_json(silent=True) or {}))


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/complete")
@smart_counselling_staff_required
def session_complete(session_id):
    return _success(complete_session(current_actor(), session_id, request.get_json(silent=True) or {}))


@smart_counselling_bp.get("/api/smart-counselling/sessions/<int:session_id>/summary")
@smart_counselling_staff_required
def session_summary(session_id):
    return _success(get_summary(current_actor(), session_id))


@smart_counselling_bp.post("/api/smart-counselling/sessions/<int:session_id>/admission-handoff")
@smart_counselling_staff_required
def session_admission_handoff(session_id):
    return _success(open_admission_handoff(current_actor(), session_id))


@smart_counselling_bp.get("/api/smart-counselling/leads/<int:lead_id>/history")
@smart_counselling_staff_required
def lead_counselling_history(lead_id):
    return _success(get_lead_history(current_actor(), lead_id))


@smart_counselling_bp.get("/api/smart-counselling/analytics")
@smart_counselling_staff_required
def smart_counselling_analytics():
    return _success(get_analytics(current_actor(), request.args))


@smart_counselling_bp.get("/api/smart-counselling/course-profile-taxonomy")
@smart_counselling_staff_required
def course_profile_taxonomy():
    return _success(taxonomy())


@smart_counselling_bp.get("/api/smart-counselling/course-profiles")
@smart_counselling_staff_required
def course_profiles_collection():
    return _success({"profiles": list_course_profiles(current_actor())})


@smart_counselling_bp.route("/api/smart-counselling/course-profiles/<int:course_id>", methods=["GET", "PUT"])
@smart_counselling_staff_required
def course_profile_detail(course_id):
    actor = current_actor()
    if request.method == "GET":
        return _success(get_course_profile(actor, course_id))
    return _success(save_course_profile(actor, course_id, request.get_json(silent=True) or {}))


@smart_counselling_bp.get("/smart-counselling/course-intelligence/<int:course_id>")
@smart_counselling_staff_required
def course_profile_admin(course_id):
    actor = current_actor()
    if actor.role != "admin":
        raise SmartCounsellingError("forbidden", "Course intelligence is restricted to administrators.", 403)
    return render_template(
        "smart_counselling/course_profile.html",
        course_profile=get_course_profile(actor, course_id), taxonomy=taxonomy(),
    )
