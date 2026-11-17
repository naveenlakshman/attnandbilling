"""Administrator-controlled final-exam scheduling with a dry-run preview."""

from datetime import date, datetime

from db import log_activity


def _student_programs(cur, institute_id, student_id):
    return cur.execute(
        """
        SELECT DISTINCT lp.id, lp.program_name, c.course_name
        FROM lms_programs lp
        LEFT JOIN courses c
          ON c.id = lp.course_id AND c.institute_id = lp.institute_id
        WHERE lp.institute_id = ?
          AND lp.is_active = 1
          AND COALESCE(lp.is_deleted, 0) = 0
          AND (
            EXISTS (
              SELECT 1 FROM lms_student_program_access spa
              WHERE spa.student_id = ? AND spa.program_id = lp.id
                AND spa.institute_id = ? AND spa.is_active = 1
                AND COALESCE(spa.access_status, 'active') = 'active'
                AND (spa.access_end_date IS NULL OR spa.access_end_date >= date('now'))
            )
            OR EXISTS (
              SELECT 1
              FROM lms_batch_program_access bpa
              JOIN student_batches sb ON sb.batch_id = bpa.batch_id
              WHERE sb.student_id = ? AND sb.status = 'active'
                AND bpa.program_id = lp.id AND bpa.institute_id = ?
                AND bpa.is_active = 1
                AND (bpa.access_end_date IS NULL OR bpa.access_end_date >= date('now'))
            )
            OR EXISTS (
              SELECT 1
              FROM invoices i
              JOIN invoice_items ii ON ii.invoice_id = i.id
              WHERE i.student_id = ? AND i.institute_id = ?
                AND ii.course_id = lp.course_id AND lp.course_id IS NOT NULL
            )
            OR EXISTS (
              SELECT 1
              FROM invoices i
              JOIN invoice_items ii ON ii.invoice_id = i.id
              JOIN lms_course_program_map cpm
                ON cpm.course_id = ii.course_id AND cpm.program_id = lp.id
              WHERE i.student_id = ? AND i.institute_id = ?
            )
          )
        ORDER BY COALESCE(c.course_name, lp.program_name), lp.program_name
        """,
        (
            institute_id,
            student_id,
            institute_id,
            student_id,
            institute_id,
            student_id,
            institute_id,
            student_id,
            institute_id,
        ),
    ).fetchall()


def _question_count(cur, institute_id, program_id):
    row = cur.execute(
        """
        SELECT COUNT(DISTINCT qb.id) AS question_count
        FROM lms_programs lp
        JOIN lms_program_chapters pc ON pc.program_id = lp.id
        JOIN lms_master_chapters mc ON mc.id = pc.master_chapter_id
        JOIN lms_question_bank qb ON qb.chapter_id = mc.id
        WHERE lp.id = ? AND lp.institute_id = ?
          AND COALESCE(pc.is_visible, 1) = 1
          AND COALESCE(mc.status, 'active') = 'active'
          AND (qb.institute_id = ? OR COALESCE(qb.is_shared, 0) = 1)
        """,
        (program_id, institute_id, institute_id),
    ).fetchone()
    return int(row["question_count"] or 0)


