# Phase 8 Dry-Run Cleanup Playbook

## Purpose
This playbook defines the non-destructive dry-run process for Phase 8 legacy cleanup planning.
No archive or delete operation is allowed until all checkpoints pass and explicit approval is granted.

## Scope
- Build preview visibility for cleanup candidates.
- Capture immutable backup checkpoints before each future destructive stage.
- Define rollback points before any data-changing action.

## Out of Scope
- No DELETE, UPDATE, or table drop in this playbook.
- No schema rewrite in this playbook.

## Prerequisites
- Phase 7 signed off.
- Phase 8 assessment mode active.
- Existing scripts available:
  - scripts/phase8_cleanup_readiness_report.py
  - scripts/phase8_preview_queries.py
  - scripts/phase8_backup_checkpoint.py

## Checkpoint Model
Use named checkpoints that map one-to-one to future execution stages.

- CP0: Baseline before any cleanup rehearsal.
- CP1: Immediate pre-archive checkpoint (future).
- CP2: Immediate pre-delete checkpoint (future).
- CP3: Final validation checkpoint (future).

## Dry-Run Execution Steps

### Step 1: Create CP0 baseline backup
Command:
```powershell
python scripts/phase8_backup_checkpoint.py --label phase8_cp0_baseline
```
Expected:
- phase8_backup_ok=True
- backup_path printed under instance/backup

### Step 2: Run readiness inventory
Command:
```powershell
python scripts/phase8_cleanup_readiness_report.py
```
Expected:
- phase8_readiness_report_ok=True
- Current legacy/master footprint summary printed

### Step 3: Run preview SQL package (read-only)
Command:
```powershell
python scripts/phase8_preview_queries.py
```
Expected:
- phase8_preview_ok=True
- Candidate and guardrail counts printed

### Step 4: Sign-off gate before any destructive work
All of the following must be true:
- legacy_topics_without_bridge = 0 (except explicitly approved exclusions)
- duplicate_program_master_links = 0
- duplicate_master_progress_keys = 0
- CP0 backup exists and is restorable
- Explicit human approval captured for next operation

## Preview SQL (Reference)
These are the core read-only queries used to estimate cleanup scope.

```sql
-- Program migration coverage
SELECT p.id, p.program_name,
       (SELECT COUNT(*) FROM lms_chapters c WHERE c.program_id = p.id) AS legacy_chapters,
       (SELECT COUNT(DISTINCT t.chapter_id)
        FROM lms_master_topic_bridge b
        JOIN lms_topics t ON t.id = b.legacy_topic_id
        JOIN lms_chapters c2 ON c2.id = t.chapter_id
        WHERE c2.program_id = p.id) AS migrated_legacy_chapters
FROM lms_programs p
WHERE p.slug != '__lms_master_bridge__'
ORDER BY p.id;
```

```sql
-- Legacy topics without bridge (must remain zero unless approved exception)
SELECT COUNT(*) AS legacy_topics_without_bridge
FROM lms_topics t
WHERE NOT EXISTS (
    SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
);
```

```sql
-- Chapters where all topics are bridged (potential future archive candidates)
SELECT COUNT(*) AS legacy_chapters_all_topics_bridged
FROM lms_chapters c
WHERE EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id)
  AND NOT EXISTS (
      SELECT 1
      FROM lms_topics t
      WHERE t.chapter_id = c.id
        AND NOT EXISTS (
            SELECT 1 FROM lms_master_topic_bridge b WHERE b.legacy_topic_id = t.id
        )
  );
```

```sql
-- Empty legacy chapters (explicit policy candidates)
SELECT COUNT(*) AS legacy_empty_chapters
FROM lms_chapters c
WHERE NOT EXISTS (SELECT 1 FROM lms_topics t WHERE t.chapter_id = c.id);
```

```sql
-- Uniqueness guardrails
SELECT COUNT(*) AS duplicate_program_master_links
FROM (
    SELECT program_id, master_chapter_id, COUNT(*) AS n
    FROM lms_program_chapters
    GROUP BY program_id, master_chapter_id
    HAVING n > 1
) t;

SELECT COUNT(*) AS duplicate_master_progress_keys
FROM (
    SELECT student_id, program_id, master_topic_id, COUNT(*) AS n
    FROM lms_master_topic_progress
    GROUP BY student_id, program_id, master_topic_id
    HAVING n > 1
) t;
```

## Backup and Rollback Checkpoints (Future Execution)
For each future destructive stage, create a checkpoint immediately before execution.

- Before archive stage: create CP1
  - python scripts/phase8_backup_checkpoint.py --label phase8_cp1_pre_archive
- Before delete stage: create CP2
  - python scripts/phase8_backup_checkpoint.py --label phase8_cp2_pre_delete
- Before final toggle/cleanup completion: create CP3
  - python scripts/phase8_backup_checkpoint.py --label phase8_cp3_pre_finalize

Rollback rule:
- If any post-step validation fails, stop immediately and restore the most recent checkpoint backup.
- Do not continue to the next stage until rollback root cause is understood and signed off.

## Validation Checklist
- No destructive statements were executed.
- CP0 backup exists.
- readiness and preview scripts return success markers.
- Guardrail counts remain zero for duplicate keys.
- Known exclusions are documented (for example, empty chapter policy).

## Current Baseline (2026-05-09)
- legacy_topics_without_bridge = 0
- legacy_empty_chapters = 1
- duplicate_program_master_links = 0
- duplicate_master_progress_keys = 0

## Next Step After Dry-Run
Create a dedicated Phase 8 execution plan document for archive/delete operations with:
- exact table-level action list
- per-step SQL transaction boundaries
- explicit restore command path using named checkpoints
- post-step validation queries
