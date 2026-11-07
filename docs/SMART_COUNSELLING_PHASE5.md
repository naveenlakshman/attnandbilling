# Smart Counselling Phase 5 — Course Intelligence

Phase 5 models trustworthy, tenant-scoped course intelligence. It contains no prospect-to-course score, ranking, percentage, Top 3 selection, or recommendation-run persistence.

## Source precedence

- `courses` remains authoritative for identity, name, fee, duration/hours, type, domain/category, active status, and website visibility.
- `course_profiles` owns purpose, audience, eligibility, entry level, certification representation, and the independent recommendation-enabled switch.
- Normalized child tables own values Phase 6 must match deterministically.
- LMS remains authoritative for curriculum/syllabus; Phase 5 exposes only tenant-safe mapping status and program summary.
- Batches remain authoritative for availability; the DTO returns only total and active counts.

No course intelligence is inferred from course names and no production profile data is seeded.

## Schema

- `course_profiles`: exactly one profile per institute/course.
- `course_supported_goals`: Phase 4 goal codes with semantic strength and primary marker.
- `course_supported_interests`: Phase 4 interest codes with semantic strength and primary marker.
- `course_education_suitability`: ALLOWED (hard eligibility set) or PREFERRED qualification/stream codes.
- `course_skill_requirements`: one minimum entry level for COMPUTER, ACCOUNTING, EXCEL, ENGLISH, and PROGRAMMING. `NONE` explicitly means no prerequisite.
- `course_skills_taught`: stable taught-skill codes, distinct from prospect interests.
- `course_profile_items`: ordered LEARNING_OUTCOME, CAREER_OUTCOME, and JOB_ROLE text. These remain editable descriptions and do not promise employment.
- `course_profile_events`: actor, tenant, course, event type, changed top-level section names, and timestamp; full profile content is not copied into logs.

All tables carry `institute_id`. Every API course lookup requires both `course_id` and the active actor's `institute_id`. The service never trusts a route ID alone.

## Taxonomies and validation

Goals, interests, education levels, qualifications, and streams are imported from `questionnaire.py`, the Phase 4 canonical definitions. Display labels are returned separately from stable persisted codes. Taught-skill, starting-level, match-strength, prerequisite-dimension, and dimension-specific level allowlists are backend constants. Flask rejects unknown values before persistence.

Education distinguishes the minimum hard education level from suitable ALLOWED/PREFERRED backgrounds. Preferred prose can explain nuance without turning every relationship into an exclusion. Prerequisites are structured by dimension and must explicitly use `NONE` when no real requirement exists.

## Recommendation readiness

`profileComplete` is true only when the backend finds:

1. A course purpose.
2. At least one supported goal.
3. At least one supported interest.
4. A minimum education level.
5. All five prerequisite dimensions explicitly defined (including `NONE`).
6. At least one taught skill.
7. At least one learning outcome.

`recommendationReady` additionally requires an active course and `recommendation_enabled=true`. LMS mapping, website visibility, and active-batch count are informational and do not independently block readiness.

## Administration and APIs

Course Intelligence is linked from the existing Flask/Jinja Course Administration cards. This keeps Angular limited to Smart Counselling's counselling content area and avoids moving unrelated administration into Angular. The sectioned page covers Overview, Audience & Eligibility, Goals & Interests, Entry Skills, Skills & Outcomes, Certification, and Recommendation.

- `GET /api/smart-counselling/course-profile-taxonomy` — canonical read-only code/label definitions.
- `GET /api/smart-counselling/course-profiles` — tenant course intelligence lookup collection for future Phase 6 consumption.
- `GET /api/smart-counselling/course-profiles/<course_id>` — combined course/profile/LMS/batch/readiness DTO.
- `PUT /api/smart-counselling/course-profiles/<course_id>` — admin-only transactional replacement of one profile and its mappings.
- `GET /smart-counselling/course-intelligence/<course_id>` — admin maintenance page.

Authenticated Smart Counselling staff may read the DTO and taxonomy for future counselling flows. Only active tenant admins may edit. CSRF protects PUT requests. A failed validation or database operation rolls back the whole profile update.

LMS programs are exposed only when their creator belongs to the active institute. Multiple mappings are ordered by `display_order`, then program ID. A missing mapping is reported as `LMS_NOT_MAPPED` and does not block recommendation readiness.

Events are `course_profile_created`, `course_profile_updated`, `recommendation_enabled`, and `recommendation_disabled`.

## Phone and WhatsApp identity policy

`lead.phone` is the sole CRM identity match. `lead.whatsapp` is contact/reference data only and cannot independently link a session. Phase 5 changes matching behavior without rewriting historical lead records.

## Migration and release

Apply `migrations/20260821_smart_counselling_phase5.sql` after Phase 2, Phase 3, and Phase 4. The migration is additive and uses `utf8mb4` for future multilingual prose. Its rollback comments are destructive and must be used only after confirming no Phase 5 data is needed.

MySQL/Cloud SQL validation remains a release blocker until all four migrations are applied sequentially to disposable/staging MySQL and constraints, indexes, timing, rollback, and API smoke tests are recorded.

## Phase 6 input contract

Phase 6 may consume only courses where `recommendationReady=true`, then combine the normalized profile DTO with the versioned Phase 4 prospect assessment. Phase 6—not Phase 5—will implement hard exclusions, weights, ranking, explanations, and persisted recommendation runs.
