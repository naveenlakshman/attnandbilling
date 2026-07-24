-- ============================================================================
-- Migration: Multi-Institute Phase 5 — Finance and Assets
-- Author: Antigravity Team
-- Date: 2026-07-24
-- Description:
--   1. Add institute_id to invoices, receipts, expenses, expense_categories,
--      bad_debt_writeoffs, assets, asset_allocation, asset_logs, reminder_logs.
--   2. Backfill existing records with institute_id = 1 (Global IT Education).
--   3. Add invoice_prefix and receipt_prefix columns to institute_settings.
--   4. Create performance indexes for multi-tenant query isolation.
-- ============================================================================

-- 1. institute_settings table prefix columns
ALTER TABLE `institute_settings`
ADD COLUMN `invoice_prefix` VARCHAR(50) DEFAULT 'GIT/B/',
ADD COLUMN `receipt_prefix` VARCHAR(50) DEFAULT 'GIT/';

UPDATE `institute_settings` SET `invoice_prefix` = 'GIT/B/', `receipt_prefix` = 'GIT/' WHERE `institute_id` = 1 AND (`invoice_prefix` IS NULL OR `invoice_prefix` = '');

INSERT INTO `institute_settings` (`institute_id`, `invoice_prefix`, `receipt_prefix`, `updated_at`)
VALUES (16, 'MEI/B/', 'MEI/', NOW())
ON DUPLICATE KEY UPDATE `invoice_prefix` = 'MEI/B/', `receipt_prefix` = 'MEI/', `updated_at` = NOW();

-- 2. invoices table
ALTER TABLE `invoices`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `invoices` i
JOIN `students` s ON i.`student_id` = s.`id`
SET i.`institute_id` = s.`institute_id`;

CREATE INDEX `idx_invoices_inst_status` ON `invoices` (`institute_id`, `status`);
CREATE INDEX `idx_invoices_inst_date` ON `invoices` (`institute_id`, `invoice_date`);

-- 3. receipts table
ALTER TABLE `receipts`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `receipts` r
JOIN `invoices` i ON r.`invoice_id` = i.`id`
SET r.`institute_id` = i.`institute_id`;

CREATE INDEX `idx_receipts_inst_date` ON `receipts` (`institute_id`, `receipt_date`);
CREATE INDEX `idx_receipts_inst_mode` ON `receipts` (`institute_id`, `payment_mode`);

-- 4. expenses & expense_categories table
ALTER TABLE `expense_categories`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

CREATE INDEX `idx_exp_cat_inst` ON `expense_categories` (`institute_id`);

ALTER TABLE `expenses`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `expenses` e
LEFT JOIN `branches` b ON e.`branch_id` = b.`id`
SET e.`institute_id` = COALESCE(b.`institute_id`, 1);

CREATE INDEX `idx_expenses_inst_date` ON `expenses` (`institute_id`, `expense_date`);

-- 5. bad_debt_writeoffs table
ALTER TABLE `bad_debt_writeoffs`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `bad_debt_writeoffs` w
JOIN `invoices` i ON w.`invoice_id` = i.`id`
SET w.`institute_id` = i.`institute_id`;

CREATE INDEX `idx_writeoffs_inst` ON `bad_debt_writeoffs` (`institute_id`);

-- 6. assets, asset_allocation, asset_logs tables
ALTER TABLE `assets`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `assets` a
LEFT JOIN `branches` b ON a.`branch_id` = b.`id`
SET a.`institute_id` = COALESCE(b.`institute_id`, 1);

CREATE INDEX `idx_assets_inst` ON `assets` (`institute_id`);

ALTER TABLE `asset_allocation`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `asset_allocation` aa
JOIN `assets` a ON aa.`asset_id` = a.`id`
SET aa.`institute_id` = a.`institute_id`;

CREATE INDEX `idx_asset_alloc_inst` ON `asset_allocation` (`institute_id`);

ALTER TABLE `asset_logs`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `asset_logs` al
JOIN `assets` a ON al.`asset_id` = a.`id`
SET al.`institute_id` = a.`institute_id`;

CREATE INDEX `idx_asset_logs_inst` ON `asset_logs` (`institute_id`);

-- 7. reminder_logs table
ALTER TABLE `reminder_logs`
ADD COLUMN `institute_id` INT NOT NULL DEFAULT 1;

UPDATE `reminder_logs` r
LEFT JOIN `invoices` i ON r.`invoice_id` = i.`id`
SET r.`institute_id` = COALESCE(i.`institute_id`, 1);

CREATE INDEX `idx_reminder_logs_inst` ON `reminder_logs` (`institute_id`);
