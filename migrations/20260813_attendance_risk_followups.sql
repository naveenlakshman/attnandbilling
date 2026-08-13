-- Additive fields for tenant-safe, append-only attendance follow-up events.
-- Apply through the normal migration process where startup schema upgrades are disabled.
ALTER TABLE attendance_followups ADD COLUMN institute_id BIGINT NULL;
ALTER TABLE attendance_followups ADD COLUMN contact_channel VARCHAR(30) NULL;
ALTER TABLE attendance_followups ADD COLUMN contact_person VARCHAR(100) NULL;
ALTER TABLE attendance_followups ADD COLUMN next_followup_date DATE NULL;

UPDATE attendance_followups af
JOIN students s ON s.id = af.student_id
SET af.institute_id = s.institute_id
WHERE af.institute_id IS NULL;

CREATE INDEX idx_attendance_followups_tenant_student_batch_date
    ON attendance_followups (institute_id, student_id, batch_id, last_followup_date);
