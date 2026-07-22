# LMS Content Authoring UX Audit

## Intended workflow

1. Create reusable chapters and topics in **Master Library**.
2. Add a lesson (PDF, rich text, or interactive image), with optional video and assignments.
3. Create a **Program** and attach reusable chapters in the required order.
4. Preview the topic in a program context, map the program to a billing course, and publish it.
5. Monitor student progress, submissions, and the review queue.

## Issues found

| Priority | Issue | User impact | Status |
|---|---|---|---|
| High | Dashboard counted legacy program-owned chapters/topics instead of the active Master Library | Staff could not trust the content overview | Fixed |
| High | No clear end-to-end authoring sequence | Staff had to infer where to start and what came next | Fixed |
| High | Topic editor did not show whether essential lesson content was missing | Incomplete topics could be mistaken for student-ready content | Fixed |
| High | No direct program-context preview from the topic content screen | Verification required navigating back through Programs | Fixed |
| Medium | Stale compatibility notice said editor wiring was still pending | Confusing and contradicted the working editor | Fixed |
| Medium | Dashboard activity dates used raw database/server timestamps | Inconsistent with the application-wide IST standard | Fixed |
| Medium | Admin-only course mapping was not explained to staff | Staff could reach a hand-off point without knowing the next owner | Fixed with role-aware guidance |
| Medium | Unused reusable chapters, draft programs, and missing lessons were not surfaced as work items | Content cleanup and publishing readiness were difficult to prioritize | Fixed on dashboard |
| Medium | Legacy and Master Library routes/templates still coexist | Maintenance complexity and occasional navigation ambiguity remain | Future phase |
| Medium | Content lists use client-side filtering and limited readiness filters | Large libraries will eventually need server-side search and pagination | Future phase |
| Low | Publishing has no formal checklist or approval state | A program can be published without a structured QA sign-off | Future phase |
| Low | No version history or draft revision per content item | Editors cannot compare or restore lesson revisions | Future phase |

## Changes delivered in this phase

- Replaced misleading legacy metrics with active program and Master Library metrics.
- Added missing-lesson, unused-chapter, and draft-program work indicators.
- Added a four-step, role-aware Content Authoring Workflow.
- Added topic readiness status for video, lesson, and assignment slots.
- Added direct student preview when a topic belongs to a visible active program.
- Added a clear **Attach to Program** action when no preview context exists.
- Replaced the stale compatibility warning with current workflow guidance.
- Formatted recent LMS activity using the shared IST formatter.

## Phase 2 — Publishing readiness (completed locally)

- Added a reusable server-side readiness service for program publishing decisions.
- Required an active course, a visible chapter, active topics in every visible chapter, and lesson content for every active topic.
- Made every new program start safely as a draft.
- Enforced readiness on the backend even if a publish request bypasses the browser UI.
- Added an actionable QA checklist, links to topics missing lessons, and a “Preview as student” entry point.
- Added MySQL regression coverage for blocked and successful publishing paths.

## Recommended next phases

### Phase 3 — Library scale (completed locally)

- Replaced browser-only filtering with MySQL-backed chapter and topic search, filtering, and pagination.
- Added chapter filters for status, used/unused state, and linked program.
- Added topic filters for status, missing lesson, missing assignment, and lesson-ready content.
- Added guarded bulk chapter attachment with duplicate and archived-item handling.
- Added guarded bulk chapter/topic archive actions that protect content used by published programs.
- Added bulk show/hide and move-to-top/bottom controls for linked program chapters.
- Disabled full-list drag ordering while filters or pagination are active to prevent partial-list data loss.
- Added MySQL regression coverage for filtering, pagination, bulk actions, permissions, and safeguards.

### Phase 4 — Editorial governance (completed locally)

- Added immutable content revisions with change notes and complete content snapshots.
- Added optional “Submit for admin approval” editing that leaves the current student version unchanged.
- Added a centralized admin Editorial Review Queue with approve and reject decisions.
- Added stale-revision protection so an older pending edit cannot overwrite newer approved work.
- Added revision history and administrator rollback, recorded as a new auditable revision.
- Preserved historical uploaded files so file-based lesson revisions remain recoverable.
- Added author, last editor, pending-review state, reviewer identity, and IST timestamps.
- Added a reproducible MySQL migration and SQLite development schema.
- Added MySQL regression coverage for revisions, approval, rejection, stale reviews, rollback, and identity.

### Phase 5 — Legacy retirement (completed locally)

- Fixed the migration dashboard to detect partially migrated chapters and untagged content, not only completely unmapped chapters.
- Made chapter migration resumable and idempotent: it repairs mapped content, migrates only missing topics, reuses the existing master chapter, and avoids duplicate program links.
- Migrated the final local gap: 8 topics and 4 content rows in CCOM Module 5; local verification now reports zero unmapped topics and zero untagged content.
- Retired direct legacy chapter/topic/content writes while retaining compatibility redirects for bookmarked URLs.
- Added the canonical `/lms_admin/legacy-migration` route while retaining the former rollout URL during the deprecation window.
- Corrected MySQL behavior so the application does not attempt an invalid SQLite backup; MySQL migration remains non-destructive and retains all source rows.
- Added a reusable SQL retirement verification script and MySQL regression coverage for partial migration, repair, idempotency, redirects, and write retirement.
- Retained legacy tables as read-only compatibility storage because master content still uses the legacy `topic_id` bridge; table removal requires a separate schema transition.
