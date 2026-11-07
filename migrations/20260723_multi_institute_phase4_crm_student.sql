-- Phase 4: CRM and Student Identity multi-tenant isolation
-- Additive and safe to re-run.

-- 1. LEADS
SET @p4_lead_inst_col = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads' AND COLUMN_NAME = 'institute_id'),
    'SELECT 1',
    'ALTER TABLE leads ADD COLUMN institute_id BIGINT NULL AFTER id'
);
PREPARE p4_stmt FROM @p4_lead_inst_col; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

UPDATE leads SET institute_id = 1 WHERE institute_id IS NULL;

SET @p4_lead_inst_notnull = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads' AND COLUMN_NAME = 'institute_id' AND IS_NULLABLE = 'YES'),
    'ALTER TABLE leads MODIFY institute_id BIGINT NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_lead_inst_notnull; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_lead_fk = IF(
    EXISTS(SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'leads' AND CONSTRAINT_NAME = 'fk_leads_institute'),
    'SELECT 1',
    'ALTER TABLE leads ADD CONSTRAINT fk_leads_institute FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE RESTRICT'
);
PREPARE p4_stmt FROM @p4_lead_fk; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;


-- 2. FOLLOWUPS
SET @p4_fol_inst_col = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'followups' AND COLUMN_NAME = 'institute_id'),
    'SELECT 1',
    'ALTER TABLE followups ADD COLUMN institute_id BIGINT NULL AFTER id'
);
PREPARE p4_stmt FROM @p4_fol_inst_col; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

UPDATE followups SET institute_id = 1 WHERE institute_id IS NULL;

SET @p4_fol_inst_notnull = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'followups' AND COLUMN_NAME = 'institute_id' AND IS_NULLABLE = 'YES'),
    'ALTER TABLE followups MODIFY institute_id BIGINT NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_fol_inst_notnull; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_fol_fk = IF(
    EXISTS(SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'followups' AND CONSTRAINT_NAME = 'fk_followups_institute'),
    'SELECT 1',
    'ALTER TABLE followups ADD CONSTRAINT fk_followups_institute FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE RESTRICT'
);
PREPARE p4_stmt FROM @p4_fol_fk; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;


-- 3. STUDENTS
SET @p4_stu_inst_col = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND COLUMN_NAME = 'institute_id'),
    'SELECT 1',
    'ALTER TABLE students ADD COLUMN institute_id BIGINT NULL AFTER id'
);
PREPARE p4_stmt FROM @p4_stu_inst_col; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

UPDATE students SET institute_id = 1 WHERE institute_id IS NULL;

SET @p4_stu_inst_notnull = IF(
    EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND COLUMN_NAME = 'institute_id' AND IS_NULLABLE = 'YES'),
    'ALTER TABLE students MODIFY institute_id BIGINT NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_stu_inst_notnull; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_stu_fk = IF(
    EXISTS(SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND CONSTRAINT_NAME = 'fk_students_institute'),
    'SELECT 1',
    'ALTER TABLE students ADD CONSTRAINT fk_students_institute FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE RESTRICT'
);
PREPARE p4_stmt FROM @p4_stu_fk; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

-- Replace standalone student_code unique index with (institute_id, student_code) unique composite index
SET @p4_stu_old_uq = IF(
    EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND INDEX_NAME = 'student_code' AND NON_UNIQUE = 0),
    'ALTER TABLE students DROP INDEX student_code',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_stu_old_uq; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_stu_code_uq = IF(
    EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND INDEX_NAME = 'uq_students_institute_code'),
    'SELECT 1',
    'CREATE UNIQUE INDEX uq_students_institute_code ON students(institute_id, student_code)'
);
PREPARE p4_stmt FROM @p4_stu_code_uq; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;


-- 4. STUDENT UPLOADED DOCUMENTS
SET @p4_doc_inst_col = IF(
    EXISTS(SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'student_uploaded_documents')
    AND NOT EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'student_uploaded_documents' AND COLUMN_NAME = 'institute_id'),
    'ALTER TABLE student_uploaded_documents ADD COLUMN institute_id BIGINT NOT NULL DEFAULT 1 AFTER id',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_doc_inst_col; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

-- 5. STUDENT PROFILE UPDATE REQUESTS
SET @p4_pur_inst_col = IF(
    EXISTS(SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'student_profile_update_requests')
    AND NOT EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'student_profile_update_requests' AND COLUMN_NAME = 'institute_id'),
    'ALTER TABLE student_profile_update_requests ADD COLUMN institute_id BIGINT NOT NULL DEFAULT 1 AFTER id',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_pur_inst_col; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

-- 6. STUDENT NOTES
SET @p4_not_inst_col = IF(
    EXISTS(SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'student_notes')
    AND NOT EXISTS(SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'student_notes' AND COLUMN_NAME = 'institute_id'),
    'ALTER TABLE student_notes ADD COLUMN institute_id BIGINT NOT NULL DEFAULT 1 AFTER id',
    'SELECT 1'
);
PREPARE p4_stmt FROM @p4_not_inst_col; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;


-- 7. INDEXES FOR TENANT LOOKUPS
SET @p4_idx1 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads' AND INDEX_NAME = 'idx_leads_inst_status'), 'SELECT 1', 'CREATE INDEX idx_leads_inst_status ON leads(institute_id, status)');
PREPARE p4_stmt FROM @p4_idx1; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_idx2 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads' AND INDEX_NAME = 'idx_leads_inst_branch'), 'SELECT 1', 'CREATE INDEX idx_leads_inst_branch ON leads(institute_id, branch_id)');
PREPARE p4_stmt FROM @p4_idx2; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_idx3 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads' AND INDEX_NAME = 'idx_leads_inst_phone'), 'SELECT 1', 'CREATE INDEX idx_leads_inst_phone ON leads(institute_id, phone)');
PREPARE p4_stmt FROM @p4_idx3; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_idx4 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND INDEX_NAME = 'idx_students_inst_status'), 'SELECT 1', 'CREATE INDEX idx_students_inst_status ON students(institute_id, status)');
PREPARE p4_stmt FROM @p4_idx4; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_idx5 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND INDEX_NAME = 'idx_students_inst_branch'), 'SELECT 1', 'CREATE INDEX idx_students_inst_branch ON students(institute_id, branch_id)');
PREPARE p4_stmt FROM @p4_idx5; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_idx6 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND INDEX_NAME = 'idx_students_inst_phone'), 'SELECT 1', 'CREATE INDEX idx_students_inst_phone ON students(institute_id, phone)');
PREPARE p4_stmt FROM @p4_idx6; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;

SET @p4_idx7 = IF(EXISTS(SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'followups' AND INDEX_NAME = 'idx_followups_inst'), 'SELECT 1', 'CREATE INDEX idx_followups_inst ON followups(institute_id)');
PREPARE p4_stmt FROM @p4_idx7; EXECUTE p4_stmt; DEALLOCATE PREPARE p4_stmt;
