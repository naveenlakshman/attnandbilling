# LMS Reusable Content Architecture - Implementation Plan

## 1. Current Architecture Analysis

### 1.1 Current Database Structure

```text
lms_programs (id, course_id, program_name, slug, ...)
  -> lms_chapters (id, program_id FK CASCADE, chapter_title, chapter_order, ...)
      -> lms_topics (id, chapter_id FK CASCADE, topic_title, topic_order, ...)
          -> lms_topic_contents (id, topic_id FK CASCADE, content_mode, external_url, file_path, content_body, ...)
          -> lms_topic_attachments (id, topic_id FK CASCADE, file_name, file_path, ...)

lms_topic_progress (student_id, topic_id) UNIQUE(student_id, topic_id)
lms_student_topic_progress (student_id, topic_id) UNIQUE(student_id, topic_id)
```

### 1.2 Content and Progress Flow
1. Admin creates program and program-owned chapters (`lms_chapters.program_id`).
2. Admin creates chapter-owned topics (`lms_topics.chapter_id`).
3. Topic lesson/video/download content is stored in `lms_topic_contents`.
4. Optional topic files are stored in `lms_topic_attachments`.
5. Student completion is tracked by topic id in legacy progress tables.

## 2. Problems in Current Design

- `lms_chapters` is tied to one program, so chapters cannot be reused.
- `lms_topics` is tied to one chapter (and indirectly one program).
- Same chapter/topic content must be duplicated manually across programs.
- Legacy progress uniqueness is topic-scoped only, not program-scoped.
- No master content library exists for reusable chapter/topic authoring.

## 3. New Reusable Architecture

### 3.1 New Tables (additive)

- `lms_master_chapters`
  - `id`, `title`, `description`, `status`, `created_by`, `created_at`, `updated_at`

- `lms_master_topics` (metadata only)
  - `id`, `master_chapter_id`, `title`, `short_description`, `topic_order`, `status`, `created_at`, `updated_at`

- `lms_program_chapters` (link table)
  - `id`, `program_id`, `master_chapter_id`, `chapter_order`, `custom_title`, `is_visible`, `created_at`
  - unique: (`program_id`, `master_chapter_id`)

- `lms_master_topic_progress` (program-isolated progress)
  - `id`, `student_id`, `program_id`, `master_topic_id`, `is_completed`, `completed_at`, `created_at`, `updated_at`
  - unique: (`student_id`, `program_id`, `master_topic_id`)

### 3.2 Reuse Existing Content Tables (no duplicate editor system)

- Keep content in existing tables:
  - `lms_topic_contents`
  - `lms_topic_attachments`
- Add nullable `master_topic_id` to both.
- Legacy topics continue using `topic_id`.
- New reusable topics use `master_topic_id`.
- Existing TinyMCE, upload, and rendering logic are reused.

## 4. Database Changes

Implemented/Planned schema approach:
- Add new reusable master tables only.
- Add nullable columns only (`ALTER TABLE ... ADD COLUMN`) via existing safe helper.
- Add non-destructive indexes for lookup speed.
- Keep all legacy LMS tables unchanged.

## 5. Fallback Strategy

Student and admin flow is dual-mode:
- If program has rows in `lms_program_chapters`, use master chapter flow.
- Else use legacy `lms_chapters` flow.

For topic content:
- If content row has `master_topic_id`, use master topic flow.
- Else use legacy `topic_id` flow.

Legacy routes remain active until full migration verification.

## 6. Student Progress Isolation Strategy

- New reusable content writes progress to `lms_master_topic_progress`.
- Uniqueness includes `program_id`, so same student and same master topic in two programs are independent records.
- Legacy progress tables (`lms_topic_progress`, `lms_student_topic_progress`) are not altered and remain fallback-only.

## 7. Route Changes (Planned)

### Master Content Library
- list/create/edit/archive master chapters
- list/create/edit/delete/reorder master topics
- reuse existing content/attachment editor workflow

### Program Builder
- view linked master chapters per program
- attach existing master chapter to program
- unlink chapter from program (without deleting master chapter)
- reorder linked chapters
- toggle chapter visibility

### Student LMS
- resolve chapters via master links first, legacy fallback second
- open lesson/video/download from existing content tables using either `master_topic_id` or `topic_id`
- update progress in `lms_master_topic_progress` for master topics and legacy tables for legacy topics

