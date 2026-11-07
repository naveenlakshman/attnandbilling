-- Phase 3 follow-up: make courses tenant-owned.
-- Existing single-institute rows are assigned to the legacy/default institute.

ALTER TABLE courses
    ADD COLUMN institute_id BIGINT NOT NULL DEFAULT 1 AFTER id;

CREATE INDEX idx_courses_institute_public
    ON courses (institute_id, is_active, show_on_website);

