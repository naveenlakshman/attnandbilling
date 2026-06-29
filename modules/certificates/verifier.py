def verify_certificate_number(conn, certificate_number):
    """
    Looks up a certificate directly by number, returning only safe metadata for public display.
    """
    cur = conn.cursor()
    
    # Fast, indexed lookup on certificates table first
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
        """,
        (certificate_number,)
    ).fetchone()
    
    if not cert:
        return None
        
    # Fetch branch details dynamically
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
    
    # Fetch general company profile
    company = cur.execute("SELECT company_name FROM company_profile WHERE id = 1").fetchone()
    institution_name = company["company_name"] if company else "Global IT Education"

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
