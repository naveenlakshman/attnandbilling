# Smart Counselling Phase 4

Phase 4 collects structured prospect profile and counselling assessment data. It does not calculate recommendations, eligibility, course fit, weights, scores, or course filters.

## Data model

- Core CRM fields remain on `leads`.
- `counselling_assessments` stores one versioned assessment per counselling session.
- `counselling_assessment_answers` stores only backend-approved question keys and validated scalar or multi-select JSON values.
- `counselling_lead_creation_requests` serializes and records new-lead creation by counselling session.
- `counselling_sessions.identity_mobile_normalized` preserves the authoritative mobile used by either OTP or authorized override. OTP verification remains separately represented by `mobile_verified` and `verification_method`.

Assessment version: `SMART_COUNSELLING_V1`.

## New lead creation

A new lead is created only after name, sensible age, education status, qualification, current situation, branch, counsellor, source, and counselling identity exist. The phone is derived from the authoritative session identity, never from the Angular profile payload.

Creation, session linking, creation-ledger completion, assessment creation, state advancement, and events commit together. A no-op update locks the counselling-session row before checking/creating the lead, and the ledger has a unique session key. Retried profile saves reuse the linked lead.

The existing CRM source `Walk-in` is preserved for reporting. The `new_lead_created` event records internal origin `SMART_COUNSELLING` without adding a duplicate lead-source label.

Override-created leads retain `mobile_verified=false` and `verification_method=OVERRIDE`.

## Existing lead updates

Existing values are prefilled. Only the controlled CRM fields that actually changed can be updated, and every changed field must be explicitly included in `confirmedFields`. Omitted fields are not erased. Lead assignment, phone, source, status, lost reason, conversion state, and history cannot be changed through this API.

Converted/student identification remains read-only. Returning lost leads may be counselled, but their lost status and reason are preserved.

## Taxonomies and completeness

The questionnaire endpoint supplies all UI codes and labels. Flask validates every submitted code. Profile completeness and assessment completeness are backend-calculated. Programming experience becomes required only when `PROGRAMMING` is among the interests.

Logical save boundaries are Profile, Goals/Interests, and Skills. Every GET reconstructs persisted progress, allowing refresh and resume without browser-history assumptions.

## WhatsApp identity policy

Phase 5 resolves the product decision: only exact normalized `leads.phone` matches establish CRM identity. `leads.whatsapp` is supporting contact/reference data and never independently links a counselling session. Historical lead records are not rewritten. Multiple primary-phone matches remain unresolved and are never selected automatically.

## Migration and release

Apply `migrations/20260821_smart_counselling_phase4.sql` manually after Phases 2 and 3. No production database was changed during development. Disposable SQLite tests cover schema application, rollback behavior, idempotency, tenant isolation, and assessment persistence.

MySQL/Cloud SQL migration validation remains mandatory before release: execute Phases 2, 3, and 4 in sequence against disposable/staging MySQL, record timings, verify constraints and indexes, exercise rollback, and run API smoke tests. The configured local PyMySQL connection remains unavailable, so this is a release blocker.

## Phase boundary

The recommendations URL is a completion shell only. Phase 5 must define trustworthy course intelligence before Phase 6 can introduce weighted recommendations.
