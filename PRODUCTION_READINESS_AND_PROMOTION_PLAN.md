# Global IT ERP Multi-Institute Production Readiness and Promotion Plan

## 1. Purpose

This runbook defines the work required to promote the tested multi-institute
application to the existing Global IT Education production environment without
mixing staging data, credentials, storage, domains, or tenant identities with
production.

The production release is not considered ready merely because the container
builds or Cloud Run accepts a revision. It is ready only after every mandatory
gate in this document passes and the release owner records an explicit go/no-go
decision.

## 2. Environment boundaries

### 2.1 Production

| Item | Value |
|---|---|
| Google Cloud project | `global-it-edu-app` |
| Region | `asia-south1` |
| Cloud Run service | `attn-billing-testing` |
| Public domain | `https://www.globaliterp.com` |
| Cloud SQL instance | `attn-billing-testing-db` |
| Database | `attn_billing_testing` |
| Runtime service account | `attn-billing-runtime@global-it-edu-app.iam.gserviceaccount.com` |
| Storage bucket | `global-it-erp-storage` |
| Redis | Production Memorystore instance only |

### 2.2 Staging

| Item | Value |
|---|---|
| Google Cloud project | `global-it-erp-staging` |
| Region | `asia-south1` |
| Cloud Run service | `attn-billing-staging` |
| Test domains | Staging and verified test institute domains |
| Cloud SQL instance | `attn-billing-staging-db` |
| Database | `attn_billing_staging` |
| Storage bucket | `global-it-erp-staging-storage` |

### 2.3 Non-negotiable isolation rules

- Never copy staging records into production.
- Never use staging secrets, buckets, Redis addresses, service accounts, or
  platform-owner credentials in production.
- Never point a staging domain at the production load balancer.
- Never run a production migration before a production backup and rehearsal.
- Never deploy a mutable image tag such as `latest` or `manual`.
- Never send production traffic to an untested revision.
- Never expose a raw database exception, SQL statement, secret, or stack trace
  to users.

## 3. Release scope

The release includes the multi-institute foundation and the changes currently
validated on the feature branch, including:

- institute and platform-owner identity separation;
- audited platform-owner tenant switching;
- institute-owned branches, administrators, users, leads, students, courses,
  LMS records, finance records, assets, documents, and numbering;
- domain ownership verification and hostname-based tenant resolution;
- institute branding and storage;
- onboarding, plan limits, suspension, and reactivation;
- tenant-specific invoice, receipt, write-off, asset, and document numbering;
- tenant-scoped dashboards, LMS progress, public course catalog, billing, and
  administrative screens;
- secured student document and photo access;
- regression fixes completed during staging acceptance testing.

The release must be tied to one immutable Git commit. At the time this plan was
created, the candidate branch was `feature/multi-institute-phase2` and the
observed commit was `9e645b9`. Reconfirm this before release.

## 4. Roles and responsibility

| Role | Responsibility |
|---|---|
| Release owner | Final go/no-go decision and traffic changes |
| Application owner | Confirms expected business behaviour |
| Database owner | Backup, migration, validation, and recovery |
| Security reviewer | IAM, secrets, network, headers, and isolation review |
| Test lead | Executes and signs the acceptance matrix |
| Support lead | User communication and post-release incident response |

One person may hold multiple roles, but every gate must have a named owner.

## 5. Definition of 100% production ready

All of the following must be true:

- [ ] The release commit is immutable, reviewed, and reproducible.
- [ ] The complete automated test suite passes in Cloud Build.
- [ ] All high-risk multi-tenant routes have cross-institute tests.
- [ ] Production configuration has been reviewed without exposing secret values.
- [ ] Cloud SQL automated backups are enabled and an on-demand pre-release
      backup is successful.
- [ ] A restore/recovery procedure has been rehearsed outside production.
- [ ] Every production migration has been rehearsed on a recent sanitized clone.
- [ ] All existing production records receive the correct institute ownership.
- [ ] Existing Global IT users, students, financial records, files, LMS content,
      and document numbers remain intact.
