-- Requires earlier multi-institute finance migrations. Apply before code.
-- Additive only: no historical UPDATE, DELETE, admission generation or branch recovery.

CREATE TABLE IF NOT EXISTS course_admissions (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, student_id BIGINT NOT NULL,
 course_id BIGINT NOT NULL, course_version VARCHAR(100) NOT NULL, course_snapshot LONGTEXT NOT NULL,
 admission_date VARCHAR(10) NOT NULL, origin_branch_id BIGINT NULL, original_creator_id BIGINT NULL,
 source VARCHAR(30) NOT NULL, source_reference VARCHAR(255) NULL, imported_by BIGINT NULL,
 status VARCHAR(20) NOT NULL, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL
,
 KEY idx_admissions_cohort (institute_id,admission_date,origin_branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS admission_modules (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, admission_id VARCHAR(32) NOT NULL,
 module_name VARCHAR(150) NOT NULL, program_id BIGINT NULL,
 UNIQUE(institute_id,admission_id,module_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS invoice_item_admissions (
 item_id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL, admission_id VARCHAR(32) NOT NULL,
 effective_date VARCHAR(10) NOT NULL, linked_by BIGINT NOT NULL, linked_at VARCHAR(40) NOT NULL
,
 KEY idx_item_admission (institute_id,admission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS training_assignments (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, admission_id VARCHAR(32) NOT NULL,
 module_id VARCHAR(32) NOT NULL, batch_id BIGINT NOT NULL, branch_id BIGINT NOT NULL,
 trainer_id BIGINT NULL, start_date VARCHAR(10) NOT NULL, end_date VARCHAR(10) NULL,
 previous_assignment_id VARCHAR(32) NULL UNIQUE, reason TEXT NOT NULL, created_by BIGINT NOT NULL,
 recorded_at VARCHAR(40) NOT NULL
,
 KEY idx_training_period (institute_id,start_date,end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS collection_payments (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, student_id BIGINT NOT NULL,
 amount_paise BIGINT NOT NULL, collection_branch_id BIGINT NULL, payment_channel VARCHAR(30) NOT NULL,
 payment_method VARCHAR(30) NOT NULL, payment_reference VARCHAR(150) NULL,
 payment_date VARCHAR(10) NOT NULL, payment_timestamp VARCHAR(40) NULL, date_source VARCHAR(30) NOT NULL,
 posted_at VARCHAR(40) NOT NULL, created_by BIGINT NOT NULL, request_key VARCHAR(100) NOT NULL,
 fingerprint VARCHAR(64) NOT NULL,
 UNIQUE(institute_id,request_key), UNIQUE(institute_id,payment_channel,payment_reference)
,
 KEY idx_collection_date (institute_id,payment_date,collection_branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS receipt_details (
 receipt_id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL, payment_id VARCHAR(32) NOT NULL,
 original_json LONGTEXT NOT NULL, recorded_at VARCHAR(40) NOT NULL, allocation_date VARCHAR(10) NOT NULL
,
 KEY idx_receipt_payment (institute_id,payment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS allocation_requests (
 institute_id BIGINT NOT NULL, request_key VARCHAR(100) NOT NULL,
 fingerprint VARCHAR(64) NOT NULL, receipt_id BIGINT NOT NULL,
 PRIMARY KEY(institute_id,request_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS advance_returns (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, payment_id VARCHAR(32) NOT NULL,
 amount_paise BIGINT NOT NULL, effective_date VARCHAR(10) NOT NULL, recorded_at VARCHAR(40) NOT NULL,
 created_by BIGINT NOT NULL, reason TEXT NOT NULL, request_key VARCHAR(100) NOT NULL,
 UNIQUE(institute_id,request_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cash_event_details (
 event_id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, branch_id BIGINT NULL,
 channel VARCHAR(30) NOT NULL, payment_reference VARCHAR(150) NULL,
 recorded_at VARCHAR(40) NOT NULL, created_by BIGINT NOT NULL,
 UNIQUE(institute_id,channel,payment_reference)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS invoice_postings (
 invoice_id BIGINT PRIMARY KEY, institute_id BIGINT NOT NULL, snapshot_json LONGTEXT NOT NULL,
 captured_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS finance_adjustments (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, invoice_id BIGINT NOT NULL,
 kind VARCHAR(30) NOT NULL, amount_paise BIGINT NOT NULL, charge_delta BIGINT NOT NULL,
 writeoff_delta BIGINT NOT NULL, cash_delta BIGINT NOT NULL,
 effective_date VARCHAR(10) NOT NULL, recorded_at VARCHAR(40) NOT NULL, created_by BIGINT NOT NULL,
 reason TEXT NOT NULL, receipt_id BIGINT NULL, writeoff_id BIGINT NULL,
 reverse_of VARCHAR(32) NULL UNIQUE, request_key VARCHAR(100) NOT NULL,
 UNIQUE(institute_id,request_key), UNIQUE(institute_id,writeoff_id)
,
 KEY idx_adjustments_invoice (institute_id,invoice_id,effective_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS accuracy_audit (
 id VARCHAR(32) PRIMARY KEY, institute_id BIGINT NOT NULL, actor_id BIGINT NOT NULL,
 entity_type VARCHAR(40) NOT NULL, entity_id VARCHAR(100) NOT NULL, before_json LONGTEXT NOT NULL,
 after_json LONGTEXT NOT NULL, reason TEXT NOT NULL, effective_date VARCHAR(10) NOT NULL,
 recorded_at VARCHAR(40) NOT NULL, event_order BIGINT NOT NULL,
 UNIQUE(institute_id,entity_type,entity_id,event_order)
,
 KEY idx_accuracy_history (institute_id,entity_type,entity_id,recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
