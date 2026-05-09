# Legacy LMS Decommission Plan (Step-by-Step)

## Objective
Safely decommission legacy LMS chapter/topic paths after full migration to master-linked architecture, without breaking production admin or student flows.

## Current Status
- All programs appear fully mapped to master content.
- Legacy chapter/topic routes and templates are still present and active in code paths.
- Immediate schema deletion is risky until route/template dependencies are removed.

## Guiding Principles
1. No direct destructive schema changes until dependency checks pass.
2. One phase per deployment cycle.
3. Mandatory verification gate after each phase.
4. Backup before every high-impact phase.

## Scope
- Included:
  - Admin UI simplification
  - Legacy write-blocking
  - Student read-path unification
  - Progress/analytics unification
  - Final route/template and schema cleanup
- Excluded for now:
  - Immediate drop of legacy tables in production

## Phase A: Visibility Cleanup (No Data Risk)
Goal: remove user-facing migration clutter while keeping system behavior stable.

Steps:
1. Hide Phase 6 Rollout from sidebar navigation.
2. Keep Phase 6 route available only to super-admin.
3. Hide/collapse Legacy Program Chapters block when unmigrated count is zero.
4. Add migration-complete read-only notice on affected admin pages.

Verification:
1. Admin menu no longer shows rollout to standard users.
2. Programs and chapter pages load without errors.
3. No behavior change in topic/content access.

Rollback:
1. Re-enable sidebar item.
2. Remove guard and redeploy.

## Phase B: Block New Legacy Writes (Low Risk)
Goal: freeze legacy growth.

Steps:
1. Disable legacy chapter create/edit routes and buttons.
2. Disable legacy topic create/edit routes and buttons.
3. Redirect users to master-link workflows.
4. Add server-side guards so direct URL access cannot create legacy data.

Verification:
1. No new records inserted into legacy chapter/topic tables.
2. Existing records remain readable.
3. Admin can still manage master-linked content.

Rollback:
1. Temporarily restore legacy write routes/buttons.

## Phase C: Student Read Path Unification (Medium Risk)
Goal: make student runtime rely on master-linked graph first.

Steps:
1. Move student program summary queries to master-linked source.
2. Move chapter/topic fetch logic to master identity.
3. Keep temporary compatibility branch for edge legacy references.
4. Remove fallback branch only after data readiness gate passes.

Verification:
1. Student dashboard and program launch work for all assigned programs.
2. Topic open and completion updates work.
3. No missing-topic or missing-progress errors in logs.

Rollback:
1. Re-enable compatibility fallback path.

## Phase D: Progress and Analytics Unification (Medium Risk)
Goal: use one consistent topic identity for metrics.

Steps:
1. Route progress summaries to master-topic progress source.
2. Reconcile legacy vs master progress counts.
3. Update admin and student analytics queries to same source.

Verification:
1. Progress values are consistent across admin and student views.
2. No duplicate or orphan progress entries.

Rollback:
1. Switch analytics back to previous mixed-source query paths.

## Phase E: Data Readiness Gate (High Impact Checkpoint)
Goal: prove safety before deletion.

Required checks:
1. Unmigrated legacy chapters count is zero for all programs.
2. No orphaned topic content references.
3. No orphaned progress references.
4. No active route/template still requiring legacy-only entities.

Operational steps:
1. Run SQL guardrail queries.
2. Save output report.
3. Create production backup checkpoint.

Pass criteria:
1. All checks pass.
2. Stakeholder sign-off received.

## Phase F: Route and Template Decommission (High Risk)
Goal: remove legacy code surface.

Steps:
1. Remove legacy-only template sections.
2. Remove legacy-only admin routes/helpers.
3. Remove rollout endpoints when no longer needed.
4. Keep monitoring for missing endpoint hits.

Verification:
1. Admin pages load with no missing route/template errors.
2. Student pages unaffected.
3. Error log remains clean.

Rollback:
1. Restore previous route/template bundle from last release.

## Phase G: Schema Cleanup (Final)
Goal: remove legacy schema after code dependency removal.

Steps:
1. Backup production database.
2. Execute controlled schema cleanup migration.
3. Validate row counts and foreign-key integrity.
4. Run full smoke tests.

Verification:
1. No schema-related runtime errors.
2. All core LMS workflows pass.

Rollback:
1. Restore pre-cleanup backup.
2. Redeploy previous stable code.

## Verification Matrix (Use Every Phase)
1. Admin:
- Programs list
- Program view
- Program chapters
- Topic list
- Topic content create/edit/view
2. Student:
- Dashboard
- Program open
- Topic open
- Mark complete
- Progress summary
3. Data:
- Orphan checks
- Duplicate checks
- Mapping integrity
4. Logs:
- No traceback spikes
- No sqlite schema errors
- No missing route/template errors

## Execution Order and Control
1. Execute one phase at a time.
2. Do not start next phase without verification sign-off.
3. Keep one backup per phase checkpoint.
4. Schedule Phase F and Phase G in low-traffic windows.

## Decision Notes
- Recommended now: start with Phase A only.
- Not recommended now: deleting legacy tables immediately.
- Cleanup trigger: only after Phase E passes and signs off.
