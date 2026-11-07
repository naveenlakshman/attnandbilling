-- Additive MySQL migration. Apply to the intended sandbox/test ERP database
-- before enabling checkout. Application startup does not run MySQL migrations.
CREATE TABLE IF NOT EXISTS cashfree_orders (
    order_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    institute_id BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    invoice_id BIGINT NOT NULL,
    created_by BIGINT NOT NULL,
    amount_paise BIGINT NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    payment_session_id TEXT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'CREATING',
    cf_payment_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NULL,
    receipt_id BIGINT NULL,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    UNIQUE KEY uq_cashfree_payment (cf_payment_id),
    UNIQUE KEY uq_cashfree_receipt (receipt_id),
    KEY idx_cashfree_invoice (institute_id, invoice_id, status),
    CONSTRAINT chk_cashfree_positive_amount CHECK (amount_paise > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Preserve cashfree_orders and its payment mapping when rolling back code.
-- Dropping this table loses duplicate-payment protection and reconciliation history.
