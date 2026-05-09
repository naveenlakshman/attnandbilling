# Phase 8 Execution Plan — Staged Cleanup with CP1/CP2 Rollback Boundaries

**Status:** DRY-RUN ONLY — No destructive SQL may execute until human sign-off at each gate.  
**Date drafted:** 2026-05-09  
**Depends on:** docs/phase8_dry_run_cleanup_playbook.md (CP0 baseline already captured)

---

## Overview

Phase 8 cleanup removes the legacy chapter/topic rows that are now fully superseded by the
master library. It is split into two destructive stages, each preceded by an immutable SQLite
checkpoint backup:

| Stage | Boundary | Backup label | What changes |
|-------|----------|--------------|--------------|
| Stage 1 | CP1 | phase8_cp1_pre_archive | Soft-retire legacy chapter rows by toggling an `archived` flag (non-destructive data change) |
| Stage 2 | CP2 | phase8_cp2_pre_delete | Hard-delete bridge orphans, progress orphans, then legacy topic/chapter rows |
| Stage 3 | CP3 | phase8_cp3_pre_finalize | Drop bridge program slug + any remaining scaffolding |

Rollback at any stage: restore the **immediately preceding** checkpoint backup — never roll back
across multiple stages at once without a signed-off plan.

---

## Pre-Execution Guardrail Run (Required Before CP1)

Run these read-only queries. All counts must match the expected values before proceeding.

### G-1: Legacy topics without bridge (must be 0)
```sql
-- DRY-RUN: guardrail check — must return 0 before any stage proceeds
SELECT COUNT(*) AS legacy_topics_without_bridge
FROM lms_topics t
WHERE NOT EXISTS (
    SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
);
-- EXPECTED: 0
-- APPROVAL GATE: If > 0, stop and investigate before continuing.
```

### G-2: Duplicate program-master links (must be 0)
```sql
-- DRY-RUN: guardrail — duplicates in lms_program_chapters
SELECT COUNT(*) AS duplicate_program_master_links
FROM (
    SELECT program_id, master_chapter_id, COUNT(*) AS n
    FROM lms_program_chapters
    GROUP BY program_id, master_chapter_id
    HAVING n > 1
) x;
-- EXPECTED: 0
```

### G-3: Duplicate master progress keys (must be 0)
```sql
-- DRY-RUN: guardrail — uniqueness of master progress rows
SELECT COUNT(*) AS duplicate_master_progress_keys
FROM (
    SELECT student_id, program_id, master_topic_id, COUNT(*) AS n
    FROM lms_master_topic_progress
    GROUP BY student_id, program_id, master_topic_id
    HAVING n > 1
) x;
-- EXPECTED: 0
```

### G-4: All archive candidates fully bridged (preview)
```sql
-- DRY-RUN: list of legacy chapters where every topic has a bridge entry
-- These are the CP1 Stage 1 archive candidates.
SELECT
    c.id              AS legacy_chapter_id,
    c.chapter_title,
    c.program_id,
    COUNT(t.id)       AS topic_count
FROM lms_chapters c
JOIN lms_topics t ON t.chapter_id = c.id
WHERE NOT EXISTS (
    SELECT 1
    FROM lms_topics t2
    WHERE t2.chapter_id = c.id
      AND NOT EXISTS (
          SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t2.id
      )
)
GROUP BY c.id, c.chapter_name, c.program_id
ORDER BY c.program_id, c.id;
-- EXPECTED: 15 rows (all non-empty legacy chapters that are fully migrated)
-- NOTE: chapter_id=13 (empty chapter, program_id=2) is excluded from this list by policy.
-- COLUMN NOTE: lms_chapters uses chapter_title (not chapter_name); lms_topics uses topic_title.
```

### G-5: Empty legacy chapters (policy-excluded, for reference only)
```sql
-- DRY-RUN: confirm policy exclusions — empty chapters with no topics
SELECT c.id AS legacy_chapter_id, c.chapter_name, c.program_id
FROM lms_chapters c
WHERE NOT EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id);
-- EXPECTED: 1 row (chapter_id=13, program_id=2)
-- ACTION: Leave in place. Empty chapters are handled separately under policy, not here.
```

