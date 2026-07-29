-- Transaction-safe invoice and receipt series per institute and prefix.
CREATE TABLE IF NOT EXISTS institute_document_sequences (
    id BIGINT NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    document_type VARCHAR(20) NOT NULL,
    series_prefix VARCHAR(50) NOT NULL,
    next_value BIGINT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_document_sequence_series (
        institute_id, document_type, series_prefix
    ),
    CONSTRAINT fk_document_sequences_institute
        FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE,
    CONSTRAINT chk_document_sequences_type
        CHECK (document_type IN ('invoice', 'receipt')),
    CONSTRAINT chk_document_sequences_next
        CHECK (next_value > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP PROCEDURE IF EXISTS add_document_number_unique_index;
DELIMITER //
CREATE PROCEDURE add_document_number_unique_index(
    IN p_table VARCHAR(64),
    IN p_index VARCHAR(64)
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = p_table
          AND INDEX_NAME = p_index
    ) THEN
        SET @document_number_sql = CONCAT(
            'CREATE UNIQUE INDEX `', p_index, '` ON `', p_table,
            '` (`institute_id`, `',
            IF(p_table = 'invoices', 'invoice_no', 'receipt_no'),
            '`)'
        );
        PREPARE document_number_stmt FROM @document_number_sql;
        EXECUTE document_number_stmt;
        DEALLOCATE PREPARE document_number_stmt;
    END IF;
END//
DELIMITER ;

CALL add_document_number_unique_index('invoices', 'uq_invoices_institute_no');
CALL add_document_number_unique_index('receipts', 'uq_receipts_institute_no');
DROP PROCEDURE add_document_number_unique_index;

-- Seed each institute's currently configured series from existing documents.
INSERT INTO institute_document_sequences (
    institute_id, document_type, series_prefix, next_value, created_at, updated_at
)
SELECT
    s.institute_id,
    'invoice',
    CONCAT(TRIM(TRAILING '/' FROM s.invoice_prefix), '/'),
    COALESCE(
        MAX(
            CASE
                WHEN CAST(i.invoice_no AS BINARY) LIKE CAST(
                    CONCAT(TRIM(TRAILING '/' FROM s.invoice_prefix), '/%')
                    AS BINARY
                )
                THEN CAST(SUBSTRING_INDEX(i.invoice_no, '/', -1) AS UNSIGNED)
            END
        ),
        0
    ) + 1,
    NOW(),
    NOW()
FROM institute_settings s
LEFT JOIN invoices i ON i.institute_id = s.institute_id
WHERE NULLIF(TRIM(s.invoice_prefix), '') IS NOT NULL
GROUP BY s.institute_id, s.invoice_prefix
ON DUPLICATE KEY UPDATE next_value = GREATEST(
    institute_document_sequences.next_value,
    VALUES(next_value)
);

INSERT INTO institute_document_sequences (
    institute_id, document_type, series_prefix, next_value, created_at, updated_at
)
SELECT
    s.institute_id,
    'receipt',
    CONCAT(TRIM(TRAILING '/' FROM s.receipt_prefix), '/'),
    COALESCE(
        MAX(
            CASE
                WHEN CAST(r.receipt_no AS BINARY) LIKE CAST(
                    CONCAT(TRIM(TRAILING '/' FROM s.receipt_prefix), '/%')
                    AS BINARY
                )
                THEN CAST(SUBSTRING_INDEX(r.receipt_no, '/', -1) AS UNSIGNED)
            END
        ),
        0
    ) + 1,
    NOW(),
    NOW()
FROM institute_settings s
LEFT JOIN receipts r ON r.institute_id = s.institute_id
WHERE NULLIF(TRIM(s.receipt_prefix), '') IS NOT NULL
GROUP BY s.institute_id, s.receipt_prefix
ON DUPLICATE KEY UPDATE next_value = GREATEST(
    institute_document_sequences.next_value,
    VALUES(next_value)
);