- [ ] `www.globaliterp.com` resolves only to the Global IT Education institute.
- [ ] Platform control hosts do not inherit institute branding or tenant data.
- [ ] Staging and other institutes cannot read or modify Global IT records.
- [ ] Production secrets and integrations pass readiness tests.
- [ ] A zero-traffic revision passes authenticated and unauthenticated smoke tests.
- [ ] Rollback has been tested and the previous healthy revision is retained.
- [ ] Monitoring, alerting, and support coverage are active.
- [ ] Traffic reaches 100% without breaching the abort thresholds.
- [ ] A post-release audit confirms isolation and data integrity.

## 6. Phase A — Release freeze and source control

### Actions

1. Stop feature development on the release branch.
2. Pull the remote branch with fast-forward only.
3. Confirm the worktree is clean.
4. Review the complete difference from the current production commit.
5. Remove temporary debugging, local credentials, database exports, uploaded
   test files, and test-only bypasses.
6. Run secret scanning across the repository and Git history.
7. Create a pull request into the protected release branch.
8. Require review for application, database, and security changes.
9. Create an annotated release tag after approval.

### Example checks

```powershell
git checkout feature/multi-institute-phase2
git pull --ff-only
git status --short
git diff --stat <current-production-commit>..HEAD
git log --oneline <current-production-commit>..HEAD
```

### Immutable release identifiers

Use the commit in all artifacts:

```text
Git tag: multi-institute-v1.0.0
Image tag: multi-institute-<short-commit-sha>
Revision suffix: multi-v1
```

### Exit gate

- [ ] Approved pull request
- [ ] Clean worktree
- [ ] No committed secrets or database dumps
- [ ] Signed release commit/tag
- [ ] Exact production diff reviewed

## 7. Phase B — Production workflow parity

The production `cloudbuild.yaml` must be brought to feature parity with the
verified checks in `cloudbuild.staging.yaml`. Production-specific resource
values must remain separate.

### Required build gates

- [ ] no legacy bootstrap
- [ ] domain ownership workflow
- [ ] platform-owner identity separation
- [ ] public website tenant isolation
- [ ] standard dashboard tenant isolation
- [ ] lead stage guard
- [ ] billing dashboard tenant isolation
- [ ] student password workflow
- [ ] LMS create-and-attach master flow
- [ ] read-only student signatures
- [ ] authorized student document access
- [ ] student photo storage URLs and filename sanitization
- [ ] LMS progress dashboard compatibility with MySQL
- [ ] invoice, receipt, write-off, asset, and document sequence isolation
- [ ] cross-institute CRUD denial for all tenant-owned resources

### Required deployment behaviour

- Build and push an immutable image.
- Deploy the candidate with `--no-traffic`.
- Preserve the production service account, Cloud SQL attachment, VPC,
  Memorystore, bucket, resource limits, and secrets.
- Do not replace all environment variables from an unreviewed YAML file.
- Do not automatically move traffic from Cloud Build.

### Exit gate

- [ ] Production build file reviewed against the live service
- [ ] All automated checks run before image push/deployment
- [ ] Build and revision use immutable identifiers
- [ ] Deployment remains at zero traffic

## 8. Phase C — Security and configuration readiness

### 8.1 Secret Manager

Confirm that the production runtime service account has only the required
Secret Accessor grants. Validate the existence and active version of:

- application secret key;
- database password;
- Google AI key, if enabled;
- Google Maps key, if enabled;
- TinyMCE key;
- SMS gateway username and password;
- email provider credentials, if enabled.

Do not print secret payloads during verification.

### 8.2 Runtime identity

Confirm the service runs as:

```text
attn-billing-runtime@global-it-edu-app.iam.gserviceaccount.com
```

Review and remove unnecessary project-wide roles. Prefer resource-level access
for the production bucket and individual secrets.

### 8.3 Production application settings

At initial release:

```text
APP_ENV=production
DEBUG_MODE=false
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_NAME=__Host-erp_session
SECURITY_HEADERS_ENABLED=true
TENANT_RESOLUTION_MODE=observe
STORAGE_PROVIDER=gcs
GCS_BUCKET_NAME=global-it-erp-storage
```

