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

## Recommended next phases

### Phase 2 — Publishing readiness

- Add a server-side readiness service shared by dashboard, program, and topic pages.
- Block or warn on publishing when visible chapters have no active topics or topics have no lesson.
- Add a program QA checklist and “Preview as student” entry point.

### Phase 3 — Library scale

- Add server-side search, filters, and pagination for chapters and topics.
- Filter by missing lesson, missing assignment, unused chapter, status, and program.
- Add bulk archive, attach, visibility, and ordering operations with safeguards.

### Phase 4 — Editorial governance

- Add draft/published content revisions, change notes, and rollback.
- Add optional reviewer approval before publishing.
- Show author, last editor, and IST timestamps consistently.

### Phase 5 — Legacy retirement

- Finish migrating remaining program-owned chapters/topics.
- Remove obsolete legacy create/edit paths after data verification.
- Keep redirects for bookmarked legacy URLs during a deprecation window.