### G-6: Bridge topic content check (before deleting bridge rows)
```sql
-- DRY-RUN: confirm bridge program's lms_topic_contents can be safely cleaned
-- These are contents attached to the compatibility bridge topic, not real student content.
SELECT
    tc.id          AS content_id,
    tc.topic_id    AS bridge_topic_id,
    tc.content_type,
    tc.master_topic_id
FROM lms_topic_contents tc
JOIN lms_topics t ON t.id = tc.topic_id
JOIN lms_chapters c ON c.id = t.chapter_id
JOIN lms_programs p ON p.id = c.program_id
WHERE p.slug = '__lms_master_bridge__'
  AND tc.master_topic_id IS NULL;
-- EXPECTED: 0 rows (bridge program should have no orphaned content without a master_topic_id)
-- NOTE: Content rows where master_topic_id IS NOT NULL are legitimate master library content
-- using the bridge topic to satisfy the topic_id NOT NULL FK constraint. They are excluded.
-- If > 0: investigate before Stage 2.
```

---

## CP1 Boundary — Pre-Archive Checkpoint

**Create this backup immediately before Stage 1 executes.**

```powershell
python scripts/phase8_backup_checkpoint.py --label phase8_cp1_pre_archive
```

Verify output:
- `phase8_backup_ok=True`
- `backup_path` printed (e.g. `instance/backup/phase8_cp1_pre_archive_YYYYMMDD_HHMMSS.db`)
- Record the exact backup filename here before continuing.

**CP1 Rollback command (use only if Stage 1 validation fails):**
```powershell
# ROLLBACK — restore CP1 snapshot (stop the Flask app first)
Copy-Item "instance\backup\phase8_cp1_pre_archive_YYYYMMDD_HHMMSS.db" `
          "instance\database.db" -Force
# Then restart Flask app and rerun G-1 through G-6 to confirm state restored.
```

---

## Stage 1 — Archive Legacy Chapters (Soft Retire)

**Prerequisite:** CP1 backup confirmed. All guardrails G-1 to G-6 pass.

This stage adds an `is_archived` flag to fully-migrated legacy chapters so they are hidden from
student-facing views but the rows are not yet deleted. This is a reversible data update.

### S1-PREVIEW: Count of rows to be archived
```sql
-- DRY-RUN: how many legacy chapter rows will be set is_archived = 1
SELECT COUNT(*) AS chapters_to_archive
FROM lms_chapters c
WHERE EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id)
  AND NOT EXISTS (
      SELECT 1
      FROM lms_topics t2
      WHERE t2.chapter_id = c.id
        AND NOT EXISTS (
            SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t2.id
        )
  );
-- EXPECTED: 15

-- LIVE EQUIVALENT (do not run until approved):
-- UPDATE lms_chapters
-- SET is_archived = 1
-- WHERE EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = lms_chapters.id)
--   AND NOT EXISTS (
--       SELECT 1 FROM lms_topics t2
--       WHERE t2.chapter_id = lms_chapters.id
--         AND NOT EXISTS (
--             SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t2.id
--         )
--   );
```

### S1-PREVIEW: Topics inside those chapters (for reference)
```sql
-- DRY-RUN: all legacy topics that will become hidden when their chapter is archived
SELECT
    t.id         AS legacy_topic_id,
    t.topic_title,
    t.chapter_id AS legacy_chapter_id,
    b.master_topic_id
FROM lms_topics t
JOIN lms_master_topic_bridge b ON b.legacy_topic_id = t.id
JOIN lms_chapters c ON c.id = t.chapter_id
WHERE EXISTS (SELECT 1 FROM lms_topics t2 WHERE t2.chapter_id = c.id)
  AND NOT EXISTS (
      SELECT 1 FROM lms_topics t3
      WHERE t3.chapter_id = c.id
        AND NOT EXISTS (
            SELECT 1 FROM lms_master_topic_bridge b2 WHERE b2.legacy_topic_id = t3.id
        )
  )
ORDER BY c.id, t.sort_order;
-- EXPECTED: 102 rows (all bridged legacy topics, grouped by their 15 archive-candidate chapters)
```

### S1-PREVIEW: Legacy topic content rows that will become inactive
```sql
-- DRY-RUN: content rows attached to topics that will be archived
SELECT COUNT(*) AS legacy_contents_in_archived_chapters
FROM lms_topic_contents tc
JOIN lms_topics t ON t.id = tc.topic_id
JOIN lms_chapters c ON c.id = t.chapter_id
WHERE EXISTS (SELECT 1 FROM lms_topics t2 WHERE t2.chapter_id = c.id)
  AND NOT EXISTS (
      SELECT 1 FROM lms_topics t3
      WHERE t3.chapter_id = c.id
        AND NOT EXISTS (
            SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t3.id
        )
  );
