-- Enforce certificate-number integrity after any legacy duplicate data is repaired.
-- This migration is intended for MySQL production/staging databases.
-- The certificate_number unique index will fail if duplicate certificates remain.

CREATE TEMPORARY TABLE certificate_sequence_keep AS
SELECT
  MIN(id) AS keep_id,
  template_code,
  year,
  MAX(current_sequence) AS current_sequence,
  MAX(updated_at) AS updated_at
FROM certificate_sequences
GROUP BY template_code, year;

UPDATE certificate_sequences AS seq
JOIN certificate_sequence_keep AS keep_seq ON keep_seq.keep_id = seq.id
SET
  seq.current_sequence = keep_seq.current_sequence,
  seq.updated_at = keep_seq.updated_at;

DELETE seq
FROM certificate_sequences AS seq
JOIN certificate_sequence_keep AS keep_seq
  ON keep_seq.template_code = seq.template_code
 AND keep_seq.year = seq.year
WHERE seq.id <> keep_seq.keep_id;

DROP TEMPORARY TABLE certificate_sequence_keep;

SET @add_certificate_number_unique := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE certificates ADD UNIQUE KEY uq_certificates_certificate_number (certificate_number)',
    'SELECT ''uq_certificates_certificate_number already exists'' AS certificate_number_integrity_check'
  )
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'certificates'
    AND index_name = 'uq_certificates_certificate_number'
);
PREPARE stmt FROM @add_certificate_number_unique;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @add_sequence_unique := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE certificate_sequences ADD UNIQUE KEY uq_certificate_sequences_template_year (template_code, year)',
    'SELECT ''uq_certificate_sequences_template_year already exists'' AS certificate_number_integrity_check'
  )
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'certificate_sequences'
    AND index_name = 'uq_certificate_sequences_template_year'
);
PREPARE stmt FROM @add_sequence_unique;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
