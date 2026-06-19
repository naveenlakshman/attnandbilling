import random

from flask import flash, redirect, render_template, request, session, url_for

from db import get_conn, log_activity
from modules.core.utils import lms_content_manager_required
from . import exams_bp


VALID_CORRECT_OPTIONS = {"A", "B", "C", "D"}


def _get_programs(cur):
    return cur.execute(
        """
            SELECT
                lp.id,
                lp.program_name,
                c.course_name
            FROM lms_programs lp
            LEFT JOIN courses c ON c.id = lp.course_id
            WHERE COALESCE(lp.is_deleted, 0) = 0
            ORDER BY c.course_name COLLATE NOCASE, lp.program_name COLLATE NOCASE
        """
    ).fetchall()


def _get_chapters(cur):
    return cur.execute(
        """
            SELECT
                mc.id,
                mc.title,
                mc.status,
                GROUP_CONCAT(DISTINCT pc.program_id) AS program_ids
            FROM lms_master_chapters mc
            LEFT JOIN lms_program_chapters pc ON pc.master_chapter_id = mc.id
            GROUP BY mc.id
            ORDER BY mc.title COLLATE NOCASE
        """
    ).fetchall()


def _get_questions(cur):
    return cur.execute(
        """
            SELECT
                qb.id,
                qb.chapter_id,
                qb.question_text,
                qb.option_a,
                qb.option_b,
                qb.option_c,
                qb.option_d,
                qb.correct_option,
                qb.question_type,
                COALESCE(mc.title, 'Unknown Chapter') AS chapter_name,
                GROUP_CONCAT(DISTINCT pc.program_id) AS program_ids
            FROM lms_question_bank qb
            LEFT JOIN lms_master_chapters mc ON mc.id = qb.chapter_id
            LEFT JOIN lms_program_chapters pc ON pc.master_chapter_id = mc.id
            GROUP BY qb.id
            ORDER BY qb.id DESC
        """
    ).fetchall()


def _get_question_bank_context(cur):
    return _get_programs(cur), _get_chapters(cur), _get_questions(cur)


def _question_form_fields():
    return {
        "chapter_id": request.form.get("chapter_id", "").strip(),
        "question_text": request.form.get("question_text", "").strip(),
        "option_a": request.form.get("option_a", "").strip(),
        "option_b": request.form.get("option_b", "").strip(),
        "option_c": request.form.get("option_c", "").strip(),
        "option_d": request.form.get("option_d", "").strip(),
        "correct_option": request.form.get("correct_option", "").strip().upper(),
    }


def _validate_question_fields(fields):
    if any(not value for value in fields.values()):
        return "All question fields are required."

    if not fields["chapter_id"].isdigit():
        return "Please select a valid chapter."

    if fields["correct_option"] not in VALID_CORRECT_OPTIONS:
        return "Correct answer must be A, B, C, or D."

    return None


def _student_required_redirect():
    if "student_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("students.login"))
    return None


@exams_bp.route("/lms_admin/questions/manage", methods=["GET"])
@lms_content_manager_required
def manage_questions():
    conn = get_conn()
    try:
        cur = conn.cursor()
        programs = _get_programs(cur)
        chapters = _get_chapters(cur)
        return render_template(
            "exams/admin_manage_questions.html",
            programs=programs,
            chapters=chapters,
            question=None,
            form_action=url_for("exams.add_question"),
            submit_label="Add Question",
            page_heading="Add Question",
            page_subtitle="Create MCQ questions linked to reusable LMS chapters.",
        )
    finally:
        conn.close()


@exams_bp.route("/lms_admin/questions/view", methods=["GET"])
@lms_content_manager_required
def view_questions():
    conn = get_conn()
    try:
        cur = conn.cursor()
        programs, chapters, questions = _get_question_bank_context(cur)
        return render_template(
            "exams/admin_view_questions.html",
            programs=programs,
            chapters=chapters,
            questions=questions,
        )
    finally:
        conn.close()


