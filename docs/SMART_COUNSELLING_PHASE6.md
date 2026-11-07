# Smart Counselling Phase 6 — Deterministic Recommendation Engine

Phase 6 matches a completed Phase 4 prospect assessment against business-approved, recommendation-ready Phase 5 Course Intelligence. It is deterministic, reproducible, versioned, and contains no generative AI, LMS presentation, comparison behavior, follow-up automation, or admission changes.

## Engine architecture and version

`recommendation_engine.py` is a pure business-rules module. It evaluates hard eligibility, calculates applicable weighted factors, builds structured explanations, normalizes scores, and ranks courses. `recommendation_service.py` owns authorization, tenant-scoped loading, atomic persistence, audit events, and API DTOs.

Engine version: `SMART_COUNSELLING_ENGINE_V1`. Every run also snapshots the assessment version, prospect inputs, course name/category, Course Intelligence `updated_at`, factors, explanations, and skills. Later configuration changes create new runs and cannot rewrite historical results.

The CRM `leads.lead_score` is neither read nor updated. Course match score is a separate concept.

## Eligibility before scoring

Only active, tenant-owned profiles where Phase 5 returns `recommendationReady=true` enter the candidate set. The engine then hard-excludes candidates for:

- Minimum education level not met.
- Configured ALLOWED qualification not met.
- Configured ALLOWED stream not met.
- Computer, accounting, Excel, English, or programming prerequisite not met.

Ineligible candidates have `INELIGIBLE` status and structured reason codes. They are persisted for audit but never ranked or returned to the ordinary recommendation list. Preferred education/background relationships never cause exclusion.

Level comparisons use centralized ordered maps; raw labels are never compared alphabetically.

## V1 weights and formulas

Central weights are Career Goal 30, Interests 30, Education 15, Entry Skills 15, and Preferences 10. A dimension participates only when both prospect and course contain reliable structured data. Scores normalize across the actual applicable weight denominator, so missing optional information is neutral.

Phase 5 has no reliable structured course learning-mode or duration-preference mappings, so the Preference 10 dimension is consistently omitted in V1 rather than invented or treated as a mismatch.

Goal strength factors:

- PRIMARY: 1.00
- STRONG: 0.85
- SUPPORTED: 0.65
- WEAK: 0.35

Interest matching is bounded. One matching interest uses its full strength. With two or more matches, the strongest contributes 80% and the second strongest 20%; further selections do not inflate the score.

After hard education eligibility passes, preferred qualification/stream matches contribute 0.70 for one match and 0.85 for two. No preferred match remains eligible with a neutral 0.50 contribution and a consideration.

Entry-skill fit averages available ordered prospect skill levels and compares that value with the Phase 5 suitable starting-level range. Inside the range is 1.00; distance reduces fit by 0.20 per level, with a 0.40 floor. Hard prerequisites always execute first.

Raw weighted sum is divided by the sum of applicable weights and rounded to an integer from 0–100. Missing prospect optional data or missing optional course metadata removes that dimension from both numerator and denominator.

## Thresholds and deterministic ranking

- 90–100: `EXCELLENT_MATCH`
- 80–89: `STRONG_MATCH`
- 70–79: `GOOD_MATCH`
- 60–69: `POSSIBLE_MATCH`
- Below 60: `LOW_MATCH`

Primary recommendations require at least 65 and are limited to three. Eligible courses below 65 may appear in a limited secondary section. If none reaches 65, the run returns `NO_STRONG_MATCH`. “Best Match” appears only for rank 1 at 80 or above.

Tie-breaking is: normalized score descending, raw weighted score descending, goal factor descending, strongest interest factor descending, then course ID ascending. Identical inputs and engine version therefore produce identical ordering.

## Explanations

Matched factors, considerations, and ineligibility reasons are produced from centralized deterministic rule templates and persisted as structured JSON. No LLM or external recommendation service is called. Ordinary staff DTOs receive only human-readable reasons and considerations, not internal weights.

## Persistence and APIs

`recommendation_runs` stores tenant/session/lead/assessment identity, assessment and engine versions, immutable prospect snapshot, status, outcome, actor, and timestamps. `recommendation_results` stores every evaluated ready candidate with course/profile snapshots, rank/score, eligibility, factors, explanations, and skill chips.

Generation and results commit atomically. A failure rolls back both run and results. Recalculation inserts another run; GET loads the latest completed run while preserving history.

- `POST /api/smart-counselling/sessions/<id>/recommendations`
- `GET /api/smart-counselling/sessions/<id>/recommendations`

Both reuse existing session authorization and tenant isolation. Angular never submits scores or course candidates.

## Angular behavior

The Recommendations route now loads the latest persisted run and generates only when none exists. It provides progressive deterministic loading messages, an emphasized qualifying top result, percentage/label, structured reasons, skills, limited secondary suitable courses, explicit no-match review actions, recalculation, and the counsellor-judgment note.

View Course, View Syllabus, and Compare remain disabled Phase 7 placeholders. No LMS content is retrieved.

## Audit events

- `recommendation_started`
- `recommendation_recalculated`
- `recommendation_completed`
- `recommendation_no_match`

Events store only run ID, engine version, and result count where applicable.

## Test fixtures and production data

Golden fixtures cover commerce/accounting job seeking, programming prerequisite exclusion, and communication-course preference. They are explicitly test-only and do not seed or infer production course mappings. Invariants cover hard exclusions, tenant isolation, disabled/not-ready courses, determinism, stable ties, irrelevant fields, bounded interests, missing optional data, history, refresh, CRM lead-score separation, authorization, and transaction rollback.

No real Course Intelligence profile is considered production-trustworthy until reviewed by the business owner and `recommendationReady=true`.

## Migration and release

Apply `migrations/20260822_smart_counselling_phase6.sql` only after Phases 2–5. MySQL/Cloud SQL validation of all migrations in sequence, indexes, constraints, timing, rollback, and API smoke tests remains mandatory before production release.

## Phase 7 input

Phase 7 may use persisted ranked course IDs for course details, existing LMS syllabus presentation, comparison, and explicit course-interest capture. Phase 6 does not implement those behaviors.
