CREATE TABLE IF NOT EXISTS routes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    institute_id BIGINT NOT NULL,
    page_id VARCHAR(40) NOT NULL,
    form_id VARCHAR(40) NOT NULL,
    course_id INT NOT NULL,
    batch_id INT NOT NULL,
    branch_id INT NOT NULL,
    counsellor_user_id INT NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_by_user_id INT NOT NULL,
    updated_by_user_id INT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_routes_tenant_page_form (institute_id, page_id, form_id),
    KEY ix_routes_webhook_lookup (page_id, form_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE notifications
    MODIFY COLUMN state ENUM('REVIEW','PENDING','PROCESSING','RETRY','DONE','DEAD') NOT NULL;

SET @meta_column_sql = IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='notifications' AND column_name='route_id'),
    'SELECT 1', 'ALTER TABLE notifications ADD COLUMN route_id BIGINT UNSIGNED NULL AFTER form_id');
PREPARE meta_column_statement FROM @meta_column_sql;
EXECUTE meta_column_statement;
DEALLOCATE PREPARE meta_column_statement;

SET @meta_column_sql = IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='notifications' AND column_name='mapping_snapshot_json'),
    'SELECT 1', 'ALTER TABLE notifications ADD COLUMN mapping_snapshot_json JSON NULL AFTER counsellor_user_id');
PREPARE meta_column_statement FROM @meta_column_sql;
EXECUTE meta_column_statement;
DEALLOCATE PREPARE meta_column_statement;

SET @meta_column_sql = IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='notifications' AND column_name='campaign_id'),
    'SELECT 1', 'ALTER TABLE notifications ADD COLUMN campaign_id VARCHAR(40) NULL AFTER ad_id');
PREPARE meta_column_statement FROM @meta_column_sql;
EXECUTE meta_column_statement;
DEALLOCATE PREPARE meta_column_statement;

SET @meta_column_sql = IF(
    EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='notifications' AND column_name='adset_id'),
    'SELECT 1', 'ALTER TABLE notifications ADD COLUMN adset_id VARCHAR(40) NULL AFTER campaign_id');
PREPARE meta_column_statement FROM @meta_column_sql;
EXECUTE meta_column_statement;
DEALLOCATE PREPARE meta_column_statement;

SET @meta_index_sql = IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=DATABASE()
        AND table_name='notifications' AND index_name='ix_notifications_review'),
    'SELECT 1',
    'CREATE INDEX ix_notifications_review ON notifications (`state`,`page_id`,`form_id`,`created_at`)'
);
PREPARE meta_index_statement FROM @meta_index_sql;
EXECUTE meta_index_statement;
DEALLOCATE PREPARE meta_index_statement;

SET @meta_index_sql = IF(
    EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=DATABASE()
        AND table_name='notifications' AND index_name='ix_notifications_route'),
    'SELECT 1',
    'CREATE INDEX ix_notifications_route ON notifications (`route_id`,`created_at`)'
);
PREPARE meta_index_statement FROM @meta_index_sql;
EXECUTE meta_index_statement;
DEALLOCATE PREPARE meta_index_statement;
