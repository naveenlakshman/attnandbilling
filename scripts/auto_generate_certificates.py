"""
Background Task: Automatic Certificate Generation
Finds all students who have passed their final exam at least 24 hours ago,
performs a complete eligibility checklist validation, and issues their certificates.

Run as:
    python scripts/auto_generate_certificates.py
"""

import sys
import os
import datetime

# Add project root to sys.path to enable absolute imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import get_conn
from modules.certificates.services import EligibilityService, CertificateService


def run():
    print("-------------------------------------------------------------------")
    print(f"Starting Certificate Auto-Generation Task at: {datetime.datetime.now()}")
    print("-------------------------------------------------------------------")

    conn = get_conn()
    try:
        cur = conn.cursor()

        # 1. Fetch certificate settings
        settings = EligibilityService.get_settings(cur)
        if settings.get("auto_generate_certificates", 1) != 1:
            print("Automatic certificate generation is disabled in settings. Exiting.")
            return

        pass_threshold = settings.get("default_pass_percentage", 50.0)

        # 2. Query students who passed the final exam at least 24 hours ago
        # and do not have an Active certificate for the corresponding course.
        # lp.course_id maps to courses.id
        passed_attempts = cur.execute(
            """
            SELECT 
                att.student_id,
                lp.course_id,
                att.score_percent,
                att.submitted_at,
                s.full_name AS student_name,
                c.course_name
            FROM lms_final_exam_attempts att
            JOIN students s ON s.id = att.student_id
            JOIN lms_programs lp ON lp.id = att.course_id
            JOIN courses c ON c.id = lp.course_id
            WHERE att.score_percent >= ?
              AND datetime(att.submitted_at) <= datetime('now', '-24 hours')
              AND NOT EXISTS (
                  SELECT 1 FROM certificates cert
                  WHERE cert.student_id = att.student_id
                    AND cert.course_id = lp.course_id
                    AND cert.status = 'Active'
              )
            ORDER BY att.submitted_at ASC
            """,
            (pass_threshold,),
        ).fetchall()

        if not passed_attempts:
            print("No new eligible candidates found with final exams completed > 24 hours ago.")
            return

        print(f"Found {len(passed_attempts)} candidate(s) to evaluate.")
        success_count = 0

        for attempt in passed_attempts:
            student_id = attempt["student_id"]
            course_id = attempt["course_id"]
            student_name = attempt["student_name"]
            course_name = attempt["course_name"]
            score = attempt["score_percent"]
            submitted_at = attempt["submitted_at"]

            print(f"\nEvaluating: {student_name} (ID: {student_id}) for '{course_name}'")
            print(f"  Passed Exam: {score}% on {submitted_at}")

            # Verify complete eligibility
            is_eligible, reasons, details = EligibilityService.check_eligibility(cur, student_id, course_id)

            if not is_eligible:
                unmet = [k for k, v in reasons.items() if not v]
                print(f"  -> Candidate not eligible. Unmet conditions: {', '.join(unmet)}")
                continue

            # Attempt transactional issuance
            try:
                cert_no = CertificateService.issue_certificate(
                    conn,
                    student_id,
                    course_id,
                    performed_by=None,
                    ip_address="Background Cron",
                    user_agent="System Auto-Generation Flow",
                    force=False
                )
                conn.commit()
                print(f"  -> SUCCESS! Certificate generated: {cert_no}")
                success_count += 1
            except Exception as e:
                conn.rollback()
                print(f"  -> ERROR generating certificate: {str(e)}")

        print("\n-------------------------------------------------------------------")
        print(f"Process finished. Generated {success_count} new certificate(s).")
        print("-------------------------------------------------------------------")

    finally:
        conn.close()


if __name__ == "__main__":
    run()
