# Smart Counselling Phase 3

Phase 3 implements mobile verification and CRM lead identification inside the authenticated staff counselling session. It does not authenticate the prospect and does not create a lead, student, password, token, profile, assessment, recommendation, follow-up, or admission record.

## OTP architecture

- Flask staff authentication remains authoritative.
- Indian mobile input is normalized server-side to E.164 (`+91` plus ten digits).
- OTPs are generated with `secrets.randbelow()` and formatted as six digits, including leading zeroes.
- Only an HMAC-SHA256 digest keyed with `SECRET_KEY` is stored. Plaintext OTPs exist only in process memory while the SMS transport is called.
- Default lifetime: 300 seconds.
- Default maximum attempts: 5.
- Default resend cooldown: 45 seconds.
- A resend invalidates the previous pending challenge and retains history.
- An OTP challenge is bound to institute and counselling session.
- The verified normalized mobile is stored on the counselling session.

## SMS integration

`OtpService` uses the focused transport in `sms_transport.py`. Production can select the existing SMS-Gate transport with `SMART_COUNSELLING_OTP_DELIVERY_MODE=gateway`. Development defaults to `disabled`; tests inject a fake transport and never contact the provider. A delivery failure leaves the challenge `INVALIDATED` with delivery state `FAILED` and never returns it as sent.

## Abuse controls

Defaults are configurable:

- IP: 10 sends/minute and 30 verifies/minute through Flask-Limiter.
- Mobile: 5 sends/hour.
- Staff user: 30 sends/hour.
- Counselling session: 8 sends/hour.
- Resend: 45-second server-authoritative cooldown.
- Verification: 5 attempts, then `LOCKED`.

Production already requires shared Flask-Limiter storage through the application's production configuration validation. In-memory rate-limit storage is test/development only.

## Lead compatibility and identification

Historical `leads.phone` and `leads.whatsapp` values are not rewritten. After OTP verification, records for the active institute are normalized in the Smart Counselling lookup boundary and compared exactly. Name is never used for identity.

- No matches: `NEW`; no lead is created.
- One accessible active or lost lead: `EXISTING_LEAD`; it is linked without changing lead status or lost history.
- One inaccessible lead: `EXISTING_LEAD_RESTRICTED`; no details, reassignment, duplicate, or link.
- Multiple records: `MULTIPLE_MATCHES`; no automatic selection or merge.
- Converted lead/student: `EXISTING_STUDENT`; existing IDs are returned minimally and no admission is started.
- Soft-deleted-only match: `SOFT_DELETED_MATCH`; no automatic restoration.

The identification result is stored on the session so refresh can restore the correct UI state. Active challenge status is available through a safe status endpoint; OTP and OTP hash are never returned.

## Override policy

OTP override is admin-only and requires one of the stable reason codes. `OTHER` also requires a note. Override sets `verification_method=OVERRIDE`, keeps `mobile_verified=false`, does not store a verified mobile, never links a lead automatically, and records an audit event.

## Migration and release

Apply `migrations/20260821_smart_counselling_phase3.sql` manually after the approved Phase 2 migration. SQLite schema application is tested in disposable databases. No migration runs automatically on MySQL startup.

Both Phase 2 and Phase 3 migrations must be exercised against a disposable MySQL/Cloud SQL-compatible environment before production. Confirm backup/PITR, migration timing, schema/indexes/constraints, rollback timing, and application smoke tests. Local MySQL access was unavailable during Phase 3, so this remains a release blocker.

## Phase boundary

The profile button is intentionally disabled and labelled Phase 4. Profile questions, education, career goals, interests, skills, recommendations, LMS, follow-up automation, and admission conversion are not implemented.
