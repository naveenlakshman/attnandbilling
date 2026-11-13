# Durable Meta leads staging review package

Status: source preparation only. No service, database, IAM binding, callback or
Page subscription has been created. Production ERP writes and prospect messaging
remain unavailable in this package.

## Boundaries and evidence classes

Results must be reported separately as:

1. credential validity;
2. independently proven synthetic retrieval;
3. durable staging receiver and worker tests;
4. live webhook delivery; and
5. ERP enquiry creation.

Local and MySQL tests do not certify live Meta delivery. Synthetic retrieval does
not certify callback delivery or ERP enquiry creation.

The approved synthetic registry proof, including the app, Page, form, synthetic
lead ID and timestamp, is retained in private evidence outside Git. Only its hash
may appear in logs or this repository. The system user has Page Leads access only.
Its inability to list `test_leads` is accepted; permissions must not be broadened
solely for that diagnostic.

## Candidate architecture

- The public receiver validates the verification token for GET challenges and
  `X-Hub-Signature-256` over the exact raw POST body before JSON parsing.
- Verification and ingestion use separate switches. Callback verification can be
  reviewed with `META_STAGING_VERIFY_ENABLED=true` while
  `META_STAGING_ENABLED=false` continues to reject deliveries.
- The MySQL inbox uses InnoDB, a unique Meta lead ID, atomic batch transactions,
  `INSERT IGNORE` duplicate handling and transactional worker leases using
  `FOR UPDATE SKIP LOCKED`.
- The Cloud Run Job worker derives a Page token in memory from the system-user
  credential, retrieves only an explicitly allowlisted synthetic ID, and persists
  field names, answer count and a SHA-256 digest. It never persists answer values.
- Failures use bounded exponential retry and safe error codes. Exhausted work is
  retained as `DEAD`; manual replay accepts only an allowlisted synthetic ID and
  creates a count-only audit record.
- Queue state and audit counts are operationally visible without IDs, answers,
  headers, credentials or raw request bodies.

## Test evidence

Final source tests on 13 November 2026: **30 passed**.

- 24 receiver, processor and packaged-worker tests.
- 6 integration tests against an isolated MySQL Community Server **8.0.45**.
- The MySQL tests repeated the migration, raced 16 concurrent deliveries of one
  lead ID, claimed 24 rows with eight concurrent workers, forced a mid-batch
  transaction failure, recovered an expired lease, exercised retry/dead/replay,
  verified an unknown completion outcome is not rewritten as a processing
  failure, and checked safe behavior when storage is unavailable.
- Python compilation and `git diff --check` passed.

Private JUnit and console evidence is retained outside Git under
`C:\Users\hello\.codex\private-evidence\meta-leads-20261113`.

## Proposed resources and cost

None of these resources has been created:

| Resource | Proposed name | Planning estimate |
|---|---|---:|
| Zonal Cloud SQL MySQL 8 instance | `global-it-meta-leads-staging-db` | USD 15-30/month continuously running |
| Database | `meta_leads_staging` | Included above |
| Cloud Run receiver | `global-it-meta-leads-staging-receiver` | Usually within free tier at synthetic volume |
| Cloud Run Job worker | `global-it-meta-leads-staging-worker` | Usually within free tier at synthetic volume |
| Cloud Scheduler job | `global-it-meta-leads-staging-worker-schedule` | About USD 0.10/month after free allowance |
| Artifact Registry image | `meta-leads-staging/receiver` | Usually under USD 1/month for one small image |

The dedicated instance costs more than Firestore but preserves MySQL transaction,
locking and migration parity and avoids the production database blast radius. A
separate database on the production instance is rejected. Firestore remains a
lower-cost future alternative but would require a different concurrency and lease
implementation. Exact billing depends on region, storage, backups, taxes and use.

## Secret references and proposed IAM

Existing references:

- `projects/644631083795/secrets/meta-erp-leads-app-secret/versions/1`
- `projects/644631083795/secrets/meta-erp-leads-staging-system-user-token/versions/1`

Proposed secrets, not created:

- `meta-erp-leads-staging-verify-token`
- `meta-erp-leads-staging-db-password`
- `meta-erp-leads-staging-synthetic-allowlist`

Proposed service accounts, not created:

- `meta-leads-staging-receiver@global-it-edu-app.iam.gserviceaccount.com`
- `meta-leads-staging-worker@global-it-edu-app.iam.gserviceaccount.com`
- `meta-leads-staging-scheduler@global-it-edu-app.iam.gserviceaccount.com`

Proposed grants require separate approval:

- Receiver: Cloud SQL Client; Secret Accessor only on app secret, verification
  token, database password and synthetic allowlist.