-- NOTE: These rows are NOT deleted in Stage 1. They simply become unreachable via the
-- archived chapter. They are candidates for Stage 2 cleanup.
```

### S1-VALIDATION: Confirm archive flag before proceeding to CP2
```sql
-- DRY-RUN: Post-Stage-1 check — run this after live UPDATE to confirm
-- SELECT COUNT(*) AS archived_chapters FROM lms_chapters WHERE is_archived = 1;
-- EXPECTED: 15

-- DRY-RUN: confirm no student-facing routes serve archived chapters
-- (verified in code: all student chapter queries must filter WHERE is_archived = 0 or is_archived IS NULL)
```

**Stage 1 sign-off gate:**
- [ ] CP1 backup filename recorded
- [ ] S1-PREVIEW counts match expected values (15 chapters, 102 topics)
- [ ] `is_archived` column exists on `lms_chapters` (add via migration if not present)
- [ ] Student-facing routes filter `is_archived`
- [ ] Explicit human approval captured

---

## CP2 Boundary — Pre-Delete Checkpoint

**Create this backup immediately before Stage 2 executes.**

```powershell
python scripts/phase8_backup_checkpoint.py --label phase8_cp2_pre_delete
```

Verify output:
- `phase8_backup_ok=True`
- Record the exact backup filename before continuing.

**CP2 Rollback command (use only if Stage 2 validation fails):**
```powershell
# ROLLBACK — restore CP2 snapshot (stop Flask first)
Copy-Item "instance\backup\phase8_cp2_pre_delete_YYYYMMDD_HHMMSS.db" `
          "instance\database.db" -Force
# Restart Flask, rerun all guardrails and Stage 1 validation to confirm state.
```

---

## Stage 2 — Hard Delete: Bridge Orphans, Progress Orphans, Legacy Rows

**Prerequisite:** CP2 backup confirmed. Stage 1 validation passed.

Delete order is critical due to foreign key constraints (`PRAGMA foreign_keys = ON`).
Execute in this exact sequence: bridge rows → legacy content/attachment rows → legacy topics → legacy chapters.

### S2-PREVIEW-A: Bridge rows to delete
```sql
-- DRY-RUN: count of lms_master_topic_bridge rows that will be removed
SELECT COUNT(*) AS bridge_rows_to_delete
FROM lms_master_topic_bridge;
-- EXPECTED: 102

-- LIVE EQUIVALENT (do not run until approved):
-- DELETE FROM lms_master_topic_bridge;
-- NOTE: Only run this after all legacy topic content has been migrated to master_topic_id
-- references or archived. Verify G-6 passes first (bridge program has no real content).
```

### S2-PREVIEW-B: Bridge program chapters to delete
```sql
-- DRY-RUN: lms_program_chapters rows for the bridge program
SELECT pc.id, pc.program_id, pc.master_chapter_id, pc.sort_order
FROM lms_program_chapters pc
JOIN lms_programs p ON p.id = pc.program_id
WHERE p.slug = '__lms_master_bridge__';
-- EXPECTED: at least 1 row (the bridge chapter link)

-- LIVE EQUIVALENT (do not run until approved):
-- DELETE FROM lms_program_chapters
-- WHERE program_id = (SELECT id FROM lms_programs WHERE slug = '__lms_master_bridge__');
```

### S2-PREVIEW-C: Orphaned legacy topic content rows to delete
```sql
-- DRY-RUN: content rows in archived chapters, now safe to hard-delete
SELECT COUNT(*) AS legacy_content_rows_to_delete
FROM lms_topic_contents tc
JOIN lms_topics t ON t.id = tc.topic_id
JOIN lms_chapters c ON c.id = t.chapter_id
WHERE c.is_archived = 1;
-- NOTE: This query only works after Stage 1 live UPDATE has run.
-- For dry-run estimation, use the count from S1-PREVIEW (legacy_contents_in_archived_chapters).

-- LIVE EQUIVALENT (do not run until approved):
-- DELETE FROM lms_topic_contents
-- WHERE topic_id IN (
--     SELECT t.id FROM lms_topics t
--     JOIN lms_chapters c ON c.id = t.chapter_id
--     WHERE c.is_archived = 1
-- );
```

### S2-PREVIEW-D: Orphaned legacy topic attachment rows to delete
```sql
-- DRY-RUN: attachment rows in archived chapters
SELECT COUNT(*) AS legacy_attachment_rows_to_delete
FROM lms_topic_attachments ta
JOIN lms_topics t ON t.id = ta.topic_id
JOIN lms_chapters c ON c.id = t.chapter_id
WHERE c.is_archived = 1;

-- LIVE EQUIVALENT (do not run until approved):
-- DELETE FROM lms_topic_attachments
-- WHERE topic_id IN (
--     SELECT t.id FROM lms_topics t
--     JOIN lms_chapters c ON c.id = t.chapter_id
--     WHERE c.is_archived = 1
-- );
```

