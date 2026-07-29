-- ============================================================================
-- Migration: Multi-Institute Phase 5 - Finance and Assets
-- Date: 2026-07-24
--
-- Idempotently tenant-scope finance and asset tables.
-- Legacy rows are derived from their owning student/invoice/branch where
-- possible. The institute_id default is removed after backfill so new writes
-- cannot silently fall into institute 1.
-- ============================================================================

DROP PROCEDURE IF EXISTS phase5_add_column;
DROP PROCEDURE IF EXISTS phase5_add_index;

DELIMITER //

CREATE PROCEDURE phase5_add_column(
    IN p_table VARCHAR(64),
    IN p_column VARCHAR(64),
    IN p_definition VARCHAR(255)
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = p_table
          AND COLUMN_NAME = p_column
    ) THEN
        SET @phase5_sql = CONCAT(
            'ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ',
            p_definition
        );
        PREPARE phase5_stmt FROM @phase5_sql;
        EXECUTE phase5_stmt;
        DEALLOCATE PREPARE phase5_stmt;
    END IF;
END//

CREATE PROCEDURE phase5_add_index(
    IN p_table VARCHAR(64),
    IN p_index VARCHAR(64),
    IN p_columns VARCHAR(255)
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = p_table
          AND INDEX_NAME = p_index
    ) THEN
        SET @phase5_sql = CONCAT(
            'CREATE INDEX `', p_index, '` ON `', p_table, '` (', p_columns, ')'
        );
        PREPARE phase5_stmt FROM @phase5_sql;
        EXECUTE phase5_stmt;
        DEALLOCATE PREPARE phase5_stmt;
    END IF;
END//

DELIMITER ;

CALL phase5_add_column(
    'institute_settings', 'invoice_prefix', 'VARCHAR(50) NULL'
);
CALL phase5_add_column(
    'institute_settings', 'receipt_prefix', 'VARCHAR(50) NULL'
);

UPDATE institute_settings
SET invoice_prefix = COALESCE(NULLIF(invoice_prefix, ''), 'GIT/B/'),
    receipt_prefix = COALESCE(NULLIF(receipt_prefix, ''), 'GIT/')
WHERE institute_id = 1;

CALL phase5_add_column('invoices', 'institute_id', 'BIGINT NULL');
UPDATE invoices i
JOIN students s ON s.id = i.student_id
SET i.institute_id = s.institute_id
WHERE i.institute_id IS NULL OR i.institute_id <> s.institute_id;
UPDATE invoices SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE invoices MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'invoices', 'idx_invoices_inst_status', '`institute_id`, `status`'
);
CALL phase5_add_index(
    'invoices', 'idx_invoices_inst_date', '`institute_id`, `invoice_date`'
);

CALL phase5_add_column('receipts', 'institute_id', 'BIGINT NULL');
UPDATE receipts r
JOIN invoices i ON i.id = r.invoice_id
SET r.institute_id = i.institute_id
WHERE r.institute_id IS NULL OR r.institute_id <> i.institute_id;
UPDATE receipts SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE receipts MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'receipts', 'idx_receipts_inst_date', '`institute_id`, `receipt_date`'
);
CALL phase5_add_index(
    'receipts', 'idx_receipts_inst_mode', '`institute_id`, `payment_mode`'
);

CALL phase5_add_column('expense_categories', 'institute_id', 'BIGINT NULL');
UPDATE expense_categories SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE expense_categories MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'expense_categories', 'idx_exp_cat_inst', '`institute_id`'
);

CALL phase5_add_column('expenses', 'institute_id', 'BIGINT NULL');
UPDATE expenses e
JOIN branches b ON b.id = e.branch_id
SET e.institute_id = b.institute_id
WHERE e.institute_id IS NULL OR e.institute_id <> b.institute_id;
UPDATE expenses SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE expenses MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'expenses', 'idx_expenses_inst_date', '`institute_id`, `expense_date`'
);

CALL phase5_add_column('bad_debt_writeoffs', 'institute_id', 'BIGINT NULL');
UPDATE bad_debt_writeoffs w
JOIN invoices i ON i.id = w.invoice_id
SET w.institute_id = i.institute_id
WHERE w.institute_id IS NULL OR w.institute_id <> i.institute_id;
UPDATE bad_debt_writeoffs SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE bad_debt_writeoffs MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'bad_debt_writeoffs', 'idx_writeoffs_inst', '`institute_id`'
);

CALL phase5_add_column('assets', 'institute_id', 'BIGINT NULL');
UPDATE assets a
JOIN branches b ON b.id = a.branch_id
SET a.institute_id = b.institute_id
WHERE a.institute_id IS NULL OR a.institute_id <> b.institute_id;
UPDATE assets SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE assets MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index('assets', 'idx_assets_inst', '`institute_id`');

CALL phase5_add_column('asset_allocation', 'institute_id', 'BIGINT NULL');
UPDATE asset_allocation aa
JOIN assets a ON a.id = aa.asset_id
SET aa.institute_id = a.institute_id
WHERE aa.institute_id IS NULL OR aa.institute_id <> a.institute_id;
UPDATE asset_allocation SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE asset_allocation MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'asset_allocation', 'idx_asset_alloc_inst', '`institute_id`'
);

CALL phase5_add_column('asset_logs', 'institute_id', 'BIGINT NULL');
UPDATE asset_logs al
JOIN assets a ON a.id = al.asset_id
SET al.institute_id = a.institute_id
WHERE al.institute_id IS NULL OR al.institute_id <> a.institute_id;
UPDATE asset_logs SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE asset_logs MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'asset_logs', 'idx_asset_logs_inst', '`institute_id`'
);

CALL phase5_add_column('reminder_logs', 'institute_id', 'BIGINT NULL');
UPDATE reminder_logs r
JOIN invoices i ON i.id = r.invoice_id
SET r.institute_id = i.institute_id
WHERE r.institute_id IS NULL OR r.institute_id <> i.institute_id;
UPDATE reminder_logs SET institute_id = 1 WHERE institute_id IS NULL;
ALTER TABLE reminder_logs MODIFY institute_id BIGINT NOT NULL;
CALL phase5_add_index(
    'reminder_logs', 'idx_reminder_logs_inst', '`institute_id`'
);

DROP PROCEDURE phase5_add_column;
DROP PROCEDURE phase5_add_index;