Set `PLATFORM_CONTROL_HOSTS` to the exact production Cloud Run/platform
hostnames. Do not include `www.globaliterp.com` in platform control hosts.

Keep tenant resolution in `observe` mode for the initial production rollout.
Move to enforcement only after the post-release isolation audit passes.

### 8.4 Network and database hardening

The observed production Cloud SQL configuration has scheduled backups disabled,
public IPv4 enabled, and encrypted transport not required. Required actions:

- enable automated backups and define retention;
- retain deletion protection;
- create and verify an on-demand pre-release backup;
- remove unnecessary authorized public networks;
- require encrypted database connections where compatible;
- retain private application connectivity through Cloud SQL/VPC;
- verify Redis is reachable only through the VPC;
- verify Cloud Run ingress remains compatible with the production load balancer.

### 8.5 Storage security

- Enable uniform bucket-level access.
- Prevent public object access.
- Grant the runtime identity only required object permissions.
- Verify tenant-prefixed object paths.
- Verify signed/authorized file delivery.
- Verify one institute cannot guess or retrieve another institute's file URL.
- Configure retention/lifecycle policies appropriate for business records.

### Exit gate

- [ ] Secrets accessible only to intended identities
- [ ] No staging identifiers in production configuration
- [ ] Secure cookies and security headers confirmed
- [ ] Backup, network, storage, and Redis checks passed
- [ ] Platform control hosts and tenant hosts correctly separated

## 9. Phase D — Database backup and recovery

### 9.1 Enable automated backups

Scheduled backups must be enabled before this release. Retain enough backups to
cover migration discovery and operational recovery.

### 9.2 Create an on-demand backup

```powershell
gcloud sql backups create `
  --project=global-it-edu-app `
  --instance=attn-billing-testing-db `
  --description="Before multi-institute release <commit>"
```

Confirm completion:

```powershell
gcloud sql backups list `
  --project=global-it-edu-app `
  --instance=attn-billing-testing-db
