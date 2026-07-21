-- Allow rich-text assignment instructions larger than MySQL TEXT's 65,535-byte limit.
-- Application validation caps incoming descriptions at 500 KiB.
ALTER TABLE lms_assignments
    MODIFY COLUMN description MEDIUMTEXT NULL;
