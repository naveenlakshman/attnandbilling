# Smart Counselling Phase 8

## Scope and boundaries

Phase 8 records a structured counselling outcome, validates the next action, creates an existing CRM follow-up when required, completes the session atomically, and provides a guarded handoff to the existing admission form. It does not create a student, invoice, payment, batch assignment, calendar platform, new CRM, or Phase 9 insights UI.

Course fit, prospect interest, counselling outcome, next action, and CRM lead temperature remain separate concepts. Recommendation scores and Phase 7 interests are not changed by outcome completion.

## Central outcome policy

The stable codes and their server-controlled rules live in `modules/smart_counselling/outcome_policy.py`. Angular receives labels, allowed reasons, allowed next actions, primary/interest requirements, and follow-up requirements from the API rather than reproducing the business rules.

V1 outcomes are `READY_FOR_ADMISSION`, `DEMO_REQUESTED`, `FOLLOWUP_REQUIRED`, `PARENT_DISCUSSION_REQUIRED`, `FEE_CONCERN`, `TIMING_CONCERN`, `COMPARING_OTHER_INSTITUTES`, `NOT_READY`, `NOT_INTERESTED`, and `NO_SUITABLE_COURSE`.

V1 deliberately requires a dated follow-up for demo requests, explicit follow-up, parent discussion, fee/timing concerns, comparison with other institutes, and not-ready prospects. A `NOT_INTERESTED` outcome creates no follow-up when its action is `NO_FURTHER_ACTION`, but staff may explicitly choose `CALL_BACK` with a valid date. `READY_FOR_ADMISSION`, fee concern, and timing concern require the selected primary interested course; rank #1 is never assumed to be the prospect's choice.

Structured reasons are supported for fee concern, timing concern, and not interested. `OTHER` requires a concise staff-note clarification.

## Existing CRM integration

Required actions insert into the existing tenant-owned `followups` table with method `Smart Counselling`, the stable outcome code, the exact next date, the acting user, and the linked lead. The lead's `last_contact_date`, `next_followup_date`, `followup_count`, and stage are updated in the same transaction. Follow-up outcomes use stage `Follow-up`; completed counselling without a new follow-up uses `Counseling Done` for an otherwise active lead.

`PARENT_DISCUSSION_REQUIRED` changes `parent_discussion_status` to `Scheduled` only when the existing value is blank, `Pending`, or `Not Required`; completed/rejected historical states are not downgraded.

The free-text `leads.interested_courses` field is not updated. `counselling_course_interests` remains authoritative. `NOT_INTERESTED` does not mark the lead Lost, clear an existing lost reason, or make another irreversible CRM lifecycle change. Existing lead score and temperature logic are not recalculated or overwritten.

An existing lead activity entry is written with the outcome code, while detailed Phase 8 lifecycle data remains in the counselling event stream. Staff notes and other PII are excluded from event metadata.

## Completion transaction and idempotency

Completion obtains a write lock through the session row, re-reads terminal state, validates the latest completed recommendation context and Phase 7 interests, validates the outcome/reason/action/date, creates any required CRM follow-up, updates permitted lead summaries, saves the normalized session outcome, records events, and sets `COMPLETED`/`completed_at` before one commit. Any error rolls the operation back.

`counselling_sessions.completion_followup_id` is the durable link to the one CRM follow-up created by the completion. A repeated completion returns the existing summary without changing `completed_at`, creating another follow-up, or adding completion events. Completed/abandoned sessions reject normal profile, assessment, recommendation, interest, and outcome writes.

## Admission handoff and converted race

Admission is available only after a completed `READY_FOR_ADMISSION` session whose lead is not converted. The handoff endpoint re-checks the current tenant-owned lead/student state and returns `/billing/student/new?from_lead=<lead_id>`. It does not create a student. If another process has converted the lead, the response reports that the prospect is already registered and supplies the existing student link when one is present.

## APIs

- `GET /api/smart-counselling/sessions/<id>/outcome`
- `PUT /api/smart-counselling/sessions/<id>/outcome`
- `POST /api/smart-counselling/sessions/<id>/complete`
- `GET /api/smart-counselling/sessions/<id>/summary`
- `POST /api/smart-counselling/sessions/<id>/admission-handoff`

All endpoints use existing Smart Counselling staff, branch, session-owner, tenant, and CSRF controls.

## Migration

`migrations/20260822_smart_counselling_phase8.sql` additively introduces only `completion_followup_id`, its tenant lookup index, and its foreign key. Apply it after Phase 2–7 migrations against an approved staging/disposable MySQL database. Production credentials must not be borrowed to bypass the current validation blocker.

## Phase 9 preparation

The completed-session summary includes prospect, verification, qualification, primary goal, top persisted recommendation, primary and other interests, normalized outcome/reason/action, follow-up date, counsellor, completion time, follow-up link, and admission/student state. This is sufficient backend context for Phase 9 history and insights without implementing that UI now.