### S2-PREVIEW-E: Legacy progress rows to evaluate (handle with care)
```sql
-- DRY-RUN: legacy progress rows for students in archived-chapter topics
-- These rows track per-topic completion and may have reporting value.
-- Policy: archive to a shadow table, do not hard-delete, unless explicitly approved.
SELECT COUNT(*) AS legacy_progress_rows_in_archived_chapters
FROM lms_topic_progress tp
JOIN lms_topics t ON t.id = tp.topic_id
JOIN lms_chapters c ON c.id = t.chapter_id
WHERE c.is_archived = 1;

-- LIVE EQUIVALENT (archive-first approach — do not run until approved):
-- INSERT INTO lms_topic_progress_archive SELECT * FROM lms_topic_progress
-- WHERE topic_id IN (
--     SELECT t.id FROM lms_topics t
--     JOIN lms_chapters c ON c.id = t.chapter_id
--     WHERE c.is_archived = 1
-- );
-- DELETE FROM lms_topic_progress
-- WHERE topic_id IN (
--     SELECT t.id FROM lms_topics t
--     JOIN lms_chapters c ON c.id = t.chapter_id
--     WHERE c.is_archived = 1
-- );
-- NOTE: lms_topic_progress_archive must be created before this runs.
```

### S2-PREVIEW-F: Legacy topic rows to delete
```sql
-- DRY-RUN: count of lms_topics rows to delete (only after content/attachment/progress cleared)
SELECT COUNT(*) AS legacy_topics_to_delete
FROM lms_topics t
JOIN lms_chapters c ON c.id = t.chapter_id
WHERE c.is_archived = 1;
-- EXPECTED: 102

-- LIVE EQUIVALENT (do not run until approved):
-- DELETE FROM lms_topics
-- WHERE chapter_id IN (SELECT id FROM lms_chapters WHERE is_archived = 1);
```

### S2-PREVIEW-G: Legacy chapter rows to delete
```sql
-- DRY-RUN: count of lms_chapters rows to delete (only after all topic rows cleared)
SELECT COUNT(*) AS legacy_chapters_to_delete
FROM lms_chapters
WHERE is_archived = 1;
-- EXPECTED: 15

-- LIVE EQUIVALENT (do not run until approved):
-- DELETE FROM lms_chapters WHERE is_archived = 1;
```

### S2-PREVIEW-H: Bridge program row to delete (last)
```sql
-- DRY-RUN: the bridge program row itself
SELECT id, program_name, slug FROM lms_programs WHERE slug = '__lms_master_bridge__';

-- LIVE EQUIVALENT (do not run until approved — run absolutely last):
-- DELETE FROM lms_programs WHERE slug = '__lms_master_bridge__';
```

### S2-VALIDATION: Post-Stage-2 expected state
```sql
-- DRY-RUN: final state checks to run after Stage 2 live deletes
-- SELECT COUNT(*) FROM lms_master_topic_bridge;   -- EXPECTED: 0
-- SELECT COUNT(*) FROM lms_chapters WHERE is_archived = 1;  -- EXPECTED: 0
-- SELECT COUNT(*) FROM lms_topics;  -- EXPECTED: 0 (all legacy topics removed)
-- SELECT COUNT(*) FROM lms_programs WHERE slug = '__lms_master_bridge__';  -- EXPECTED: 0
-- SELECT COUNT(*) FROM lms_master_topics;  -- EXPECTED: 102 (unchanged)
-- SELECT COUNT(*) FROM lms_master_chapters;  -- EXPECTED: 15 (unchanged)
```

**Stage 2 sign-off gate:**
- [ ] CP2 backup filename recorded
- [ ] All S2-PREVIEW counts reviewed and match expectations
- [ ] `lms_topic_progress_archive` shadow table created (if legacy progress rows > 0)
- [ ] Delete order confirmed: bridge rows → content → attachments → progress → topics → chapters → bridge program
- [ ] Explicit human approval captured for each delete batch

---

## CP3 Boundary — Pre-Finalize Checkpoint

**Create this backup before Stage 3.**

```powershell
python scripts/phase8_backup_checkpoint.py --label phase8_cp3_pre_finalize
```

---

## Stage 3 — Deferred Schema Cleanup

**Prerequisite:** CP3 backup confirmed. Stage 2 validation passed.  
**Current decision:** Deferred. The live app still uses `master_topic_id` in active admin and student flows, so the schema columns cannot be dropped yet.

