import datetime
from db import get_conn
from .numbering import generate_certificate_number
from .audit import log_certificate_action

class EligibilityService:
    @staticmethod
    def get_settings(cur):
        row = cur.execute("SELECT * FROM certificate_settings WHERE id = 1").fetchone()
        if row:
            return dict(row)
        return {
            "default_pass_percentage": 50.0,
            "auto_generate_certificates": 1,
            "allow_manual_issue": 1,
            "allow_reissue": 1,
            "show_student_photo": 1,
            "show_grade": 1,
            "enable_certificate_verification": 1,
            "prefix": "GIT",
            "sequence_length": 6
        }

    @classmethod
    def check_eligibility(cls, cur, student_id, course_id):
        """
        Evaluates student eligibility for a certificate for a given Course ID.
        Returns (is_eligible, reasons_dict, details_dict)
        """
        settings = cls.get_settings(cur)
        pass_threshold = settings.get("default_pass_percentage", 50.0)

        # 1. Fetch Course details
        course = cur.execute(
            "SELECT id, course_name, duration FROM courses WHERE id = ?",
            (course_id,)
        ).fetchone()
        if not course:
            return False, {"error": "Course not found"}, {}

        # Resolve active program_id for this course to check syllabus/assignment progress
        program_row = cur.execute(
            """
            SELECT lp.id
            FROM lms_programs lp
            JOIN lms_student_program_access spa ON spa.program_id = lp.id
            WHERE lp.course_id = ? AND spa.student_id = ? AND spa.is_active = 1
            UNION
            SELECT lp.id
            FROM lms_programs lp
            JOIN lms_batch_program_access bpa ON bpa.program_id = lp.id
            JOIN student_batches sb ON sb.batch_id = bpa.batch_id
            WHERE lp.course_id = ? AND sb.student_id = ? AND sb.status = 'active'
            LIMIT 1
            """,
            (course_id, student_id, course_id, student_id)
        ).fetchone()

        program_id = None
        if program_row:
            program_id = program_row["id"]
        else:
            # Fallback to the first active program mapping to this course
            fallback_program = cur.execute(
                "SELECT id FROM lms_programs WHERE course_id = ? AND is_active = 1 AND COALESCE(is_deleted, 0) = 0 LIMIT 1",
                (course_id,)
            ).fetchone()
            program_id = fallback_program["id"] if fallback_program else None

        # 2. Check Exam Attempt (Must pass)
        attempt = cur.execute(
            """
            SELECT score_percent, submitted_at
            FROM lms_final_exam_attempts
            WHERE student_id = ? AND course_id = ?
            ORDER BY score_percent DESC, submitted_at DESC
            LIMIT 1
            """,
            (student_id, program_id)
        ).fetchone()

        has_passed_exam = False
        exam_score = 0
        completion_date = datetime.date.today().isoformat()
        
        if attempt:
            exam_score = attempt["score_percent"]
            has_passed_exam = exam_score >= pass_threshold
            if attempt["submitted_at"]:
                completion_date = attempt["submitted_at"][:10]

        # 3. Syllabus & Assignment Progress Checks
        syllabus_completed = False
        assignments_completed = False
        syllabus = {"completed": 0, "total": 0, "passed": False}
        assignments = {"submitted": 0, "total": 0, "passed": False}

        if program_id:
            from modules.exams.routes import _final_exam_syllabus_check
            syllabus = _final_exam_syllabus_check(cur, student_id, program_id)
            syllabus_completed = syllabus.get("passed", False)

            from modules.exams.routes import _final_exam_assignment_check
            assignments = _final_exam_assignment_check(cur, student_id, program_id)
            assignments_completed = assignments.get("passed", False)

        # 4. Financial Dues (Must be <= 0 balance)
        from modules.exams.routes import _final_exam_dues_check
        dues = _final_exam_dues_check(cur, student_id)
        no_dues = dues.get("passed", False)

        # 5. Course Invoiced Check
        invoice_check = cur.execute(
            """
            SELECT ii.id
            FROM invoice_items ii
            JOIN invoices i ON i.id = ii.invoice_id
            WHERE i.student_id = ? AND ii.course_id = ? AND i.status != 'cancelled'
            LIMIT 1
            """,
            (student_id, course_id)
        ).fetchone()
        is_invoiced = invoice_check is not None

        # 6. Student Profile Verification Check (Must have an approved final exam application)
        app_check = cur.execute(
            """
            SELECT id FROM lms_final_exam_applications
            WHERE student_id = ? AND course_id = ? AND status = 'APPROVED'
            LIMIT 1
            """,
            (student_id, program_id)
        ).fetchone()
        is_profile_verified = app_check is not None

        is_eligible = (
            has_passed_exam
            and syllabus_completed
            and assignments_completed
            and no_dues
            and is_invoiced
            and is_profile_verified
        )

        reasons = {
            "has_passed_exam": has_passed_exam,
            "syllabus_completed": syllabus_completed,
            "assignments_completed": assignments_completed,
            "no_dues": no_dues,
            "is_invoiced": is_invoiced,
            "is_profile_verified": is_profile_verified
        }

        details = {
            "exam_score": exam_score,
            "exam_threshold": pass_threshold,
            "syllabus": syllabus,
            "assignments": assignments,
            "dues": dues,
            "completion_date": completion_date,
            "course_id": course_id,
            "course_name": course["course_name"],
            "course_duration": course["duration"],
            "is_profile_verified": is_profile_verified
        }

        return is_eligible, reasons, details


