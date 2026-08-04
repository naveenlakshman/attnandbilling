"""
Test script to verify course-aware and tenant-isolated LMS Assignment Review Queue filtering.
"""
import sqlite3
import sys

def test_course_aware_review_queue():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create minimal schema
    cur.execute("CREATE TABLE branches (id INTEGER PRIMARY KEY, institute_id INTEGER, branch_name TEXT)")
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, role TEXT, is_active INTEGER, institute_id INTEGER, branch_id INTEGER, can_view_all_branches INTEGER)")
    cur.execute("CREATE TABLE courses (id INTEGER PRIMARY KEY, course_name TEXT)")
    cur.execute("CREATE TABLE batches (id INTEGER PRIMARY KEY, batch_name TEXT, course_id INTEGER, branch_id INTEGER, trainer_id INTEGER, status TEXT)")
    cur.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, full_name TEXT, student_code TEXT, branch_id INTEGER, institute_id INTEGER)")
    cur.execute("CREATE TABLE student_batches (id INTEGER PRIMARY KEY, student_id INTEGER, batch_id INTEGER, status TEXT)")
    cur.execute("CREATE TABLE lms_programs (id INTEGER PRIMARY KEY, course_id INTEGER, program_name TEXT, is_published INTEGER, is_active INTEGER, is_deleted INTEGER, institute_id INTEGER)")
    cur.execute("CREATE TABLE lms_course_program_map (id INTEGER PRIMARY KEY, course_id INTEGER, program_id INTEGER)")
    cur.execute("CREATE TABLE lms_master_chapters (id INTEGER PRIMARY KEY, title TEXT)")
    cur.execute("CREATE TABLE lms_master_topics (id INTEGER PRIMARY KEY, master_chapter_id INTEGER, title TEXT)")
    cur.execute("CREATE TABLE lms_program_chapters (id INTEGER PRIMARY KEY, program_id INTEGER, master_chapter_id INTEGER, is_visible INTEGER)")
    cur.execute("CREATE TABLE lms_assignments (id INTEGER PRIMARY KEY, master_topic_id INTEGER, title TEXT)")
    cur.execute("CREATE TABLE lms_assignment_submissions (id INTEGER PRIMARY KEY, assignment_id INTEGER, student_id INTEGER, is_latest INTEGER, review_status TEXT, submitted_at TEXT, institute_id INTEGER, original_filename TEXT, feedback TEXT, rejection_reason TEXT)")

    # Insert test data:
    # Tenant 1
    cur.execute("INSERT INTO branches VALUES (1, 1, 'Main Branch')")
    cur.execute("INSERT INTO users VALUES (1, 'Naveen Lakshman', 'staff', 1, 1, 1, 0)")
    cur.execute("INSERT INTO users VALUES (2, 'Meghana M', 'staff', 1, 1, 1, 0)")

    # Courses & Batches
    cur.execute("INSERT INTO courses VALUES (10, 'CCBA Course')")
    cur.execute("INSERT INTO courses VALUES (20, 'Python Course')")

    cur.execute("INSERT INTO batches VALUES (100, 'CCBA Batch', 10, 1, 2, 'active')") # Meghana
    cur.execute("INSERT INTO batches VALUES (200, 'Afternoon Python Batch', 20, 1, 1, 'active')") # Naveen

    # Programs & Mapping
    cur.execute("INSERT INTO lms_programs VALUES (1, 10, 'CCBA Program', 1, 1, 0, 1)")
    cur.execute("INSERT INTO lms_programs VALUES (2, 20, 'Python Program', 1, 1, 0, 1)")

    # Master Chapters & Topics
    cur.execute("INSERT INTO lms_master_chapters VALUES (1, 'Chapter 3: Microsoft Word')")
    cur.execute("INSERT INTO lms_program_chapters VALUES (1, 1, 1, 1)") # CCBA Program -> Ch 3

    cur.execute("INSERT INTO lms_master_chapters VALUES (2, 'Chapter 1: Python Basics')")
    cur.execute("INSERT INTO lms_program_chapters VALUES (2, 2, 2, 1)") # Python Program -> Ch 1

    # Assignments
    cur.execute("INSERT INTO lms_master_topics VALUES (1, 1, 'Working with Lists')")
    cur.execute("INSERT INTO lms_assignments VALUES (1, 1, 'Working with Lists Assignment')")

    cur.execute("INSERT INTO lms_master_topics VALUES (2, 2, 'Variables & Types')")
    cur.execute("INSERT INTO lms_assignments VALUES (2, 2, 'Python Variables Assignment')")

    # Student Lanika M enrolled in BOTH batches
    cur.execute("INSERT INTO students VALUES (500, 'Lanika M', '1516707', 1, 1)")
    cur.execute("INSERT INTO student_batches VALUES (1, 500, 100, 'active')") # CCBA
    cur.execute("INSERT INTO student_batches VALUES (2, 500, 200, 'active')") # Python

    # Lanika submits 1 CCBA assignment and 1 Python assignment
    cur.execute("INSERT INTO lms_assignment_submissions VALUES (1, 1, 500, 1, 'submitted', '2026-08-04 10:00:00', 1, 'lists.docx', NULL, NULL)")
    cur.execute("INSERT INTO lms_assignment_submissions VALUES (2, 2, 500, 1, 'submitted', '2026-08-04 11:00:00', 1, 'vars.py', NULL, NULL)")

    current_inst = 1

    base_sql = f"""
        SELECT s.id, s.assignment_id, s.student_id,
               a.title AS assignment_title, mt.title AS topic_title,
               mc.title AS chapter_title, st.full_name AS student_name,
               (SELECT GROUP_CONCAT(DISTINCT b_names.batch_name)
                FROM student_batches sb_names
                JOIN batches b_names ON b_names.id = sb_names.batch_id
                WHERE sb_names.student_id = s.student_id
                  AND sb_names.status = 'active'
                  AND LOWER(COALESCE(b_names.status, '')) = 'active'
                  AND (
                      EXISTS (
                          SELECT 1 FROM lms_program_chapters pc_m
                          JOIN lms_programs lp_m ON lp_m.id = pc_m.program_id
                          LEFT JOIN lms_course_program_map cpm_m ON cpm_m.program_id = lp_m.id
                          WHERE pc_m.master_chapter_id = mt.master_chapter_id
                            AND pc_m.is_visible = 1
                            AND lp_m.is_active = 1
                            AND lp_m.is_deleted = 0
                            AND lp_m.institute_id = {current_inst}
                            AND (b_names.course_id = lp_m.course_id OR b_names.course_id = cpm_m.course_id)
                      )
                      OR NOT EXISTS (
                          SELECT 1 FROM lms_program_chapters pc_chk
                          JOIN lms_programs lp_chk ON lp_chk.id = pc_chk.program_id
                          LEFT JOIN lms_course_program_map cpm_chk ON cpm_chk.program_id = lp_chk.id
                          WHERE pc_chk.master_chapter_id = mt.master_chapter_id
                            AND pc_chk.is_visible = 1
                            AND lp_chk.is_active = 1
                            AND lp_chk.is_deleted = 0
                            AND lp_chk.institute_id = {current_inst}
                            AND (lp_chk.course_id IS NOT NULL OR cpm_chk.course_id IS NOT NULL)
                      )
                  )) AS batch_names,
               (SELECT GROUP_CONCAT(DISTINCT u_names.full_name)
                FROM student_batches sb_names
                JOIN batches b_names ON b_names.id = sb_names.batch_id
                JOIN users u_names ON u_names.id = b_names.trainer_id
                WHERE sb_names.student_id = s.student_id
                  AND sb_names.status = 'active'
                  AND LOWER(COALESCE(b_names.status, '')) = 'active'
                  AND (
                      EXISTS (
                          SELECT 1 FROM lms_program_chapters pc_m
                          JOIN lms_programs lp_m ON lp_m.id = pc_m.program_id
                          LEFT JOIN lms_course_program_map cpm_m ON cpm_m.program_id = lp_m.id
                          WHERE pc_m.master_chapter_id = mt.master_chapter_id
                            AND pc_m.is_visible = 1
                            AND lp_m.is_active = 1
                            AND lp_m.is_deleted = 0
                            AND lp_m.institute_id = {current_inst}
                            AND (b_names.course_id = lp_m.course_id OR b_names.course_id = cpm_m.course_id)
                      )
                      OR NOT EXISTS (
                          SELECT 1 FROM lms_program_chapters pc_chk
                          JOIN lms_programs lp_chk ON lp_chk.id = pc_chk.program_id
                          LEFT JOIN lms_course_program_map cpm_chk ON cpm_chk.program_id = lp_chk.id
                          WHERE pc_chk.master_chapter_id = mt.master_chapter_id
                            AND pc_chk.is_visible = 1
                            AND lp_chk.is_active = 1
                            AND lp_chk.is_deleted = 0
                            AND lp_chk.institute_id = {current_inst}
                            AND (lp_chk.course_id IS NOT NULL OR cpm_chk.course_id IS NOT NULL)
                      )
                  )) AS trainer_names
        FROM lms_assignment_submissions s
        JOIN lms_assignments a ON a.id = s.assignment_id
        JOIN lms_master_topics mt ON mt.id = a.master_topic_id
        JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
        JOIN students st ON st.id = s.student_id
    """

    # Test 1: Query for Naveen (trainer_id = 1)
    trainer_filter_sql = base_sql + """
        WHERE EXISTS (
            SELECT 1 FROM student_batches sb_scope
            JOIN batches b_scope ON b_scope.id = sb_scope.batch_id
            WHERE sb_scope.student_id = s.student_id
              AND sb_scope.status = 'active'
              AND LOWER(COALESCE(b_scope.status, '')) = 'active'
              AND b_scope.trainer_id = ?
              AND (
                  EXISTS (
                      SELECT 1 FROM lms_program_chapters pc_scope
                      JOIN lms_programs lp_scope ON lp_scope.id = pc_scope.program_id
                      LEFT JOIN lms_course_program_map cpm_scope ON cpm_scope.program_id = lp_scope.id
                      WHERE pc_scope.master_chapter_id = mt.master_chapter_id
                        AND pc_scope.is_visible = 1
                        AND lp_scope.is_active = 1
                        AND lp_scope.is_deleted = 0
                        AND lp_scope.institute_id = ?
                        AND (b_scope.course_id = lp_scope.course_id OR b_scope.course_id = cpm_scope.course_id)
                  )
                  OR NOT EXISTS (
                      SELECT 1 FROM lms_program_chapters pc_chk
                      JOIN lms_programs lp_chk ON lp_chk.id = pc_chk.program_id
                      LEFT JOIN lms_course_program_map cpm_chk ON cpm_chk.program_id = lp_chk.id
                      WHERE pc_chk.master_chapter_id = mt.master_chapter_id
                        AND pc_chk.is_visible = 1
                        AND lp_chk.is_active = 1
                        AND lp_chk.is_deleted = 0
                        AND lp_chk.institute_id = ?
                        AND (lp_chk.course_id IS NOT NULL OR cpm_chk.course_id IS NOT NULL)
                  )
              )
        )
    """

    rows_naveen = cur.execute(trainer_filter_sql, (1, current_inst, current_inst)).fetchall()
    assert len(rows_naveen) == 1, f"Expected 1 submission for Naveen, got {len(rows_naveen)}"
    assert rows_naveen[0]['assignment_title'] == 'Python Variables Assignment'
    assert rows_naveen[0]['batch_names'] == 'Afternoon Python Batch'
    assert rows_naveen[0]['trainer_names'] == 'Naveen Lakshman'
    print("PASS: Naveen only sees Python assignment with Python batch and Naveen Lakshman metadata.")

    # Test 2: Query for Meghana (trainer_id = 2)
    rows_meghana = cur.execute(trainer_filter_sql, (2, current_inst, current_inst)).fetchall()
    assert len(rows_meghana) == 1, f"Expected 1 submission for Meghana, got {len(rows_meghana)}"
    assert rows_meghana[0]['assignment_title'] == 'Working with Lists Assignment'
    assert rows_meghana[0]['batch_names'] == 'CCBA Batch'
    assert rows_meghana[0]['trainer_names'] == 'Meghana M'
    print("PASS: Meghana only sees CCBA assignment with CCBA batch and Meghana M metadata.")

    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_course_aware_review_queue()