```

### 9.3 Recovery rehearsal

Restore the backup to a separate temporary instance or database, never over the
live production database during rehearsal. Confirm:

- application tables can be queried;
- record counts match;
- representative invoices, receipts, students, LMS content, and files resolve;
- admin and student password hashes remain valid;
- character sets, time zones, and decimal values remain correct.

### Exit gate

- [ ] Automated backup enabled
- [ ] On-demand backup completed
- [ ] Recovery rehearsal documented
- [ ] Recovery time and recovery point objectives accepted

## 10. Phase E — Production data migration rehearsal

Use a recent production clone in an isolated environment. Do not allow that
clone to send SMS, email, webhooks, or other external notifications.

### Migration order

Confirm applicability and execute schema migrations in dependency order:

1. `20260722_multi_institute_phase1_foundation.sql`
2. `20260723_multi_institute_phase2_core_identity.sql`
3. `20260723_multi_institute_phase4_crm_student.sql`
4. `20260724_multi_institute_phase5_finance_assets.sql`
5. `20260727_multi_institute_phase9_onboarding_subscriptions.sql`
6. `20260728_courses_tenant_ownership.sql`
7. `20260728_institute_domain_verification.sql`
8. `20260728_platform_owner_separation.sql`
9. `20260728_student_password_changed_at.sql`
10. `20260729_tenant_asset_sequences.sql`
11. `20260729_tenant_document_sequences.sql`
12. `20260729_tenant_writeoff_sequences.sql`

Also verify whether earlier LMS migrations are already present before applying
them. Never assume a filename means a migration has run.

### Migration requirements

- Migrations must be idempotent or protected by an explicit migration ledger.
- Every table/column/index must be checked before creation.
- DDL and backfills must be separated where useful.
- Long-running backfills must be measured on production-sized data.
- No migration may silently assign a record to an arbitrary institute.
- Financial and audit identifiers must not be renumbered retroactively.
- Existing stored file paths must remain resolvable.
- Backfills must produce zero orphaned tenant-owned records.

### Required reconciliation report

Record before-and-after counts for at least:

- institutes and domains;
- branches and users;
- leads and follow-ups;
- students, enrollments, batches, and attendance;
- courses and public course ownership;
- LMS programs, chapters, topics, content, assignments, submissions, and progress;
- invoices, invoice items, receipts, installments, write-offs, and expenses;
- assets and asset categories;
- student documents, photos, signatures, and certificates;
- activity and audit logs.

For every tenant-owned table:

```text
total rows = rows with valid institute ownership
rows with NULL institute ownership = 0
rows linked to a different institute through parent/child joins = 0
```

### Existing production tenant

The migration must create or identify exactly one Global IT Education tenant and
assign existing Global IT data to it. Validate:

- `www.globaliterp.com` is its active primary domain;
- current branches remain attached;
- existing administrators retain access;
- platform-owner identity is separate from institute administrators;
- current branding and public website remain unchanged;
- current invoice, receipt, student, asset, and LMS numbering remains valid.

### Exit gate

- [ ] Full rehearsal completes successfully
- [ ] Migration duration is within the maintenance window
- [ ] Zero orphaned or cross-owned rows
- [ ] Reconciliation signed by application and database owners
- [ ] Re-running the migration causes no duplication
- [ ] Roll-forward and recovery procedures documented

## 11. Phase F — Test acceptance matrix

### 11.1 Platform owner

- [ ] Login/logout and session expiry
- [ ] Platform UI never inherits the selected institute unintentionally
- [ ] Create, edit, suspend, reactivate, and deactivate an institute
- [ ] Configure plan and limits
- [ ] Onboard first branch and administrator
- [ ] Verify a domain challenge
- [ ] Enter/exit an institute through an audited support session
- [ ] Platform owner does not appear as a tenant staff user
- [ ] Tenant actions are recorded under the platform identity

### 11.2 Tenant isolation

Use Institute A and Institute B:

- [ ] A cannot list, search, view, edit, download, or delete B's records
- [ ] Direct numeric-ID URL access returns 404/403
- [ ] Public hostname selects the correct tenant
- [ ] Raw Cloud Run/platform hostname does not default to the last used tenant
- [ ] Sessions cannot be reused across tenant hostnames incorrectly
- [ ] Cached branding and query results do not leak across hostnames
- [ ] Background jobs, exports, PDFs, SMS, email, and storage retain tenant scope

### 11.3 Administration and CRM

- [ ] Branch/user limits enforced server-side and transactionally
- [ ] User and branch lists do not expose internal IDs unnecessarily
- [ ] Dates display in the configured institute timezone
- [ ] Lead create/edit excludes Converted and Lost direct selection
- [ ] Conversion follows the approved workflow
- [ ] Student registration and profile update work
- [ ] Branch, course, and batch choices contain only tenant-owned records

### 11.4 Finance

- [ ] Dashboard totals are tenant-scoped
- [ ] Invoice and receipt creation is atomic
- [ ] Number sequences start and advance per institute
- [ ] Concurrent creation cannot produce duplicate numbers
- [ ] PDF download works without popup dependence
- [ ] Institute/branch address and branding appear correctly in documents
- [ ] Payment and installment totals reconcile
- [ ] Write-off creation/deletion correctly updates expenses and receivables
- [ ] Activity logs display business references, not unsafe internal IDs
- [ ] Indian/institute-local date-time formatting is correct

### 11.5 LMS

- [ ] Program/course ownership is tenant-scoped
- [ ] New master creation can attach to the current program
- [ ] Master library and editorial workflows remain isolated
- [ ] Assignment, submission, preview, and review work
- [ ] MySQL progress dashboard runs without alias or Decimal/float errors
- [ ] Student progress and completion rules calculate correctly
- [ ] TinyMCE loads only on authorized domains
- [ ] Certificates cannot be viewed across institutes

### 11.6 Student portal

- [ ] Correct institute branding on login and portal
- [ ] Student authentication is tenant-scoped
- [ ] Password confirmation is checked client- and server-side
- [ ] Last password-change time is correct
- [ ] Documents are visible only to the student and authorized staff
- [ ] Existing signatures are read-only
- [ ] Profile update form expands only when requested
- [ ] Photo upload and camera capture persist in GCS
- [ ] Camera denial produces useful guidance and file upload remains available

### 11.7 Responsive and browser testing

- [ ] Chrome, Edge, Firefox, and mobile browsers
- [ ] Desktop, tablet, and mobile layouts
- [ ] Keyboard navigation and focus visibility
- [ ] Forms remain usable at 200% zoom
- [ ] No unexpected horizontal scrolling for action controls

### Exit gate

- [ ] No open severity-1 or severity-2 defects
- [ ] Security and isolation tests have 100% pass rate
- [ ] Business acceptance signed

## 12. Phase G — Observability and operations

### Required monitoring

- Cloud Run request count, latency, CPU, memory, instances, and 5xx rate;
- application exceptions grouped by route and revision;
- Cloud SQL CPU, memory, connections, storage, slow queries, and lock waits;
- Redis connection failures and rate-limit errors;
- GCS permission and object-not-found errors;
- authentication failures and suspicious cross-tenant access attempts;
- SMS/email delivery errors without logging credentials or sensitive content.

### Alerts

Define actionable thresholds and recipients for:

- elevated 5xx rate;
- health check failures;
- abnormal latency;
- database connection exhaustion;
- database storage threshold;
- failed backup;
- repeated tenant-authorization denial spikes;
- revision startup failures.

### Log requirements

- Include revision, request/correlation ID, institute ID, actor type, and route.
- Do not log passwords, tokens, document contents, or secret values.
- Platform support sessions must include platform actor, target institute,
  start/end time, and performed action.

### Exit gate

- [ ] Dashboards and alerts tested
- [ ] Support and escalation contacts assigned
- [ ] Logs support tenant-safe incident investigation

## 13. Phase H — Production deployment

### 13.1 Change window

Choose a low-usage period. Notify staff of the maintenance window and temporary
change freeze. Pause scheduled jobs that could write conflicting data during
the migration.

### 13.2 Final preflight

- [ ] Confirm exact Git commit and image digest
- [ ] Confirm production project in the active CLI context
- [ ] Confirm backup completed
- [ ] Confirm previous healthy revision name
- [ ] Export the current Cloud Run service description for recovery
- [ ] Confirm migration scripts and reconciliation queries
- [ ] Confirm named release, database, security, and test owners are present

### 13.3 Apply migrations

Apply only the reviewed production migration bundle. Capture start/end time and
output. Run the reconciliation report immediately afterward. Abort before
traffic changes if any count or ownership check fails.

### 13.4 Deploy zero-traffic revision

Build using the production project and immutable tag. Deploy with:

```text
--no-traffic
--revision-suffix=multi-v1
```

Do not modify the custom domain mapping. Because the same Cloud Run service is
used, `www.globaliterp.com` remains mapped to the service while revision traffic
is controlled separately.

### 13.5 Smoke-test candidate

Test the candidate revision using an approved revision tag or controlled
internal route. Ensure testing the tag does not accidentally resolve the tag
hostname as a production institute hostname.

Minimum checks:

- health/startup;
- public home and login;
- platform-owner login;
- Global IT administrator login;
- representative student login;
- dashboard;
- one read-only lead/student/finance/LMS path;
- authorized GCS image/document retrieval;
- database and Redis connectivity;
- correct host/tenant resolution.

### Exit gate

- [ ] Candidate revision healthy
- [ ] Smoke tests pass
- [ ] No migration reconciliation errors
- [ ] No configuration drift

## 14. Phase I — Progressive traffic rollout

Record baseline 5xx rate, latency, login success, and database health before
moving traffic.

Recommended progression:

1. 5% candidate / 95% previous revision
2. 25% candidate / 75% previous revision
3. 50% candidate / 50% previous revision
4. 100% candidate

Hold each stage long enough to cover real requests and critical workflows.
Because schema is shared, migrations must remain backward-compatible with the
old application throughout progressive rollout.

### Abort thresholds

Immediately stop or roll back application traffic if:

- tenant data appears under the wrong hostname or user;
- any cross-institute access succeeds;
- authentication or session handling fails materially;
- error rate or latency exceeds the agreed threshold;
- invoice/receipt numbering duplicates or skips unexpectedly;
- financial totals do not reconcile;
- files are publicly exposed or become broadly inaccessible;
- database connections, locks, or CPU reach unsafe levels;
- required platform or institute administrators cannot log in.

### Application rollback

Move 100% traffic to the previous healthy revision. Do not automatically reverse
database migrations. Use expand/contract migrations so the previous revision
remains compatible. If data integrity is affected, stop writes and invoke the
database recovery plan.

### Exit gate

- [ ] 100% traffic on candidate
- [ ] Previous healthy revision retained
- [ ] No abort threshold breached
- [ ] Core business workflow confirmed by a real authorized tester

## 15. Phase J — Post-release validation

### First hour

- monitor logs, 5xx rate, latency, Cloud SQL, Redis, and GCS;
- verify `www.globaliterp.com` branding and tenant selection;
- verify platform-control hostname separation;
- test one admin and one student session;
- verify dashboard and finance totals;
- verify no staging integrations or domains appear.

### First 24 hours

- reconcile new invoice, receipt, student, lead, and LMS activity;
- review authorization denials and support-session audit events;
- confirm scheduled backup completion;
- verify SMS/email delivery and quotas if enabled;
- collect staff and student reports.

### First 7 days

- run the complete cross-tenant isolation suite again;
- review slow queries and add indexes only through a reviewed migration;
- review storage usage and orphaned objects;
- confirm plan limits and suspension behaviour;
- decide whether tenant resolution can move from `observe` to enforcement.

### Exit gate

- [ ] 24-hour validation signed
- [ ] 7-day isolation audit signed
- [ ] No unresolved production integrity issue
- [ ] Release record completed

## 16. Recommended execution sequence

| Order | Work item | Environment | Production mutation? |
|---:|---|---|---|
| 1 | Freeze and review release | Git | No |
| 2 | Update production Cloud Build gates | Repository | No |
| 3 | Run all automated tests | Build | No |
| 4 | Enable backups and take backup | Production Cloud SQL | Yes |
| 5 | Rehearse migration on clone | Isolated clone | No |
| 6 | Complete acceptance matrix | Staging | No |
| 7 | Review production IAM/config | Production, read-only first | Potentially |
| 8 | Apply reviewed migrations | Production Cloud SQL | Yes |
| 9 | Deploy zero-traffic revision | Production Cloud Run | Yes |
| 10 | Smoke-test candidate | Production candidate | Read-only preferred |
| 11 | Shift traffic progressively | Production Cloud Run | Yes |
| 12 | Monitor and reconcile | Production | Read-only |
| 13 | Enforce tenant resolution after audit | Production | Yes |

## 17. Current known blockers

At the time this plan was prepared:

1. Production scheduled Cloud SQL backups were disabled.
2. The production Cloud Build workflow did not include the full staging
   multi-tenant regression suite.
3. Production used a mutable image tag in its build substitutions.
4. The live production service did not yet expose all explicit platform-control
   and tenant-resolution configuration used in staging.
5. Production Cloud SQL public-network and transport settings required review.
6. The full production-data migration and reconciliation had not yet been
   rehearsed on a recent production-sized clone.

Production rollout must not begin until these blockers are resolved.

## 18. Final go/no-go record

```text
Release:
Git commit:
Image digest:
New revision:
Previous revision:
Backup ID:
Migration bundle/version:
Release owner:
Database owner:
Security reviewer:
Test lead:
Planned start:
Actual start:
100% traffic time:

Source gate:             PASS / FAIL
Automated tests:         PASS / FAIL
Security review:         PASS / FAIL
Backup and recovery:     PASS / FAIL
Migration rehearsal:     PASS / FAIL
Data reconciliation:     PASS / FAIL
Acceptance testing:      PASS / FAIL
Zero-traffic smoke test: PASS / FAIL
Monitoring readiness:    PASS / FAIL

Decision: GO / NO-GO
Approved by:
Notes:
```

