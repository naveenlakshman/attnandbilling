-- Repair legacy LMS submission tenant ownership from the authoritative student row.
-- Idempotent: rerunning updates only missing or mismatched institute IDs.

UPDATE lms_assignment_submissions AS submission
JOIN students AS student ON student.id = submission.student_id
SET submission.institute_id = student.institute_id
WHERE student.institute_id IS NOT NULL
  AND (
      submission.institute_id IS NULL
      OR submission.institute_id <> student.institute_id
  );