### S3-PREVIEW: Columns that can be dropped (optional schema cleanup)
```sql
-- DRY-RUN: confirm master_topic_id columns are no longer needed on legacy content tables
-- (only drop if all content is now referenced exclusively through master_topic_id
--  and legacy topic rows are gone)
SELECT COUNT(*) AS legacy_contents_with_null_master_topic_id
FROM lms_topic_contents
WHERE master_topic_id IS NULL;
-- If 0 after Stage 2 cleanup, the column is safe to drop.

-- LIVE EQUIVALENT (do not run until approved):
-- ALTER TABLE lms_topic_contents DROP COLUMN master_topic_id;
-- ALTER TABLE lms_topic_attachments DROP COLUMN master_topic_id;
-- NOTE: SQLite DROP COLUMN requires SQLite >= 3.35.0. Verify version before running.
-- NOTE: Not safe to execute yet. Active code still depends on these columns for content routing.
```

### S3-VALIDATION: Final database footprint
```sql
-- DRY-RUN: expected final counts after all three stages complete
-- SELECT COUNT(*) FROM lms_master_chapters;       -- EXPECTED: 15
-- SELECT COUNT(*) FROM lms_master_topics;         -- EXPECTED: 102
-- SELECT COUNT(*) FROM lms_program_chapters;      -- EXPECTED: active program links only
-- SELECT COUNT(*) FROM lms_master_topic_progress; -- EXPECTED: unchanged student progress
-- SELECT COUNT(*) FROM lms_chapters;              -- EXPECTED: 1 (empty chapter_id=13, policy exclusion)
-- SELECT COUNT(*) FROM lms_topics;                -- EXPECTED: 0
-- SELECT COUNT(*) FROM lms_programs WHERE slug != '__lms_master_bridge__'; -- EXPECTED: active programs
```

### S3-Decision Gate
- `master_topic_id` remains in active use across `modules/lms_admin/routes.py` and `modules/students/routes.py`.
- Bridge content and student progress still rely on that compatibility layer.
- Keep the bridge chapter and schema columns in place until a dedicated schema-removal migration is designed and tested.

---

## Rollback Decision Tree

```
Stage fails or validation count mismatch?
│
├─ During Stage 1 (archive update):
│   → Restore CP1 backup
│   → Rerun G-1 through G-6 to confirm clean state
│   → Investigate mismatch before re-attempting Stage 1
│
├─ During Stage 2 (hard deletes):
│   → Restore CP2 backup (NOT CP1 — CP2 is immediately pre-delete)
│   → Rerun Stage 1 validation queries to confirm archive flags intact
│   → Investigate which delete batch caused the mismatch
│   → If CP2 restore is insufficient, escalate to CP1 restore
│
└─ During Stage 3 (schema cleanup):
    → Restore CP3 backup
    → No data loss risk (Stage 3 is schema-only)
    → SQLite version check before retrying DROP COLUMN
```

---

## Execution Checklist Summary

### Before CP1
- [ ] G-1: legacy_topics_without_bridge = 0
- [ ] G-2: duplicate_program_master_links = 0
- [ ] G-3: duplicate_master_progress_keys = 0
- [ ] G-4: 15 archive candidates confirmed
- [ ] G-5: 1 policy-excluded empty chapter confirmed
- [ ] G-6: bridge program has no real content rows
- [ ] CP1 backup created and filename recorded

### Before CP2
- [ ] Stage 1 live UPDATE executed (is_archived flag set on 15 chapters)
- [ ] Post-Stage-1 validation confirms 15 archived chapters
- [ ] Student-facing routes tested: archived chapters not visible
- [ ] CP2 backup created and filename recorded

### Before CP3
- [ ] All Stage 2 deletes executed in correct order
- [ ] S2-VALIDATION counts all match expected values
- [ ] Legacy progress rows archived to shadow table (if applicable)
- [ ] CP3 backup created and filename recorded

### After Stage 3
- [ ] Final S3-VALIDATION counts match expected values
- [ ] App smoke test (student LMS navigation, admin library) passes
- [ ] Phase 8 entry in docs/progress.md updated with completion sign-off

---

## Known Approved Exclusions

| Item | Reason | Action |
|------|--------|--------|
| `lms_chapters.id = 13` (program_id=2, empty chapter) | No topics — excluded by policy | Leave in place; not included in archive or delete candidates |

---

*This document covers dry-run SQL templates only. No destructive statement in this file
may execute without an explicit human sign-off at each checkpoint gate.*
