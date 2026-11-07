-- Secure DNS ownership verification for institute custom domains.
-- Apply once before deploying the matching application revision.

ALTER TABLE institute_domains
    ADD COLUMN verification_token VARCHAR(128) NULL AFTER verified_at,
    ADD COLUMN verification_record_name VARCHAR(255) NULL AFTER verification_token,
    ADD COLUMN verification_last_checked_at DATETIME NULL AFTER verification_record_name,
    ADD COLUMN verification_message VARCHAR(500) NULL AFTER verification_last_checked_at;

CREATE INDEX idx_institute_domains_verification
    ON institute_domains (status, verification_last_checked_at);
