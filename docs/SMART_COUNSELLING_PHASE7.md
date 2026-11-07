# Smart Counselling Phase 7

## Scope

Phase 7 adds counselling-safe course detail, syllabus preview, two-or-three-course comparison, and expressed course interest. It does not add counselling outcomes, follow-up, admission conversion, OTP changes, or recommendation-engine changes.

## Recommendation snapshot and current data

- Rank, score, match label, eligibility, recommendation reasons, and considerations are always read from the latest completed persisted recommendation run.
- Opening course details, comparing courses, or changing interest never recalculates or modifies the recommendation score.
- Course name, status, fee, duration, hours, course intelligence, batches, and LMS syllabus are read from current tenant-owned records.
- A recommended course that later becomes inactive remains visible and is labelled `CURRENTLY_UNAVAILABLE`.

## LMS mapping policy

Only an active, published, non-deleted LMS program owned by the active institute is eligible. When a course has multiple eligible mappings, Phase 7 deterministically chooses the mapping with the lowest `display_order`, then the lowest program ID. The master chapter/topic structure is preferred; the legacy chapter/topic structure is used only when the chosen program has no visible active master chapters.

The preview exposes only program title, ordered chapter titles, ordered topic titles, and an estimated topic duration where the legacy schema provides it. It never returns lesson content, HTML/body fields, resources, assessments, trainer notes, learner progress, enrolment data, or other student data. Missing mappings and empty syllabi return an explicit `NOT_AVAILABLE` response.

## Batch and fee behavior

The details and comparison DTOs return the current course fee and current active batches only. Batches include their display name, branch, date/time window, and status. Phase 7 makes no seat-availability claim.

## Course interest

Interest is stored separately from recommendation results using `INTERESTED`, `HIGHLY_INTERESTED`, or `NOT_INTERESTED`. One row exists per counselling session and course. At most one row per session can be primary; a primary course must be interested or highly interested. Switching the primary choice clears the prior primary in the same transaction. Interest writes keep the tenant, session, lead, recommendation run, course, and acting user references for auditability.

## API surface

- `GET /api/smart-counselling/sessions/<session_id>/courses/<course_id>`
- `GET /api/smart-counselling/sessions/<session_id>/courses/<course_id>/syllabus`
- `GET /api/smart-counselling/sessions/<session_id>/compare?course_ids=1,2`
- `GET /api/smart-counselling/sessions/<session_id>/course-interests`
- `PUT /api/smart-counselling/sessions/<session_id>/course-interests/<course_id>`

All endpoints require the existing Smart Counselling staff authorization and active-institute session authorization. Course IDs must belong to the current persisted recommendation context. Mutations retain the existing JSON CSRF protection.

## UI

Angular routes now include course details and comparison. Recommendation cards support selecting up to three courses, opening course details or syllabus, comparing selected courses, saving interest, and setting a primary choice. Course details show current information alongside the persisted recommendation explanation. Comparison collapses from three columns to two and then one through the shared responsive design tokens.

## Events

Phase 7 records `course_detail_viewed`, `syllabus_viewed`, `comparison_opened`, `course_interest_set`, `course_interest_changed`, and `primary_course_interest_changed` in the existing event stream.

## Migration and rollback

Apply `migrations/20260822_smart_counselling_phase7.sql` only after the Phase 2 through Phase 6 migrations. The generated `primary_session_id` plus unique index enforces one primary choice in MySQL. SQLite test/bootstrap schema uses an equivalent partial unique index. Rollback is destructive and consists of dropping `counselling_course_interests` only after confirming its data is disposable.

## Phase 8 boundary

Phase 7 provides a stable, tenant-scoped primary course-interest signal for Phase 8. Phase 8 must still define and implement counselling outcomes, follow-up workflow, admission hand-off, and their permissions; none are inferred or started here.
