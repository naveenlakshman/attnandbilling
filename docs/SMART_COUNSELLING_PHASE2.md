# Smart Counselling Phase 2

Phase 2 adds the tenant-safe counselling session lifecycle. It does not add OTP,
assessment, recommendation, LMS, comparison, follow-up, or admission behavior.

## Schema

`counselling_sessions` is the source of truth. Sessions start unlinked in
`IDENTIFICATION_PENDING`; a placeholder lead is never created. Fields for future
verification, lead/course interest, outcome, and follow-up integration remain
nullable until their owning phases.

`counselling_events` is append-only by application contract. The repository has
an insert operation only. Events contain controlled lifecycle metadata, never
mobile numbers, names, notes, OTP values, or arbitrary request payloads.

Indexes support tenant dashboard/status queries, branch-scoped access,
counsellor resume lists, lead history, and chronological event lookup.

## State machine

```text
STARTED -> IDENTIFICATION_PENDING -> IDENTIFIED -> IN_PROGRESS
        -> OUTCOME_PENDING -> COMPLETED
```

Any non-terminal state may transition to `ABANDONED`. `COMPLETED` and
`ABANDONED` are terminal. Phase 2 creates sessions directly in
`IDENTIFICATION_PENDING`; the `STARTED` code is retained as a stable import or
future orchestration state.

## Authorization

- Flask staff session, active database user, active tenant, and
  `smart_counselling` subscription feature are verified on every route.
- Every lookup includes `session.id + institute_id`.
- Branch-restricted actors are limited to their active branch.
- Staff can access only their own sessions; administrators retain their existing
  branch/all-branch scope.
- A linked lead must also pass the existing assignment policy. Leads assigned to
  another counsellor are denied without disclosure or automatic reassignment.

The eventual cross-counsellor reassignment workflow remains a Phase 3+ product
decision. Phase 2 uses the secure deny-by-default behavior.

## Migration

MySQL migration: `migrations/20260821_smart_counselling_phase2.sql`.

Production steps:

1. Confirm backup/PITR and the target Cloud SQL instance.
2. Connect using the project's approved Cloud SQL Auth Proxy/MySQL workflow.
3. Inspect for table-name conflicts.
4. Apply the migration manually to the intended environment.
5. Verify both tables, foreign keys, indexes, and a transactional smoke test.
6. Deploy application code only after schema verification.

Do not depend on Cloud Run startup to apply this migration. Emergency rollback
is destructive: back up first, then drop `counselling_events` followed by
`counselling_sessions`. Normal rollback should instead redeploy the previous
application revision while retaining the additive tables.
