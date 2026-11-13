# Isolated Meta staging receiver candidate

Prepared 13 November 2026 on local branch `codex/meta-leads-review`.
This is a local candidate. **No callback was registered, no Page subscribed,
no IAM changed, no cloud resource deployed, and no production or prospect
messages enabled.** The live synthetic retrieval gate remains blocked.

## Readiness by gate

| Gate | Result | Evidence/limit |
|---|---|---|
| Local receiver | **Ready for code review** | SQLite inbox, HMAC verification, off-by-default switch, approved-ID allowlist, redacted audit, retries, controls. |
| Local tests | **15 passed** | Flask test client and temporary SQLite files; test list below. These are local tests only. |
| Synthetic lead visibility | **Blocked** | Prior successful read-only checks found the intended app's form test registry empty twice. The visible native status row was Zoho only, pending, with no payload/lead ID. Current Page token is now invalid. |
| Synthetic answer retrieval | **Not tested** | Probe correctly stopped before requesting answers because the ID was not in the test registry. |
| Webhook delivery | **Not configured** | Read-only Meta checks returned empty app and Page subscriptions. |
| Production credential readiness | **Not ready** | Read-only token debug on 13 November says the pinned Page token is invalid/expired. No production identity or eligible long-lived production token has been established. |

## Receiver behavior

`staging/meta_lead_receiver/receiver.py` exposes `GET` and `POST /webhook/meta`
and `GET /healthz`. The module has no production enquiry, messaging, or Meta
lead-fetch implementation.

- Webhook verification compares the configured verification token in constant
  time. `POST` verifies `X-Hub-Signature-256` as HMAC-SHA256 over the exact raw
  request body before parsing.
- Body size is limited to 64 KiB. The receiver accepts only Page leadgen
  notifications for the explicit Page and Form, and only lead IDs in the
  configured synthetic-ID allowlist. IDs outside that set are discarded after
  a redacted ignored-count audit. The allowlist never learns IDs from callbacks.
- SQLite uses a file-backed WAL inbox, unique lead ID, atomic batched inserts and
  redacted count-only audit rows. It never stores raw bodies or answer values.
  Redacted local verification evidence is kept outside Git for 30 days after
  this candidate review, then deleted unless an incident hold is opened.
- The worker claim is transactional and leased. Failures use bounded exponential
  retry; after five attempts an item moves to `DEAD`. Safe error codes only are
  retained. Controlled replay accepts only an allowlisted ID and records an audit
  count. A processor receives IDs and metadata only; none is wired to ERP.
- The disable switch is `META_STAGING_ENABLED`, default `false`. Disabled mode
  rejects verification and delivery. Operators must restart with the switch off
  to stop intake; already queued rows remain on disk for inspection/recovery.
- Terminal notifications and count-only audit rows are retained for 30 days.
  Pending/retrying rows are preserved until resolution rather than silently
  deleted at the retention boundary. Back up the staging database securely,
  restrict filesystem access, and never copy it into the production database.

Local tests cover verification success/failure and disable behavior, missing and
incorrect signatures, raw-body tampering, malformed envelopes, duplicate and
batched notifications, ignored real/unapproved IDs, durable reopen, no answer
storage, oversized-body rejection, storage failure with retryable HTTP response, worker retry/backoff,
dead-letter and controlled replay, redacted health and retention pruning.

## Important deployment limitation

The local store is SQLite. Cloud Run container files are not durable storage,
so this candidate **must not be deployed unchanged**. Before staging deployment,
replace the SQLite store with a staging-only Cloud SQL adapter and rerun the
same tests against disposable MySQL 8.0.45. Use an independent database instance,
not the production instance or production schema. Implement and test worker
process packaging and job scheduling before any webhook subscription. The current
candidate has only an injected worker function, no scheduled worker service.

The signed body authenticates that Meta sent a notification; it does not prove
that the lead ID is synthetic. The allowlist must be populated only after an
administrator has established the synthetic test ID through supported evidence.
Until then it stays empty and all callbacks are ignored.

## Proposed hosting and resource names

These are proposed names only; none exists as part of this candidate:

