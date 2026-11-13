# Meta leads production rollout evidence

Date: 2026-11-13 (Asia/Kolkata)

## Scope and safety state

The Meta receiver and worker are isolated Cloud Run resources. They do not run
inside the ERP web service. Runtime schema migration is disabled: SQL in
`staging/meta_lead_receiver/migrations/001_inbox.sql` is applied separately.

The first deployment must use both `META_STAGING_ENABLED=false` and
`META_STAGING_VERIFY_ENABLED=false`. The worker job must also use
`META_STAGING_ENABLED=false`. No Scheduler job, Meta callback or Page
subscription is created until the mapping gate below is resolved and a disabled
candidate has passed its checks.

## Production mapping gate

Read-only verification against `global_it_erp_production` found:

- institute 1: Global IT Education, active, Asia/Kolkata;
- branch 2: Hoskote Branch (`HB`), active;
- course 43: `DFA 2026 With AI for Accounting`, active, but records 180 hours;
- advertised offer: 225 hours, 2026-11-18 through 2027-04-10, 12:00-14:00;
- no course-43 batch exactly matches those dates and times;
- active Hoskote staff candidates exist, but no counsellor selection has been
  explicitly approved for this campaign.

Production processing remains disabled until an owner resolves the 180/225-hour
discrepancy, creates or identifies the exact batch without changing records
silently, and approves one counsellor. The worker validates all mapping IDs and
the exact batch schedule again inside the enquiry transaction.

## Resources and connection budget

- project: `global-it-edu-app` (`644631083795`)
- region: `asia-south1`
- Cloud SQL: `global-it-erp-production-db`
- database: `meta_leads_inbox`
- receiver: `global-it-meta-leads-receiver`
- worker job: `global-it-meta-leads-worker`
- Artifact Registry image: `asia-south1-docker.pkg.dev/global-it-edu-app/cloud-run-source-deploy/meta-leads-receiver`
- service identities: `meta-leads-receiver` and `meta-leads-worker`

Receiver deployment is limited to one instance, concurrency two and one
Gunicorn process with two threads. The worker job is limited to one task and one
parallel execution; a MySQL advisory lock additionally rejects overlap. Maximum
Meta workload database connections are four: two receiver request connections,
one worker advisory-lock connection and one worker operation connection.

The receiver database principal has inbox INSERT/SELECT access only. The worker
principal has inbox processing rights. Production ERP writes require narrowly
scoped SELECT/INSERT rights on the validated ERP tables; they are not granted or
used while production processing is disabled.

## Disable, recovery and rollback

1. Set receiver `META_STAGING_ENABLED=false`; keep verification disabled unless
   Meta must verify a reviewed callback.
2. Keep the worker job `META_STAGING_ENABLED=false` and delete or pause any
   Scheduler trigger before changing revisions.
3. Remove the Page subscription before disabling an enabled production flow so
   notifications are not acknowledged and discarded.
4. Route the receiver tag/traffic to the last accepted immutable revision for an
   ordinary code rollback. Update the worker job to the matching immutable image.
5. Preserve `meta_leads_inbox` records. Do not restore the database for an
   ordinary code rollback. Database restoration is a separate incident action
   and must account for accepted notifications and ERP enquiries created after
   the restore point.
6. After token revocation, keep processing disabled, add a replacement pinned
   secret version, validate the intended app/Page/form and one allowlisted
   synthetic lead, then update the revision. Never overwrite the old version.

Inbox DONE/DEAD records and redacted audit rows are retained for 30 days. A
controlled replay requires an explicit lead-ID allowlist and is audit logged.

## Incremental cost assumption

The existing Cloud SQL compute is reused, so no new database compute charge is
introduced. At this campaign's low volume, Cloud Run requests/jobs and Artifact
Registry storage are expected to be within free allowance or only a few rupees
per month; Secret Manager access/storage is also expected to be a few rupees.
No Scheduler cost exists while the mapping gate is open. Actual billing must be
checked after rollout because free-tier usage is shared by the project.

## Callback and subscription

The callback is not active merely because it appears here. Its proposed shape is:

`https://global-it-meta-leads-receiver-644631083795.asia-south1.run.app/webhook/meta`

After all gates pass, register it on app `1626775252463463`, subscribe Page
`300480973645515` to `leadgen`, and verify form `1806095097277660` with synthetic
lead `1572484097979419`. Existing test records and third-party CRM connections
must not be removed or changed.

## Actual rollout result — 2026-11-13

The controlled rollout stopped at the production-mapping gate. The isolated
production resources are installed but disabled:

- runtime source commit: `a61317a8febcd1a03f8571f16a65d95be008ed41`;
- immutable image digest:
  `sha256:33d5212da445c137a1fd7bf665d974510c8772920608b46ca7e6b187b3e41a49`;
- receiver revision: `global-it-meta-leads-receiver-00011-qoj`, 100% traffic,
  private, `META_STAGING_ENABLED=false`, verification disabled;
- worker job: `global-it-meta-leads-worker`, one task/parallelism one, disabled,
  with no Scheduler trigger;
- restore point: successful on-demand Cloud SQL backup `1794547932326`;
- database: `meta_leads_inbox`; the migration was applied twice and contains
  `notifications` and `audit`;
- pinned secrets: app secret version 1, system-user token version 1, and
  verify/receiver-password/worker-password version 3.

IAM additions are Cloud SQL Client for the two runtime service accounts,
secret-level accessor only for each identity's required secrets, and Cloud Run
Invoker for the release administrator on the private receiver. No `allUsers`
invoker was added.

Final tests on MySQL 8.0.45: 37 focused tests passed. The repository `tests/`
suite passed 331 tests with 22 documented skips. The private synthetic check
rejected an invalid signature (401), accepted one correctly signed allowlisted
notification, and completed synthetic retrieval with four redacted field names
and an answer-value hash. No answer values were stored and `erp_lead_id` remains
null. No ERP enquiry was created.

The first worker execution failed because its four command arguments were
rendered as one string. The job was disabled, the rendered specification was
corrected, and execution `global-it-meta-leads-worker-lb7bw` then succeeded.
The final job configuration was restored to disabled.

Live Meta delivery was not tested: the intended app currently has no webhook
subscription and the Page has no subscribed apps. The current system-user token
is valid for app `1626775252463463` and expires at 2027-01-12 01:44:38 UTC
(07:14:38 Asia/Kolkata). Renewal ownership must be assigned before expiry.

Callback registration, Page subscription, public receiver invocation,
production ERP table grants, production-mode processing and prospect messaging
were not enabled. They remain blocked by the missing exact batch, the 180/225
course-hours discrepancy and the absence of an approved counsellor mapping.
