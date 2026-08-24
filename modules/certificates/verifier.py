from db import get_company_profile
from services.tenant_context import get_current_institute_id
from .verification_tokens import is_certificate_verification_token_valid


def _format_certificate_result(cur, cert, current_institute_id):
    student = cur.execute(
        """
        SELECT b.branch_name
        FROM students s
        LEFT JOIN branches b ON b.id = s.branch_id
        WHERE s.id = ?
        """,
        (cert["student_id"],)
    ).fetchone()

    branch_name = student["branch_name"] if student and student["branch_name"] else "Head Office"

    company = get_company_profile(current_institute_id)
    institution_name = company["company_name"]

    return {
        "certificate_number": cert["certificate_number"],
        "student_name": cert["student_name"],
        "course_name": cert["course_name"],
        "grade": cert["grade"],
        "issue_date": cert["issue_date"],
        "completion_date": cert["completion_date"],
        "branch": branch_name,
        "institution_name": institution_name,
        "status": cert["status"],
        "qr_verified_status": True if cert["status"] == "Active" else False,
        "certificate_id": cert["certificate_id"]
    }


def verify_certificate_number(conn, certificate_number):
    """
    Looks up a certificate directly by number, returning only safe metadata for public display.
    """
    cur = conn.cursor()
    
    # Fast, indexed lookup on certificates table first
    current_institute_id = get_current_institute_id(default=1)
    cert = cur.execute(
        """
        SELECT 
            c.id AS certificate_id,
            c.certificate_number,
            c.snapshot_student_name AS student_name,
            c.snapshot_course_name AS course_name,
            c.snapshot_grade AS grade,
            c.snapshot_completion_date AS completion_date,
            c.issue_date,
            c.status,
            c.student_id
        FROM certificates c
        WHERE c.certificate_number = ?
          AND c.institute_id = ?
        """,
        (certificate_number, current_institute_id)
    ).fetchone()
    
    if not cert:
        return None

    return _format_certificate_result(cur, cert, current_institute_id)


def verify_certificate_signed(conn, cert_id, token):
    """
    Verifies a QR-code link bound to one certificate row and a signed token.
    """
    cur = conn.cursor()
    current_institute_id = get_current_institute_id(default=1)
    cert = cur.execute(
        """
        SELECT
            c.id AS certificate_id,
            c.certificate_number,
            c.snapshot_student_name AS student_name,
            c.snapshot_course_name AS course_name,
            c.snapshot_grade AS grade,
            c.snapshot_completion_date AS completion_date,
            c.issue_date,
            c.status,
            c.student_id
        FROM certificates c
        WHERE c.id = ?
          AND c.institute_id = ?
        """,
        (cert_id, current_institute_id)
    ).fetchone()

    if not cert:
        return None

    if not is_certificate_verification_token_valid(
        cert["certificate_id"],
        cert["certificate_number"],
        token
    ):
        return None

    return _format_certificate_result(cur, cert, current_institute_id)