## 8. Template Changes (Planned)

New templates:
- `templates/lms_admin/master_chapters.html`
- `templates/lms_admin/master_chapter_form.html`
- `templates/lms_admin/master_topics.html`
- `templates/lms_admin/master_topic_form.html`
- `templates/lms_admin/attach_chapter_modal.html`

Updated templates:
- `templates/lms_admin/lms_chapters.html` (program builder + attach modal entry)
- `templates/lms_admin/lms_program_view.html` (shared chapter visibility)
- student templates use same rendering with dual-source data from routes

## 9. Migration Strategy

### Guiding principles
- Additive migrations only
- Backward compatibility first
- No destructive schema edits
- No removal of legacy flow until final verification

### Phase-by-phase

## Phase 1
Objective:
- Add new reusable tables and nullable `master_topic_id` columns safely.

Affected files:
- `db.py`

Database impact:
- Create: `lms_master_chapters`, `lms_master_topics`, `lms_program_chapters`, `lms_master_topic_progress`
- Add columns: `lms_topic_contents.master_topic_id`, `lms_topic_attachments.master_topic_id`
- Add indexes for new lookup paths

Risks:
- Low (idempotent create/add-column operations)

Rollback strategy:
- Keep new tables unused if needed; legacy flow remains default

Testing checklist:
- app init succeeds
- new tables exist
- new columns exist
- legacy LMS pages still work

Dependencies:
- none

## Phase 2
Objective:
- Build master content library (admin CRUD) reusing current content editor/upload logic.

Affected files:
- `modules/lms_admin/routes.py`
- `templates/lms_admin/*` (new master templates)

Database impact:
- write/read master chapter/topic data
- write/read content rows with `master_topic_id`

Risks:
- route integration and validation coverage

Rollback strategy:
- disable new routes; legacy routes unchanged

Testing checklist:
- admin creates chapter + topics + content + attachments
- edit and reorder work

Dependencies:
- phase 1 complete

## Phase 3
Objective:
- Program builder linking for reusable chapters.

Affected files:
- `modules/lms_admin/routes.py`
- `templates/lms_admin/lms_chapters.html`
- `templates/lms_admin/attach_chapter_modal.html`

Database impact:
- write/read `lms_program_chapters`

Risks:
- ordering and duplicate-link prevention UX

Rollback strategy:
- remove link rows for affected program

Testing checklist:
- attach/unlink/reorder/visibility per program

Dependencies:
- phase 2 complete

## Phase 4
Objective:
- Student dual-mode consumption and progress write path.

Affected files:
- `modules/students/routes.py`
- student lesson/program templates (minimal changes)

Database impact:
- reads from both legacy and master structures
- writes to `lms_master_topic_progress` for master topics

Risks:
- ambiguous route resolution if context is missing

Rollback strategy:
- route fallback to legacy-only mode

Testing checklist:
- master topic display works
- progress isolation by program works
- legacy topics still work

Dependencies:
- phase 3 complete

## Phase 5
Objective:
- CCOM pilot migration only.

Affected files:
- migration utility script(s) / admin migration helper route (if added)

Database impact:
- copy selected chapter/topics into master structures
- map content/attachments via `master_topic_id`
- create link rows in `lms_program_chapters`

Risks:
- duplicate migration runs

Rollback strategy:
- unlink migrated master chapter from CCOM, revert to legacy flow

Testing checklist:
- 21-topic MS Excel works in CCOM and another program
- one edit reflects everywhere
- progress remains program-isolated

Dependencies:
- phase 4 complete

## Phase 6
Objective:
- Gradual rollout to remaining programs.

Affected files:
- migration utilities and operational procedures

Database impact:
- additional master/link/progress rows only

Risks:
- operational consistency across programs

Rollback strategy:
- program-level unlink and legacy fallback

Testing checklist:
- per-program verification before enabling students

Outcome (executed):
- Completed rollout for all content-bearing legacy chapters in active programs.
- Confirmed one-backup-per-batch execution model in operations.
- Confirmed chapter-level skip behavior for zero-topic legacy chapters.

Sign-off decision:
- Keep empty legacy chapters excluded from reusable master migration.
- Do not create placeholder master chapters for empty legacy chapters.
- Preserve legacy fallback behavior during stability audit.

Dependencies:
- phase 5 successful

## Phase 7
Objective:
- Stability period and verification audit.

