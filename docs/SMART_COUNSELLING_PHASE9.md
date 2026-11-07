# Smart Counselling Phase 9

## Scope delivered

Phase 9 connects completed Smart Counselling journeys to CRM lead detail and adds read-only lead history and management analytics. It does not implement Phase 10 release hardening, background aggregation, or changes to admission ownership.

## CRM integration

The lead detail page loads one focused latest-insight DTO. The card shows the latest session, counsellor, verification state, selected assessment facts, top recommendation, prospect-selected primary course, outcome, next action, follow-up date, session count, and a history link. The recommendation and primary interest remain separate fields.

The CRM lead and student records remain authoritative for current stage, assignment, follow-up, and conversion. Counselling records provide historical context and do not overwrite current CRM state.

## History and timeline

`GET /api/smart-counselling/leads/<lead_id>/history` returns tenant- and actor-authorized history. It batch-loads sessions and related records to avoid per-session queries. The response includes completed, open, and abandoned sessions; safe assessment answers; every completed recommendation run and its persisted score/reason snapshot; interest changes; outcomes; and selected useful events. The newest session is displayed first and expanded initially.

OTP hashes, normalized phone identity, generic raw metadata, and other internal security data are not returned. Course names are resolved from the current tenant course catalogue because Phase 1-8 did not persist a course-name snapshot; historical scores, ranks, labels, and reasons remain the stored values.

## Analytics

`GET /api/smart-counselling/analytics` provides:

- overview totals and session/lead conversion rates;
- funnel stages;
- outcome and follow-up distribution;
- recommended-course and primary-interest distribution;
- recommendation-versus-interest alignment;
- no-suitable-course dimensions;
- counsellor process metrics.

Filters support date range, branch, counsellor, recommended course, and primary course. Dates default to the latest seven calendar days. Admins can filter within authorized tenant scope. Staff are forced to their own counsellor and branch scope and cannot widen it through query parameters.

## Funnel and conversion definitions

The funnel uses explicit units:

- `STARTED`, `VERIFIED`, `ASSESSED`, `RECOMMENDED`, and `COMPLETED` count counselling sessions;
- `CONVERTED` counts unique counselled leads with a current student record.

Session conversion rate is completed sessions whose lead currently has a student record divided by completed sessions. Lead conversion rate is unique counselled leads with a current student record divided by unique counselled leads. Both use the filtered counselling cohort and are reported independently to avoid mixing repeat sessions with prospects.

No exact enrolled-course attribution is claimed: the existing student conversion link identifies the converted lead, but the current schema does not reliably prove which course enrollment resulted from a particular counselling recommendation.

## Performance approach

Analytics uses grouped SQL queries rather than loading complete histories. The lead card uses a dedicated latest-record query. History uses bounded batch queries. Migration `20260822_smart_counselling_phase9.sql` adds a tenant/date/branch/counsellor/outcome composite index for the primary analytics access path. No summary table is introduced in Phase 9.

## Authorization and tenant isolation

Every history and analytics query begins with the active institute. Lead history additionally enforces branch visibility and existing lead-assignment access. Filter option lists are generated inside the same authorized scope. Cross-tenant records return not found, while known in-tenant but unauthorized records return forbidden.

## Known limitations and Phase 10 readiness

- Course display names are current catalogue values, not historical name snapshots.
- Conversion is lead/student based; exact course-enrollment attribution is unavailable.
- Counsellor metrics describe counselling process performance and do not attribute admissions to a counsellor.
- Large-production-volume query plans and MySQL migration application must be validated during Phase 10 deployment hardening.
- Visual dashboards use dependency-free CSS bars and funnels; no chart library was added.

Phase 9 is structurally ready for Phase 10 once the MySQL migration is applied and verified in the target environment.
