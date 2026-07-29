-- Tenant-owned, transaction-safe bad-debt write-off references.
ALTER TABLE institute_document_sequences
    DROP CHECK chk_document_sequences_type;

ALTER TABLE institute_document_sequences
    ADD CONSTRAINT chk_document_sequences_type
    CHECK (document_type IN ('invoice', 'receipt', 'writeoff'));

ALTER TABLE bad_debt_writeoffs
    ADD COLUMN reference_no VARCHAR(80) NULL AFTER institute_id;

UPDATE bad_debt_writeoffs w
LEFT JOIN expenses e
    ON e.institute_id = w.institute_id
   AND e.reference_no = CONCAT('WO-', w.id)
SET w.reference_no = COALESCE(e.reference_no, CONCAT('WO-', w.id))
WHERE w.reference_no IS NULL;

-- Convert legacy global WO-{row id} values to an institute-owned series.
-- The temporary mapping lets the related expense retain its audit link.
CREATE TEMPORARY TABLE writeoff_reference_migration (
    writeoff_id BIGINT NOT NULL PRIMARY KEY,
    institute_id BIGINT NOT NULL,
    old_reference VARCHAR(80) NOT NULL,
    new_reference VARCHAR(80) NOT NULL
);

INSERT INTO writeoff_reference_migration (
    writeoff_id, institute_id, old_reference, new_reference
)
SELECT
    ranked.id,
    ranked.institute_id,
    ranked.reference_no,
    CONCAT(ranked.writeoff_prefix, '/', LPAD(ranked.tenant_number, 3, '0'))
FROM (
    SELECT
        w.id,
        w.institute_id,
        w.reference_no,
        CASE
            WHEN UPPER(TRIM(TRAILING '/' FROM COALESCE(s.invoice_prefix, 'INV')))
                 REGEXP '(^|/)(INV|INVOICE)$'
            THEN REGEXP_REPLACE(
                TRIM(TRAILING '/' FROM COALESCE(s.invoice_prefix, 'INV')),
                '(INV|INVOICE)$',
                'WO',
                1,
                0,
                'i'
            )
            ELSE CONCAT(
                TRIM(TRAILING '/' FROM COALESCE(s.invoice_prefix, 'INV')),
                '/WO'
            )
        END AS writeoff_prefix,
        ROW_NUMBER() OVER (
            PARTITION BY w.institute_id
            ORDER BY w.writeoff_date, w.created_at, w.id
        ) AS tenant_number
    FROM bad_debt_writeoffs w
    LEFT JOIN institute_settings s ON s.institute_id = w.institute_id
) ranked;

UPDATE expenses e
JOIN writeoff_reference_migration m
  ON m.institute_id = e.institute_id
 AND m.old_reference = e.reference_no
SET e.reference_no = m.new_reference;

UPDATE bad_debt_writeoffs w
JOIN writeoff_reference_migration m ON m.writeoff_id = w.id
SET w.reference_no = m.new_reference;

ALTER TABLE bad_debt_writeoffs
    MODIFY reference_no VARCHAR(80) NOT NULL;

CREATE UNIQUE INDEX uq_writeoffs_institute_reference
    ON bad_debt_writeoffs (institute_id, reference_no);

INSERT INTO institute_document_sequences (
    institute_id, document_type, series_prefix, next_value, created_at, updated_at
)
SELECT
    numbered.institute_id,
    'writeoff',
    numbered.series_prefix,
    COUNT(*) + 1,
    NOW(),
    NOW()
FROM (
    SELECT
        m.institute_id,
        CONCAT(
            LEFT(
                m.new_reference,
                LENGTH(m.new_reference)
                    - LENGTH(SUBSTRING_INDEX(m.new_reference, '/', -1)) - 1
            ),
            '/'
        ) AS series_prefix
    FROM writeoff_reference_migration m
) numbered
GROUP BY numbered.institute_id, numbered.series_prefix
ON DUPLICATE KEY UPDATE next_value = GREATEST(
    institute_document_sequences.next_value,
    VALUES(next_value)
);

DROP TEMPORARY TABLE writeoff_reference_migration;