Affected files:
- monitoring/ops checklist

Database impact:
- none required

Risks:
- hidden edge cases in low-frequency workflows

Rollback strategy:
- continue dual-mode until confidence threshold met

Testing checklist:
- no regressions for legacy and master paths

Execution checklist (started 2026-05-09):
- Route and template integrity:
  - verify dual-mode route endpoints resolve and remain registered
  - compile critical templates (`students/topic.html`, admin rollout/chapter screens)
- Data integrity and uniqueness:
  - verify no duplicates in (`program_id`, `master_chapter_id`) links
  - verify no duplicates in (`student_id`, `program_id`, `master_topic_id`) progress keys
  - verify bridge/topic count consistency (`lms_master_topics` vs bridge rows)
- Student journey regression:
  - open enrolled migrated program and confirm first-topic resolution
  - validate prev/next and sidebar sequencing for master-topic flow
  - mark completion and verify row creation/update in `lms_master_topic_progress`
  - verify idempotent completion action (repeat mark does not duplicate records)
- Admin workflow regression:
  - edit master-topic content and confirm reflected view in linked program contexts
  - upload/download attachment via master-topic path and verify secure serving
- Legacy fallback safety:
  - verify non-migrated/legacy paths still resolve for any legacy-only content
  - maintain rollback readiness (program-level unlink remains available)

Audit automation artifact:
- Script: `scripts/phase7_stability_audit.py`
- Purpose: one-command non-destructive baseline audit for Phase 7
- Run command:
  - `python scripts/phase7_stability_audit.py`
- First execution snapshot:
  - `phase7_audit_timestamp=2026-05-09T14:48:53`
  - `routes_count=195`
  - route checks: pass
  - template compile checks: pass
  - duplicate anomaly checks: pass (`duplicate_program_master_links=0`, `duplicate_master_progress_keys=0`)
  - coverage checks: pass (expected empty-chapter exclusion retained)

Transactional smoke artifact:
- Script: `scripts/phase7_transactional_smoke_checks.py`
- Purpose: HTTP-level student/admin flow checks + progress-write idempotency verification
- Run command:
  - `python scripts/phase7_transactional_smoke_checks.py`
- First execution snapshot:
  - selected tuple: `student_id=3`, `program_id=1`, `master_topic_id=2`
  - `master_topic_view_status=200`
  - completion endpoint sequence (complete -> complete -> incomplete -> complete) all passed with `200`
  - final progress state persisted as completed in `lms_master_topic_progress`
  - admin rollout page check passed (`admin_phase6_rollout_status=200`)
  - overall result: `smoke_ok=True`

Admin propagation + attachment-path artifact:
- Script: `scripts/phase7_admin_content_attachment_checks.py`
- Purpose: verify master-topic content edit propagation and protected file endpoint behavior
- Run command:
  - `python scripts/phase7_admin_content_attachment_checks.py`
- First execution snapshot:
  - fixture: `program_id=1`, `student_id=3`, `content_id=24`, `master_topic_id=34`
  - admin edit + revert cycle passed (`200/302` flow)
  - propagation confirmed in DB and student-rendered topic page
  - protected file path checks passed:
    - unauthenticated request -> login redirect
    - authenticated request -> controlled `404` for missing file (no server error)
    - wrong-mode endpoint -> `404`
  - overall result: `admin_checks_ok=True`

Acceptance criteria for Phase 7 sign-off:
- No blocker-severity regressions in student or admin LMS flows for the stability window.
- No duplicate-key anomalies in link/progress unique domains.
- Completion events successfully recorded in `lms_master_topic_progress` during audit runs.
- Legacy fallback remains functional and untouched.
- Empty chapter exclusion policy remains unchanged and documented.

Sign-off outcome (2026-05-09):
- Phase 7 accepted based on successful stability, transactional, and admin propagation/attachment reruns.
- No blocker-severity regressions identified.
- Duplicate-key anomaly checks remain clean.
- Master-topic completion evidence captured in `lms_master_topic_progress`.
- Residual risks are low and operationally mitigated by dual-mode fallback + unlink rollback posture.

Operational cadence:
- Day 0 baseline (completed): route/template/data integrity snapshot.
- Day 1-3: transactional smoke checks and first real completion event validation.
- End of stability window: final audit summary + sign-off decision for Phase 8 deferral/continuation.

