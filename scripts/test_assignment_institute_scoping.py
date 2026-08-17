"""Regression checks for LMS assignment institute isolation and legacy backfills."""

import sqlite3


def main():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE lms_master_chapters (id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL);
        CREATE TABLE lms_master_topics (id INTEGER PRIMARY KEY, master_chapter_id INTEGER NOT NULL);
        CREATE TABLE lms_assignments (
            id INTEGER PRIMARY KEY,
            master_topic_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            institute_id INTEGER DEFAULT 1
        );
        CREATE TABLE students (id INTEGER PRIMARY KEY, institute_id INTEGER NOT NULL);
        CREATE TABLE lms_assignment_submissions (
            id INTEGER PRIMARY KEY,
            assignment_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            institute_id INTEGER,
            is_latest INTEGER NOT NULL DEFAULT 1
        );

        INSERT INTO lms_master_chapters VALUES (1, 1), (2, 2);
        INSERT INTO lms_master_topics VALUES (1, 1), (2, 2);
        INSERT INTO lms_assignments VALUES (1, 1, 'Institute 1 assignment', 1);
        INSERT INTO lms_assignments VALUES (2, 2, 'Legacy Institute 2 assignment', 1);
        INSERT INTO students VALUES (10, 1), (20, 2);
        INSERT INTO lms_assignment_submissions VALUES (1, 1, 10, 1, 1);
        INSERT INTO lms_assignment_submissions VALUES (2, 2, 20, 1, 1);
        INSERT INTO lms_assignment_submissions VALUES (3, 2, 20, NULL, 1);
        """
    )

    conn.execute(
        """
        UPDATE lms_assignments
        SET institute_id = COALESCE((
            SELECT mc.institute_id
            FROM lms_master_topics mt
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
            WHERE mt.id = lms_assignments.master_topic_id
        ), 1)
        WHERE master_topic_id IS NOT NULL AND (institute_id IS NULL OR institute_id = 1)
        """
    )
    conn.execute(
        """
        UPDATE lms_assignment_submissions
        SET institute_id = COALESCE((
            SELECT institute_id FROM students
            WHERE students.id = lms_assignment_submissions.student_id
        ), 1)
        WHERE student_id IS NOT NULL AND (institute_id IS NULL OR institute_id = 1)
        """
    )

    def assignments_for(institute_id):
        return conn.execute(
            """
            SELECT a.id, COUNT(s.id) AS submission_count
            FROM lms_assignments a
            JOIN lms_master_topics mt ON mt.id = a.master_topic_id
            JOIN lms_master_chapters mc ON mc.id = mt.master_chapter_id
            LEFT JOIN lms_assignment_submissions s
              ON s.assignment_id = a.id
             AND s.is_latest = 1
             AND (s.institute_id = ? OR s.institute_id IS NULL)
             AND EXISTS (
                 SELECT 1 FROM students st
                 WHERE st.id = s.student_id AND st.institute_id = ?
             )
            WHERE a.institute_id = ? AND mc.institute_id = ?
            GROUP BY a.id
            ORDER BY a.id
            """,
            (institute_id, institute_id, institute_id, institute_id),
        ).fetchall()

    institute_1 = assignments_for(1)
    institute_2 = assignments_for(2)
    assert [(row["id"], row["submission_count"]) for row in institute_1] == [(1, 1)]
    assert [(row["id"], row["submission_count"]) for row in institute_2] == [(2, 2)]

    conn.execute(
        "INSERT INTO lms_assignments (id, master_topic_id, title, institute_id) VALUES (?, ?, ?, ?)",
        (3, 2, "New Institute 2 assignment", 2),
    )
    assert [row["id"] for row in assignments_for(2)] == [2, 3]
    assert [row["id"] for row in assignments_for(1)] == [1]
    print("PASS: Institute 2 legacy and new assignments are visible only in Institute 2.")


if __name__ == "__main__":
    main()
