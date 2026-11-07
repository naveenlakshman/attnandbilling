"""Additive accuracy schema. MySQL applies migrations explicitly, before code."""

SCHEMA = '''
CREATE TABLE IF NOT EXISTS course_admissions (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, student_id BIGINT NOT NULL,
 course_id BIGINT NOT NULL, course_version VARCHAR(100) NOT NULL, course_snapshot TEXT NOT NULL,
 admission_date VARCHAR(10) NOT NULL, origin_branch_id BIGINT NULL, original_creator_id BIGINT NULL,
 source VARCHAR(30) NOT NULL, source_reference VARCHAR(255) NULL, imported_by BIGINT NULL,
 status VARCHAR(20) NOT NULL, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS admission_modules (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, admission_id VARCHAR(32) NOT NULL,
 module_name VARCHAR(150) NOT NULL, program_id BIGINT NULL,
 UNIQUE(institute_id,admission_id,module_name)
);
CREATE TABLE IF NOT EXISTS invoice_item_admissions (
 item_id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL, admission_id VARCHAR(32) NOT NULL,
 effective_date VARCHAR(10) NOT NULL, linked_by BIGINT NOT NULL, linked_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS training_assignments (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, admission_id VARCHAR(32) NOT NULL,
 module_id VARCHAR(32) NOT NULL, batch_id BIGINT NOT NULL, branch_id BIGINT NOT NULL,
 trainer_id BIGINT NULL, start_date VARCHAR(10) NOT NULL, end_date VARCHAR(10) NULL,
 previous_assignment_id VARCHAR(32) NULL UNIQUE, reason TEXT NOT NULL, created_by BIGINT NOT NULL,
 recorded_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_payments (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, student_id BIGINT NOT NULL,
 amount_paise BIGINT NOT NULL, collection_branch_id BIGINT NULL, payment_channel VARCHAR(30) NOT NULL,
 payment_method VARCHAR(30) NOT NULL, payment_reference VARCHAR(150) NULL,
 payment_date VARCHAR(10) NOT NULL, payment_timestamp VARCHAR(40) NULL, date_source VARCHAR(30) NOT NULL,
 posted_at VARCHAR(40) NOT NULL, created_by BIGINT NOT NULL, request_key VARCHAR(100) NOT NULL,
 fingerprint VARCHAR(64) NOT NULL,
 UNIQUE(institute_id,request_key), UNIQUE(institute_id,payment_channel,payment_reference)
);
CREATE TABLE IF NOT EXISTS receipt_details (
 receipt_id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL, payment_id VARCHAR(32) NOT NULL,
 original_json TEXT NOT NULL, recorded_at VARCHAR(40) NOT NULL, allocation_date VARCHAR(10) NOT NULL
);
CREATE TABLE IF NOT EXISTS allocation_requests (
 institute_id BIGINT NOT NULL, request_key VARCHAR(100) NOT NULL,
 fingerprint VARCHAR(64) NOT NULL, receipt_id BIGINT NOT NULL,
 PRIMARY KEY(institute_id,request_key)
);
CREATE TABLE IF NOT EXISTS advance_returns (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, payment_id VARCHAR(32) NOT NULL,
 amount_paise BIGINT NOT NULL, effective_date VARCHAR(10) NOT NULL, recorded_at VARCHAR(40) NOT NULL,
 created_by BIGINT NOT NULL, reason TEXT NOT NULL, request_key VARCHAR(100) NOT NULL,
 UNIQUE(institute_id,request_key)
);
CREATE TABLE IF NOT EXISTS cash_event_details (
 event_id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, branch_id BIGINT NULL,
 channel VARCHAR(30) NOT NULL, payment_reference VARCHAR(150) NULL,
 recorded_at VARCHAR(40) NOT NULL, created_by BIGINT NOT NULL,
 UNIQUE(institute_id,channel,payment_reference)
);
CREATE TABLE IF NOT EXISTS invoice_postings (
 invoice_id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL, snapshot_json TEXT NOT NULL,
 captured_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS finance_adjustments (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, invoice_id BIGINT NOT NULL,
 kind VARCHAR(30) NOT NULL, amount_paise BIGINT NOT NULL, charge_delta BIGINT NOT NULL,
 writeoff_delta BIGINT NOT NULL, cash_delta BIGINT NOT NULL,
 effective_date VARCHAR(10) NOT NULL, recorded_at VARCHAR(40) NOT NULL, created_by BIGINT NOT NULL,
 reason TEXT NOT NULL, receipt_id BIGINT NULL, writeoff_id BIGINT NULL,
 reverse_of VARCHAR(32) NULL UNIQUE, request_key VARCHAR(100) NOT NULL,
 UNIQUE(institute_id,request_key), UNIQUE(institute_id,writeoff_id)
);
CREATE TABLE IF NOT EXISTS accuracy_audit (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, actor_id BIGINT NOT NULL,
 entity_type VARCHAR(40) NOT NULL, entity_id VARCHAR(100) NOT NULL, before_json TEXT NOT NULL,
 after_json TEXT NOT NULL, reason TEXT NOT NULL, effective_date VARCHAR(10) NOT NULL,
 recorded_at VARCHAR(40) NOT NULL, event_order BIGINT NOT NULL,
 UNIQUE(institute_id,entity_type,entity_id,event_order)
);
'''


def init_sqlite_schema(conn):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            conn.execute(statement)
    for name,table,columns in (
        ('idx_admissions_cohort','course_admissions','institute_id,admission_date,origin_branch_id'),
        ('idx_item_admission','invoice_item_admissions','institute_id,admission_id'),
        ('idx_training_period','training_assignments','institute_id,start_date,end_date'),
        ('idx_collection_date','collection_payments','institute_id,payment_date,collection_branch_id'),
        ('idx_adjustments_invoice','finance_adjustments','institute_id,invoice_id,effective_date'),
        ('idx_accuracy_history','accuracy_audit','institute_id,entity_type,entity_id,recorded_at'),
    ):
        conn.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})')