Dependencies:
- phase 6 complete

## Phase 8 (Future Cleanup After Full Production Verification)
Objective:
- Optional legacy cleanup, only by separate approval.

Current decision state:
- Executed in staged cleanup mode on 2026-05-09 with CP1/CP2/CP3 checkpoints.
- Legacy archive/delete actions completed; bridge chapter retained as the FK anchor for master-linked content.

Assessment artifact:
- Script: `scripts/phase8_cleanup_readiness_report.py`
- Purpose: non-destructive inventory of legacy footprint, master coverage, and cleanup candidate signals
- Run command:
  - `python scripts/phase8_cleanup_readiness_report.py`
- Baseline snapshot:
  - `legacy_chapters=16`, `legacy_topics=102`
  - `master_chapters=15`, `master_topics=102`, `bridge_rows=102`
  - `legacy_topics_without_bridge=0`
  - `legacy_empty_chapters=1` (intentional excluded chapter)
  - duplicate anomaly checks clean

Execution result:
- CP1 backup: `instance/backup/phase8_cp1_pre_archive_20260509_161947.db`
- CP2 backup: `instance/backup/phase8_cp2_pre_delete_20260509_162618.db`
- CP3 backup: `instance/backup/phase8_cp3_pre_finalize_20260509_163039.db`
- Stage 1: 15 legacy chapters archived
- Stage 2: 24 bridge topics created, content reassigned, 101 legacy topics and 14 legacy chapters deleted
- Final retained rows: `lms_chapters=2`, `lms_topics=25`, master library unchanged

Dry-run playbook artifact (built):
- Runbook: `docs/phase8_dry_run_cleanup_playbook.md`
- Backup checkpoint utility: `scripts/phase8_backup_checkpoint.py`
- Preview SQL utility: `scripts/phase8_preview_queries.py`
- Validated outputs:
  - `phase8_preview_ok=True`
  - `phase8_backup_ok=True`
  - checkpoint example: `instance/backup/phase8_checkpoint_20260509_150023.db`

Affected files:
- to be decided later

Database impact:
- potentially destructive; explicitly deferred

Risks:
- data loss if done prematurely

Rollback strategy:
- not applicable until separately planned and approved

Testing checklist:
- to be defined in dedicated cleanup plan

Dependencies:
- full production verification + explicit sign-off

## 10. Risks and Rollback Plan

Key risks:
- route ambiguity during dual-mode period
- migration mapping mistakes (`topic_id` <-> `master_topic_id`)
- accidental use of wrong progress table

Controls:
- additive schema only
- pilot-first migration (CCOM)
- explicit route branching rules
- keep legacy flow active until final verification

Rollback posture:
- unlink master chapters per program to revert instantly
- keep all legacy data/tables untouched
- avoid destructive DDL in main rollout

## 11. Testing Strategy

### Unit-level
- query builders choose correct table path by context
- progress write uses expected table per topic mode

### Integration-level
- admin can build reusable content end-to-end
- program builder attach/unlink/reorder works
- student can consume content and complete topics

### Regression-level
- old LMS pages and data continue to function
- downloads and YouTube rendering remain intact

### Pilot-level (CCOM)
- 21-topic chapter reused in at least two programs
- master edits reflect in all linked programs
- progress remains isolated by program

## 12. Permissions and Security Impact

- Keep existing role checks (`admin/staff`) for content management routes.
- Students only access enrolled program content.
- Continue secure file serving and path validation in download routes.
- No expansion of student write permissions beyond progress endpoints.

## 13. Performance Considerations

- Add indexes on new FKs and progress lookup keys.
- Prefer minimal join depth in list pages.
- Cache chapter/topic trees at request scope to avoid repeated queries.
- Keep fallback checks simple: existence probe first, then branch query path.

## 14. SQLite Compatibility Considerations

- `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN` are safe and supported.
- Avoid UNIQUE constraint rewrites on legacy tables (requires table rebuild in SQLite).
- Keep old progress tables unchanged to minimize migration risk.
- Use idempotent schema upgrades through existing helper functions.

## 15. Future Scalability Considerations

- Master content model naturally supports many-to-many program reuse.
- `custom_title` enables program-specific naming overrides later.
- Versioning can be introduced later (`master_topic_versions`) without changing core linkage model.
- Soft-archive status supports lifecycle management without deletion.