- Worker: Cloud SQL Client; Secret Accessor only on system-user token, database
  password and synthetic allowlist. It does not receive the app secret or
  verification token.
- Scheduler identity: Cloud Run Invoker only on the staging worker job.
- Public unauthenticated invoker on the receiver is required only when Meta is
  approved to reach the HTTPS callback. Application signature validation remains
  mandatory. No production ERP secret is granted to either runtime identity.

## Credential lifecycle

The system-user token is renewable and expires after 60 days.

- Owner: Global IT Education Meta business administrators. Primary operator:
  Naveen L; independent approval: another full-control administrator.
- At 21, 14 and 7 days before expiry, monitoring must alert the owner. A daily
  read-only `debug_token` check records validity, app match, scope set and expiry;
  it never logs the token.
- Generate the replacement with the same app, 60-day lifetime, five reviewed
  scopes and Leads-only Page asset access. Do not broaden Page permissions.
- Add the replacement as a new pinned Secret Manager version. Validate app, Page,
  form and the independently allowlisted synthetic lead before updating any
  worker revision to the new version.
- Run the old and new credential checks side by side. After the new zero-traffic
  worker candidate passes, update the pinned secret version, run one synthetic
  retrieval, and retain the old version for 24 hours without using `latest`.
- After the observation period, disable the old secret version and revoke the old
  Meta token. Destruction is deferred until the audit retention period expires.
- On unexpected revocation, pause Scheduler, disable the worker job, leave inbox
  rows pending, issue and independently approve a replacement, validate it, then
  resume. Never mark pending rows complete or delete them to recover access.

## Proposed deployment sequence

1. Approve the exact commit, image digest, resources, secret-level IAM and costs.
2. Create the dedicated staging database and runtime identities. Apply the SQL
   migration separately; Cloud Run does not run repository migrations.
3. Deploy the receiver as a zero-traffic revision with both switches false and
   deploy the worker job disabled. Verify storage, logs and secret references.
4. Create a second zero-traffic receiver revision with verification true and
   ingestion false. Verify the proposed callback path using a local challenge.
5. After separate Meta approval, expose only the receiver, register the callback,
   and subscribe the Page to `leadgen`. Keep ingestion and the worker disabled.
6. Verify one live synthetic delivery into the durable inbox, duplicates and
   redacted monitoring. Only then approve worker execution for that allowlisted ID.

Proposed callback, which does not yet exist:

`https://<staging-service-host>/webhook/meta`

## Proposed Meta writes requiring separate approval

1. App Dashboard Webhooks: set the proposed HTTPS callback and verification token,
   subscribe the app Page object to the `leadgen` field.
2. Page subscription: POST `/{page-id}/subscribed_apps` with
   `subscribed_fields=leadgen` using the reviewed Page credential flow.

Both actions change Meta configuration. They must occur only after the disabled
candidate, exact URL, image digest and recovery controls are approved. Existing
test records and third-party CRM connections must remain untouched.

## Disable and rollback

Immediate disable order:

1. Pause `global-it-meta-leads-staging-worker-schedule`.
2. Update the worker job with `META_STAGING_ENABLED=false` and cancel active job
   executions.
3. Route 100% receiver traffic to the prebuilt revision with
   `META_STAGING_VERIFY_ENABLED=false` and `META_STAGING_ENABLED=false`.
4. Remove every tag from enabled candidate revisions because tagged URLs bypass
   ordinary traffic allocation.

Exact command pattern, with reviewed revision and execution names substituted:

```powershell
gcloud scheduler jobs pause global-it-meta-leads-staging-worker-schedule `
  --location=asia-south1 --project=global-it-edu-app

gcloud run jobs update global-it-meta-leads-staging-worker `
  --region=asia-south1 --project=global-it-edu-app `
  --update-env-vars=META_STAGING_ENABLED=false

gcloud run jobs executions cancel EXECUTION_NAME `
  --region=asia-south1 --project=global-it-edu-app

gcloud run services update-traffic global-it-meta-leads-staging-receiver `
  --region=asia-south1 --project=global-it-edu-app `
  --to-revisions=DISABLED_REVISION=100

gcloud run services update-traffic global-it-meta-leads-staging-receiver `
  --region=asia-south1 --project=global-it-edu-app `
  --remove-tags=candidate
```

Ordinary code rollback routes traffic to a previously tested compatible revision
and leaves the database intact. Accepted inbox rows are never rolled back with
code. Database restoration is a separate incident procedure: preserve the current
database, restore a backup into a new recovery instance, reconcile every accepted
post-backup inbox row, and cut over only after review. Do not restore in place or
delete accepted rows as part of routine rollback.
