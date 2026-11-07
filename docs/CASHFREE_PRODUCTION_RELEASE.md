# Cashfree live release preparation

Live release prepared on 7 November 2026 for the existing production service.
The owner confirmed production credentials, approval of www.globaliterp.com in
Cashfree, and switching the scheduled reminder job to the production database.
The two additive payment tables have been applied; existing ledger rows were not changed.

## Verified production inventory

- Project: `global-it-edu-app`, region: `asia-south1`.
- Service: `global-it-erp-production`.
- Pre-release serving and rollback revision: `global-it-erp-production-student-names-abe8fb3`.
- Runtime account: `attn-billing-runtime@global-it-edu-app.iam.gserviceaccount.com`.
- Database: `global_it_erp_production`, Cloud SQL instance `global-it-erp-production-db`.
- Active primary institute-1 domain: `www.globaliterp.com`.
- Current runtime: 1 CPU, 1 GiB, concurrency 80, timeout 120 seconds, maximum 4 instances.
- Automated backup `1793997000000` completed successfully at `2026-11-06T21:33:49Z`.
  Binary logs/PITR are enabled, with 8 retained backups and 7 transaction-log days.
- Both Cashfree tables were created on 7 November; both initially contained zero rows.
- Live secret versions are `attn-billing-cashfree-live-app-id:1` and
  `attn-billing-cashfree-live-secret-key:1`. Runtime Secret Accessor grants are verified.
- Reminder job: `automatic-fee-reminders`, using the same runtime service account.
  Before release it targets `attn_billing_testing`; the approved release switches
  its database/socket/Cloud SQL mount to match the production web service.
- Scheduler: `automatic-fee-reminders-daily`, enabled at 09:00 Asia/Kolkata.

Refresh this inventory before deployment; the local JSON records under
`scratch/cashfree-production-release/` are excluded from source uploads.

## Live credentials and Secret Manager

Keep the existing sandbox `.env` entries for Docker. Add these separate values
locally, without sharing them through chat, Git, shell arguments, or build substitutions:

```dotenv
CASHFREE_LIVE_APP_ID=<Cashfree production App ID>
CASHFREE_LIVE_SECRET_KEY=<Cashfree production secret>
```

After the owner confirms the values are ready:

```powershell
.venv\Scripts\python.exe ops/cashfree_production_release.py inventory
.venv\Scripts\python.exe ops/cashfree_production_release.py schema-preflight
.venv\Scripts\python.exe ops/cashfree_production_release.py store-secrets
```

The helper uploads secret bytes through stdin and grants Secret Accessor on only
the two Cashfree secrets to the existing runtime account. It records numeric
versions of `attn-billing-cashfree-live-app-id` and
`attn-billing-cashfree-live-secret-key`. Bind those recorded versions to
`CASHFREE_APP_ID` and `CASHFREE_SECRET_KEY` using additive `--update-secrets` flags.
Existing secret bindings and runtime settings must be preserved.

## Release sequence

1. Confirm live credentials, merchant account readiness, and domain approval in
   Cashfree for `https://www.globaliterp.com`.
2. Refresh backup/PITR status. Apply the two committed, additive migrations
   `20261029_cashfree_sandbox.sql` and `20261029_cashfree_student_payment_links.sql`
   through an authenticated Cloud SQL connection. Verify schema and constraints.
   Do not drop the payment mapping tables when rolling back application code.
3. Compile, run payment and release-secret tests, run the MySQL integration test,
   review the diff, and commit the intended release changes. Inspect the upload
   source list and exclude all credentials, local database files, and student uploads.
4. Build an image tagged with the reviewed commit, record its immutable digest,
   and deploy it with zero traffic while preserving the actual service configuration.
5. Use these production-only environment settings on the candidate:

   ```dotenv
   CASHFREE_MODE=production
   CASHFREE_API_URL=https://api.cashfree.com/pg
   CASHFREE_INSTITUTE_ID=1
   CASHFREE_PAYMENT_LINKS_ENABLED=true
   CASHFREE_PAYMENT_LINK_BASE_URL=https://www.globaliterp.com
   CASHFREE_NOTIFY_URL=https://www.globaliterp.com/billing/cashfree/webhook
   ```

6. Check readiness, TLS/login, secret resolution, authorization, schema access,
   webhook signature rejection, and logs on the candidate. Promote only after
   those checks pass, then verify the intended tenant domain and payment-link pages.
7. After the web release serves traffic, update the existing reminder job to the
   same immutable image, live-mode settings, canonical payment-link URL, and pinned
   secret references. Preserve its other settings. Do not execute it as a test:
   that would send real reminder messages.

Production mode rejects TEST App IDs, mismatched API hosts, and sandbox order IDs.
Live orders use the `cf_live_` prefix; existing sandbox orders retain `cf_`.
The frontend SDK mode, checkout CSP, SMS messages, receipt notes, and audit wording
follow the configured environment. Production application configuration refuses
sandbox payment processing.

No live payment, real student message, schema write, candidate deployment, or
traffic promotion should be performed until the release prerequisites are satisfied.

## 7 November 2026 deployment verification

- Serving revision: `global-it-erp-production-cashfree-live-539297b`.
- Immutable image: `sha256:ab5e19ea10cbf77db2e00c432195b3dfbe28951a8a467677da2d729e047134f1`.
- Payment, link, migration/concurrency and message coverage: 90 Python tests and
  22 JavaScript tests passed, including the disposable MySQL integration test.
- Candidate, direct Cloud Run and public-domain checks passed for live checkout,
  current installment/full-balance choices, authentication, invalid-amount and
  sandbox-order rejection, webhook signature authentication and public health.
- The load balancer's `erp-cloudrun-backend` had static CSP and referrer headers
  that overrode application policies. Those two overrides were removed; other
  backend settings and headers were preserved. Cloud Run now supplies the
  route-specific CSP and payment-link `no-referrer` policy. Billing CDN cache
  invalidation completed before the final public checks passed.
- `automatic-fee-reminders` now uses the same live image and pinned Cashfree
  secrets, `global_it_erp_production`, and the production Cloud SQL socket/mount.
  The existing daily 09:00 Asia/Kolkata schedule and other runtime settings remain.
- Execution `automatic-fee-reminders-lgwcd` used execution-only argument overrides
  for a read-only dry run, with the send function disabled. It verified one live
  payment link, reported zero failures, and sent zero messages. The job's normal
  command remains `python scripts/run_fee_reminders.py`.
- Verification created no live orders, charged no payments and changed no existing
  fee-ledger records. The earlier web revision and pre-release job image remain
  available; preserve payment mappings and reconcile in-flight orders if reverting.

References: [Cloud Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets),
[Secret Manager versions](https://docs.cloud.google.com/secret-manager/docs/add-secret-version),
[Cashfree go-live requirements](https://www.cashfree.com/docs/payments/online/go-live/checklist).