class CertificateService:
    @staticmethod
    def get_grade_from_score(score):
        if score >= 90: return "A+"
        if score >= 80: return "A"
        if score >= 70: return "B"
        if score >= 60: return "C"
        if score >= 50: return "Pass"
        return "Fail"

    @classmethod
    def issue_certificate(cls, conn, student_id, course_id, grade=None, completion_date=None, notes=None, performed_by=None, ip_address=None, user_agent=None, force=False):
        """
        Transactional service logic to generate a certificate.
        If force=True, bypasses Eligibility Checks (admin manual issuance).
        """
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        
        # 1. Fetch settings
        settings = EligibilityService.get_settings(cur)
        
        # 2. Check if student already has an Active certificate for the course
        existing = cur.execute(
            "SELECT id FROM certificates WHERE student_id = ? AND course_id = ? AND status = 'Active'",
            (student_id, course_id)
        ).fetchone()
        
        if existing:
            raise ValueError("Student already holds an Active certificate for this course.")

        # 3. Verify eligibility
        is_eligible, reasons, details = EligibilityService.check_eligibility(cur, student_id, course_id)
        if not force and not is_eligible:
            unmet = [k for k, v in reasons.items() if not v]
            raise ValueError(f"Student is not eligible for certificate. Unmet: {', '.join(unmet)}")

        # 4. Resolve Template & Version
        # Course template -> Default setting template -> Active fallback
        course = cur.execute("SELECT certificate_template_id FROM courses WHERE id = ?", (course_id,)).fetchone()
        template_id = course["certificate_template_id"] if course else None
        
        if not template_id:
            template_id = settings.get("default_template_id")
            
        if not template_id:
            # Fallback to any active default template in db
            fallback = cur.execute("SELECT id FROM certificate_templates WHERE is_active = 1 ORDER BY is_default DESC, id DESC LIMIT 1").fetchone()
            if not fallback:
                raise ValueError("No active certificate templates are defined in the database.")
            template_id = fallback["id"]

        # Fetch template metadata
        template = cur.execute(
            "SELECT * FROM certificate_templates WHERE id = ?",
            (template_id,)
        ).fetchone()
        if not template:
            raise ValueError("Certificate template not found.")

        # 5. Fetch Student and Course snapshots
        student = cur.execute(
            """
            SELECT s.full_name, s.student_code, b.branch_name
            FROM students s
            LEFT JOIN branches b ON b.id = s.branch_id
            WHERE s.id = ?
            """,
            (student_id,)
        ).fetchone()
        if not student:
            raise ValueError("Student not found")

        # Resolve active program_id for this course to link the certificate record
        program_row = cur.execute(
            """
            SELECT lp.id
            FROM lms_programs lp
            JOIN lms_student_program_access spa ON spa.program_id = lp.id
            WHERE lp.course_id = ? AND spa.student_id = ? AND spa.is_active = 1
            UNION
            SELECT lp.id
            FROM lms_programs lp
            JOIN lms_batch_program_access bpa ON bpa.program_id = lp.id
            JOIN student_batches sb ON sb.batch_id = bpa.batch_id
            WHERE lp.course_id = ? AND sb.student_id = ? AND sb.status = 'active'
            LIMIT 1
            """,
            (course_id, student_id, course_id, student_id)
        ).fetchone()

        program_id = None
        if program_row:
            program_id = program_row["id"]
        else:
            # Fallback to the first active program mapping to this course
            fallback_program = cur.execute(
                "SELECT id FROM lms_programs WHERE course_id = ? AND is_active = 1 AND COALESCE(is_deleted, 0) = 0 LIMIT 1",
                (course_id,)
            ).fetchone()
            program_id = fallback_program["id"] if fallback_program else None

        # 6. Calculate static snapshots
        score_val = details.get("exam_score", 0.0)
        grade_val = grade if grade else cls.get_grade_from_score(score_val)
        comp_date = completion_date if completion_date else details.get("completion_date", now[:10])
        
        # 7. Generate certificate number atomically
        completion_year = int(comp_date[:4])
        cert_no = generate_certificate_number(conn, template["template_code"], completion_year, settings)

        # 8. Write Certificate Record
        cur.execute(
            """
            INSERT INTO certificates (
                certificate_number, student_id, course_id, program_id, template_id,
                snapshot_student_name, snapshot_student_reg, snapshot_course_name, snapshot_course_duration,
                snapshot_grade, snapshot_completion_date, issue_date, score, status, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?)
            """,
            (
                cert_no,
                student_id,
                course_id,
                program_id,
                template["id"],
                student["full_name"],
                student["student_code"],
                details.get("course_name"),
                details.get("course_duration"),
                grade_val,
                comp_date,
                now[:10],
                score_val,
                notes,
                performed_by,
                now
            )
        )
        cert_id = cur.lastrowid
        
        # 9. Audit Log action
        log_certificate_action(
            conn, cert_id, "Issued",
            performed_by=performed_by,
            new_status="Active",
            reason="Certificate earned/issued",
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return cert_no

    @classmethod
    def reissue_certificate(cls, conn, cert_id, reason=None, performed_by=None, ip_address=None, user_agent=None):
        """
        Transactional service logic to reissue a certificate.
        Replaces the old certificate with a new sequence-incremented version.
        """
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        
        # 1. Fetch old certificate
        old_cert = cur.execute("SELECT * FROM certificates WHERE id = ?", (cert_id,)).fetchone()
        if not old_cert:
            raise ValueError("Original certificate not found.")
        
        if old_cert["status"] != "Active":
            raise ValueError("Only Active certificates can be reissued.")

        # 2. Mark old certificate as Re-issued
        cur.execute(
            "UPDATE certificates SET status = 'Re-issued', updated_at = ? WHERE id = ?",
            (now, cert_id)
        )
        
        # 3. Log Re-issue on old certificate
        log_certificate_action(
            conn, cert_id, "Re-issued",
            performed_by=performed_by,
            previous_status="Active",
            new_status="Re-issued",
            reason=reason or "Re-issued by Administrator",
            ip_address=ip_address,
            user_agent=user_agent
        )

        # 4. Fetch settings
        settings = EligibilityService.get_settings(cur)

        # 5. Fetch template code
        template = cur.execute("SELECT template_code FROM certificate_templates WHERE id = ?", (old_cert["template_id"],)).fetchone()
        template_code = template["template_code"] if template else "CERT"

        # 6. Generate new certificate number atomically
        completion_year = int(old_cert["snapshot_completion_date"][:4])
        new_cert_no = generate_certificate_number(conn, template_code, completion_year, settings)

        # 7. Write New Certificate Record (Copy snapshots from old certificate)
        cur.execute(
            """
            INSERT INTO certificates (
                certificate_number, student_id, course_id, program_id, template_id,
                snapshot_student_name, snapshot_student_reg, snapshot_course_name, snapshot_course_duration,
                snapshot_grade, snapshot_completion_date, issue_date, score, status, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?)
            """,
            (
                new_cert_no,
                old_cert["student_id"],
                old_cert["course_id"],
                old_cert["program_id"],
                old_cert["template_id"],
                old_cert["snapshot_student_name"],
                old_cert["snapshot_student_reg"],
                old_cert["snapshot_course_name"],
                old_cert["snapshot_course_duration"],
                old_cert["snapshot_grade"],
                old_cert["snapshot_completion_date"],
                now[:10],
                old_cert["score"],
                f"Reissued replacement for {old_cert['certificate_number']}. Reason: {reason}",
                performed_by,
                now
            )
        )
        new_cert_id = cur.lastrowid

        # 8. Log Issue on new certificate
        log_certificate_action(
            conn, new_cert_id, "Issued",
            performed_by=performed_by,
            new_status="Active",
            reason=f"Reissued replacement for {old_cert['certificate_number']}",
            ip_address=ip_address,
            user_agent=user_agent
        )

        return new_cert_no

    @classmethod
    def revoke_certificate(cls, conn, cert_id, reason=None, performed_by=None, ip_address=None, user_agent=None):
        """
        Transactional service logic to revoke a certificate.
        """
        cur = conn.cursor()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        
        # 1. Fetch certificate
        cert = cur.execute("SELECT * FROM certificates WHERE id = ?", (cert_id,)).fetchone()
        if not cert:
            raise ValueError("Certificate not found.")
        
        if cert["status"] != "Active":
            raise ValueError("Only Active certificates can be revoked.")

        # 2. Update status to Revoked
        cur.execute(
            "UPDATE certificates SET status = 'Revoked', updated_at = ? WHERE id = ?",
            (now, cert_id)
        )
        
        # 3. Log Revocation
        log_certificate_action(
            conn, cert_id, "Revoked",
            performed_by=performed_by,
            previous_status="Active",
            new_status="Revoked",
            reason=reason or "Revoked by Administrator",
            ip_address=ip_address,
            user_agent=user_agent
        )