- Cloud Run receiver: `global-it-meta-leads-staging-receiver`.
- Dedicated Cloud SQL staging instance: `global-it-meta-leads-staging-db`.
- Database: `meta_leads_staging`; dedicated least-privilege DB principal.
- Separate Cloud Run worker/job after packaging: `global-it-meta-leads-staging-worker`.
- Region proposal: `asia-south1`, subject to the owner's existing data-location policy.
- Proposed callback shape: `https://<staging-service-host>/webhook/meta`.
  **This URL does not exist yet.** Do not enter it in Meta until a reviewed
  candidate is deployed and verified over HTTPS.

## Credential references and IAM for a future staging deployment

Use pinned versions and keep payloads out of Git and chat:

- `projects/644631083795/secrets/meta-erp-leads-staging-page-token/versions/<n>`
- `projects/644631083795/secrets/meta-erp-leads-app-secret/versions/<n>`
- Proposed, not created: `meta-erp-leads-staging-verify-token` in project `644631083795`.

At the last live check, versions 1 of the Page token and App Secret existed. The
Page token version 1 is now invalid according to Meta's read-only `debug_token`
check on 13 November 2026. Do not treat it as a deployment credential. Provision
a fresh eligible staging token only after app access is resolved and select a
rotation/expiry owner. No credential value was printed or written into this branch.

The future receiver service account needs Secret Accessor on only the App Secret
and verification-token secrets. The worker may need Secret Accessor on the Page
token, but only if a separately reviewed staging processor retrieves an approved
synthetic lead. Neither identity needs Secret Manager Admin. Grant Cloud SQL
Client only to service identities that connect to the staging instance. No IAM
binding has been created.

## Deployment sequence for later review

1. Resolve the test-ID provenance/visibility discrepancy and review this code.
2. Implement the Cloud SQL staging adapter, staging worker packaging, and
   candidate container. Test migrations, concurrent duplicate intake, retry
   leases, restart recovery, disable, retention and tenant isolation locally.
3. Create the separate staging DB, service identities and pinned staging secrets;
   apply only reviewed secret-level IAM. Store and approve the allowlisted test ID.
4. Build an immutable image. Deploy the receiver with zero Meta subscriptions,
   `META_STAGING_ENABLED=false`, private ingress/appropriate access controls,
   and verify health, signatures and storage using local synthetic requests.
5. Review the exact HTTPS callback, candidate image digest, IAM diff, logs and
   rollback plan. Only after separate approval may an admin configure the app
   callback and Page subscription for the explicitly synthetic test. Keep any
   real-lead IDs outside the allowlist and never fetch them.
6. Run one approved native synthetic notification and verify receipt, dedup,
   worker retry, answer retrieval only if separately approved, no ERP writes and
   no outgoing messages. Production ingestion remains off.

## Disable and recovery

1. Set `META_STAGING_ENABLED=false` and restart the staging receiver; this
   immediately blocks verification and callbacks. If service access is suspect,
   scale the staging receiver to zero. Do not alter production services.
2. If Meta delivery was enabled during an approved staging test, disable the
   staging callback/Page subscription through the reviewed staging configuration.
   Do not remove unrelated Zoho, Interakt or other CRM connections.
3. Preserve the staging DB and redacted logs. Inspect queue counts and safe error
   codes. Correct code/config first; do not delete IDs or replay unapproved items.
4. Restore a reviewed immutable image and staging DB backup. Re-enable only with
   `META_STAGING_ENABLED=true` after health, signature and dedup checks pass and
   the synthetic allowlist is revalidated. Every manual replay must be audited.

## Live Meta discrepancy

Current supported GET evidence and the boundary of that evidence are recorded in
[`META_LEADS_ACCESS_FINDINGS.md`](META_LEADS_ACCESS_FINDINGS.md). No test ID was
invented, no real-submission lead edge was queried, and no third-party CRM or
existing Meta test record was modified.

On 13 November, a read-only `debug_token` call using the pinned secret references
confirmed that the Page token belongs to the intended app and has the
`leads_retrieval` and `pages_manage_metadata` grants, but `is_valid=false`.
Because it is expired, this diagnostic stopped before querying Page/form/test
registry or subscription edges. The last successful reads on 12 November remain
the evidence for the empty synthetic registry and absent subscriptions. No
synthetic answers were requested and no Meta writes were made.