@exams_bp.route("/lms_admin/questions/edit/<int:question_id>", methods=["GET"])
@lms_content_manager_required
def edit_question(question_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        question = cur.execute(
            "SELECT * FROM lms_question_bank WHERE id = ?",
            (question_id,),
        ).fetchone()
        if not question:
            flash("Question not found.", "warning")
            return redirect(url_for("exams.view_questions"))

        programs = _get_programs(cur)
        chapters = _get_chapters(cur)
        return render_template(
            "exams/admin_manage_questions.html",
            programs=programs,
            chapters=chapters,
            question=question,
            form_action=url_for("exams.update_question", question_id=question_id),
            submit_label="Update Question",
            page_heading=f"Edit Question #{question_id}",
            page_subtitle="Update the question, options, chapter, and correct answer.",
        )
    finally:
        conn.close()


@exams_bp.route("/lms_admin/questions/add", methods=["POST"])
@lms_content_manager_required
def add_question():
    fields = _question_form_fields()
    error = _validate_question_fields(fields)
    if error:
        flash(error, "danger")
        return redirect(url_for("exams.manage_questions"))

    chapter_id = int(fields["chapter_id"])
    conn = get_conn()
    try:
        cur = conn.cursor()
        chapter = cur.execute(
            "SELECT id, title FROM lms_master_chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
        if not chapter:
            flash("Selected chapter was not found.", "danger")
            return redirect(url_for("exams.manage_questions"))

        cur.execute(
            """
                INSERT INTO lms_question_bank (
                    chapter_id,
                    question_text,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    correct_option,
                    question_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'MCQ')
            """,
            (
                chapter_id,
                fields["question_text"],
                fields["option_a"],
                fields["option_b"],
                fields["option_c"],
                fields["option_d"],
                fields["correct_option"],
            ),
        )
        question_id = cur.lastrowid

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="create",
            module_name="lms_question_bank",
            record_id=question_id,
            description=f"Created question for chapter: {chapter['title']}",
            conn=conn,
        )
        conn.commit()
        flash("Question added successfully.", "success")
    finally:
        conn.close()

    return redirect(url_for("exams.view_questions"))


@exams_bp.route("/lms_admin/questions/update/<int:question_id>", methods=["POST"])
@lms_content_manager_required
def update_question(question_id):
    fields = _question_form_fields()
    error = _validate_question_fields(fields)
    if error:
        flash(error, "danger")
        return redirect(url_for("exams.edit_question", question_id=question_id))

    chapter_id = int(fields["chapter_id"])
    conn = get_conn()
    try:
        cur = conn.cursor()
        question = cur.execute(
            "SELECT id FROM lms_question_bank WHERE id = ?",
            (question_id,),
        ).fetchone()
        if not question:
            flash("Question not found.", "warning")
            return redirect(url_for("exams.view_questions"))

        chapter = cur.execute(
            "SELECT id, title FROM lms_master_chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
        if not chapter:
            flash("Selected chapter was not found.", "danger")
            return redirect(url_for("exams.edit_question", question_id=question_id))

        cur.execute(
            """
                UPDATE lms_question_bank
                SET
                    chapter_id = ?,
                    question_text = ?,
                    option_a = ?,
                    option_b = ?,
                    option_c = ?,
                    option_d = ?,
                    correct_option = ?,
                    question_type = 'MCQ'
                WHERE id = ?
            """,
            (
                chapter_id,
                fields["question_text"],
                fields["option_a"],
                fields["option_b"],
                fields["option_c"],
                fields["option_d"],
                fields["correct_option"],
                question_id,
            ),
        )

        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="update",
            module_name="lms_question_bank",
            record_id=question_id,
            description=f"Updated question for chapter: {chapter['title']}",
            conn=conn,
        )
        conn.commit()
        flash("Question updated successfully.", "success")
    finally:
        conn.close()

    return redirect(url_for("exams.view_questions"))


@exams_bp.route("/lms_admin/questions/delete/<int:question_id>", methods=["GET", "POST"])
@lms_content_manager_required
def delete_question(question_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        question = cur.execute(
            "SELECT id, question_text FROM lms_question_bank WHERE id = ?",
            (question_id,),
        ).fetchone()
        if not question:
            flash("Question not found.", "warning")
            return redirect(url_for("exams.view_questions"))

        cur.execute("DELETE FROM lms_question_bank WHERE id = ?", (question_id,))
        log_activity(
            user_id=session.get("user_id"),
            branch_id=session.get("branch_id"),
            action_type="delete",
            module_name="lms_question_bank",
            record_id=question_id,
            description=f"Deleted question: {question['question_text'][:80]}",
            conn=conn,
        )
        conn.commit()
        flash("Question deleted successfully.", "success")
    finally:
        conn.close()

    return redirect(url_for("exams.view_questions"))


@exams_bp.route("/student/mock/setup/<int:chapter_id>", methods=["GET"])
def chapter_mock_intro(chapter_id):
    auth_redirect = _student_required_redirect()
    if auth_redirect:
        return auth_redirect

    conn = get_conn()
    try:
        cur = conn.cursor()
        chapter = cur.execute(
            "SELECT id, title FROM lms_master_chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
        if not chapter:
            flash("Chapter mock test was not found.", "warning")
            return redirect(url_for("students.dashboard"))

        questions = cur.execute(
            """
                SELECT
                    id,
                    chapter_id,
                    question_text,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    question_type
                FROM lms_question_bank
                WHERE chapter_id = ?
            """,
            (chapter_id,),
        ).fetchall()
    finally:
        conn.close()

    questions = list(questions)
    if not questions:
        flash("No mock test questions are available for this chapter yet.", "warning")
        return redirect(url_for("students.dashboard"))

    random.shuffle(questions)
    selected_questions = questions[:20]
    selected_ids = [question["id"] for question in selected_questions]

    conn = get_conn()
    try:
        answer_rows = conn.execute(
            f"""
                SELECT id, correct_option
                FROM lms_question_bank
                WHERE id IN ({','.join('?' for _ in selected_ids)})
            """,
            selected_ids,
        ).fetchall()
    finally:
        conn.close()

    session["chapter_mock_answers"] = {
        "chapter_id": chapter_id,
        "question_ids": selected_ids,
        "answers": {str(row["id"]): row["correct_option"] for row in answer_rows},
    }
    session.modified = True

    return render_template(
        "exams/take_exam.html",
        chapter=chapter,
        questions=selected_questions,
        question_count=len(selected_questions),
        exam_duration_seconds=20 * 60,
    )


@exams_bp.route("/student/mock/submit", methods=["POST"])
def submit_chapter_mock():
    auth_redirect = _student_required_redirect()
    if auth_redirect:
        return auth_redirect

    mock = session.get("chapter_mock_answers") or {}
    answer_key = mock.get("answers") or {}
    question_ids = mock.get("question_ids") or []
    chapter_id = mock.get("chapter_id")

    if not answer_key or not question_ids or not chapter_id:
        flash("Your mock test session has expired. Please start the mock test again.", "warning")
        return redirect(url_for("students.dashboard"))

    submitted_answers = {
        str(question_id): request.form.get(f"answer_{question_id}", "").strip().upper()
        for question_id in question_ids
    }
    correct_count = sum(
        1
        for question_id, correct_option in answer_key.items()
        if submitted_answers.get(question_id) == correct_option
    )
    total_questions = len(question_ids)
    score_percent = round((correct_count / total_questions) * 100, 1) if total_questions else 0

    conn = get_conn()
    try:
        chapter = conn.execute(
            "SELECT id, title FROM lms_master_chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    finally:
        conn.close()

    session.pop("chapter_mock_answers", None)
    session.modified = True

    return render_template(
        "exams/mock_result.html",
        chapter=chapter,
        correct_count=correct_count,
        total_questions=total_questions,
        score_percent=score_percent,
    )