def preview_manual_schedule(cur, institute_id, branch_id):
    branch = cur.execute(
        """SELECT id, branch_name FROM branches
           WHERE id = ? AND institute_id = ? AND is_active = 1""",
        (branch_id, institute_id),
    ).fetchone()
    if not branch:
        raise ValueError("Choose an active branch in this institute.")

    students = cur.execute(
        """
        SELECT id, student_code, full_name, phone, date_of_birth
        FROM students
        WHERE institute_id = ? AND branch_id = ? AND status = 'active'
        ORDER BY full_name, id
        """,
        (institute_id, branch_id),
    ).fetchall()

    rows = []
    students_without_program = []
    for student in students:
        programs = _student_programs(cur, institute_id, student["id"])
        if not programs:
            students_without_program.append(dict(student))
            continue
        for program in programs:
            attempted = cur.execute(
                """SELECT id FROM lms_final_exam_attempts
                   WHERE student_id = ? AND course_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (student["id"], program["id"]),
            ).fetchone()
            current = cur.execute(
                """SELECT app.id, app.status, app.requested_exam_date
                   FROM lms_final_exam_applications app
                   JOIN students owner ON owner.id = app.student_id
                   WHERE owner.institute_id = ?
                     AND app.student_id = ? AND app.course_id = ?
                   ORDER BY app.applied_on DESC, app.id DESC LIMIT 1""",
                (institute_id, student["id"], program["id"]),
            ).fetchone()
            questions = _question_count(cur, institute_id, program["id"])
            if attempted:
                action = "skip_attempted"
            elif questions == 0:
                action = "blocked_no_questions"
            elif current and current["status"] in ("PENDING", "APPROVED"):
                action = "reschedule"
            else:
                action = "create"
            rows.append(
                {
                    "student": dict(student),
                    "program": dict(program),
                    "question_count": questions,
                    "application": dict(current) if current else None,
                    "action": action,
                }
            )

    return {
        "branch": dict(branch),
        "student_count": len(students),
        "students_without_program": students_without_program,
        "rows": rows,
        "schedulable_count": sum(row["action"] in ("create", "reschedule") for row in rows),
        "create_count": sum(row["action"] == "create" for row in rows),
        "reschedule_count": sum(row["action"] == "reschedule" for row in rows),
        "attempted_count": sum(row["action"] == "skip_attempted" for row in rows),
        "blocked_question_count": sum(row["action"] == "blocked_no_questions" for row in rows),
    }


def apply_manual_schedule(conn, institute_id, branch_id, exam_date, actor_id):
    try:
        parsed_date = date.fromisoformat(exam_date)
    except (TypeError, ValueError):
        raise ValueError("Choose a valid exam date.") from None
    if parsed_date < date.today():
        raise ValueError("Exam date cannot be in the past.")

    cur = conn.cursor()
    preview = preview_manual_schedule(cur, institute_id, branch_id)
    stamp = datetime.now().isoformat(timespec="seconds")
    scheduled_ids = []
    for row in preview["rows"]:
        if row["action"] not in ("create", "reschedule"):
            continue
        student = row["student"]
        program = row["program"]
        application = row["application"]
        if row["action"] == "reschedule":
            application_id = application["id"]
            cur.execute(
                """UPDATE lms_final_exam_applications
                   SET requested_exam_date = ?, status = 'APPROVED'
                   WHERE id = ? AND student_id = ?""",
                (exam_date, application_id, student["id"]),
            )
        else:
            cur.execute(
                """
                INSERT INTO lms_final_exam_applications (
                    student_id, course_id, verified_name,
                    verified_phone, verified_dob, requested_exam_date, status, applied_on
                ) VALUES (?, ?, ?, ?, ?, ?, 'APPROVED', ?)
                """,
                (
                    student["id"],
                    program["id"],
                    student["full_name"] or "Not provided",
                    student["phone"] or "Not provided",
                    str(student["date_of_birth"] or "Not provided"),
                    exam_date,
                    stamp,
                ),
            )
            application_id = cur.lastrowid

        log_activity(
            user_id=actor_id,
            branch_id=branch_id,
            action_type="manual_schedule",
            module_name="lms_final_exam_applications",
            record_id=application_id,
            description=(
                f"Administrator scheduled final exam on {exam_date}; "
                f"program {program['id']} uses {row['question_count']} question-bank questions; "
                "accepted offline topic/assignment evidence and deferred fee settlement"
            ),
            conn=conn,
            institute_id=institute_id,
        )
        scheduled_ids.append(application_id)

    return preview, scheduled_ids


def has_manual_fee_override(cur, institute_id, student_id, application_id=None):
    params = [institute_id, student_id]
    application_filter = ""
    if application_id is not None:
        application_filter = " AND app.id = ?"
        params.append(application_id)
    return cur.execute(
        f"""
        SELECT app.id
        FROM lms_final_exam_applications app
        JOIN students owner ON owner.id = app.student_id
        JOIN activity_logs al
          ON al.record_id = app.id
         AND al.institute_id = owner.institute_id
         AND al.module_name = 'lms_final_exam_applications'
         AND al.action_type = 'manual_schedule'
        WHERE owner.institute_id = ? AND app.student_id = ?
          AND app.status = 'APPROVED'
          {application_filter}
        ORDER BY app.requested_exam_date DESC, app.id DESC
        LIMIT 1
        """,
        tuple(params),
    ).fetchone() is not None
