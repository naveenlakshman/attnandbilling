-- Tenant-isolated asset codes and transaction-safe per-institute numbering.

ALTER TABLE institute_document_sequences
    DROP CHECK chk_document_sequences_type;

ALTER TABLE institute_document_sequences
    ADD CONSTRAINT chk_document_sequences_type
    CHECK (document_type IN ('invoice', 'receipt', 'writeoff', 'asset'));

-- The legacy schema made asset_code globally unique. Tenant ownership requires
-- uniqueness only inside one institute.
SET @asset_code_unique_index = (
    SELECT s.index_name
    FROM information_schema.statistics s
    WHERE s.table_schema = DATABASE()
      AND s.table_name = 'assets'
      AND s.non_unique = 0
    GROUP BY s.index_name
    HAVING GROUP_CONCAT(s.column_name ORDER BY s.seq_in_index) = 'asset_code'
    LIMIT 1
);
SET @drop_asset_unique_sql = IF(
    @asset_code_unique_index IS NULL,
    'SELECT 1',
    CONCAT('ALTER TABLE assets DROP INDEX `',
           REPLACE(@asset_code_unique_index, '`', '``'), '`')
);
PREPARE drop_asset_unique_stmt FROM @drop_asset_unique_sql;
EXECUTE drop_asset_unique_stmt;
DEALLOCATE PREPARE drop_asset_unique_stmt;

SET @asset_tenant_unique_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'assets'
      AND index_name = 'uq_assets_institute_code'
);
SET @add_asset_tenant_unique_sql = IF(
    @asset_tenant_unique_exists = 0,
    'ALTER TABLE assets ADD UNIQUE KEY uq_assets_institute_code (institute_id, asset_code)',
    'SELECT 1'
);
PREPARE add_asset_tenant_unique_stmt FROM @add_asset_tenant_unique_sql;
EXECUTE add_asset_tenant_unique_stmt;
DEALLOCATE PREPARE add_asset_tenant_unique_stmt;

-- Preserve legacy codes, but start each tenant's new AST series after its own
-- highest AST number. Prefix changes get an independent sequence.
INSERT INTO institute_document_sequences (
    institute_id, document_type, series_prefix, next_value, created_at, updated_at
)
SELECT
    a.institute_id,
    'asset',
    'AST/',
    COALESCE(
        MAX(
            CASE
                WHEN a.asset_code REGEXP '^AST-[0-9]+$'
                THEN CAST(SUBSTRING(a.asset_code, 5) AS UNSIGNED)
                ELSE 0
            END
        ),
        0
    ) + 1,
    NOW(),
    NOW()
FROM assets a
GROUP BY a.institute_id
ON DUPLICATE KEY UPDATE
    next_value = GREATEST(
        institute_document_sequences.next_value,
        VALUES(next_value)
    ),
    updated_at = NOW();
