# Multi-Institute Platform: Phase 0–3 Team Handoff

**Project:** Global IT ERP multi-institute conversion  
**Prepared:** 23 July 2026  
**Current branch:** `feature/multi-institute-phase2`  
**Local application:** `http://localhost:8080`  
**Secondary local tenant example:** `http://test2.localhost:8080`  
**Production domain:** `www.globaliterp.com`  
**Status:** Phases 0–3 completed and tested locally; staging and production unchanged

---

## 1. Purpose

The application was originally designed for one institute: Global IT Education.
Branches could be created, but users, students, finance, attendance, LMS data,
branding, uploaded files, and authentication all implicitly belonged to Global IT.

The multi-institute project converts the application into a tenant-isolated
platform where:

- a platform owner can create and administer institutes;
- every institute controls its own branding, branches, administrators, and staff;
- operational and student data belongs to exactly one institute;
- usernames, branch codes, student codes, and document numbers may overlap safely
  between institutes;
- a tenant is resolved from the request hostname;
- direct record IDs and file paths cannot cross institute boundaries;
- Global IT production behavior and historical data remain compatible throughout
  the migration.

This document describes what was completed in Phases 0–3 and gives the required
order, controls, and exit gates for the remaining phases.

---

## 2. Environment and safety boundaries

### 2.1 Stable production

- Google Cloud project: `global-it-edu-app`
- Production domain: `www.globaliterp.com`
- Production must not be modified during feature development.
- Do not run new migrations, deploy revisions, change IAM, modify Cloud SQL, or
  change the production bucket until a staging phase has passed its exit gate.

### 2.2 Isolated staging

- Google Cloud project: `global-it-erp-staging`
- Region: `asia-south1`
- Cloud Run: `attn-billing-staging`
- Cloud SQL: `attn-billing-staging-db`
- Database: `attn_billing_staging`
- Intended domain: `staging.globaliterp.com`

Staging is for production-like verification. It must use staging-only databases,
storage, secrets, service accounts, Redis, and integrations.

### 2.3 Local Docker

- Web: `http://localhost:8080`
- MySQL exposed locally on port `3308`
- Global IT resolves from `localhost` for backward-compatible development.
- Secondary institutes use subdomains such as:

  ```text
  http://test2.localhost:8080
  ```

- Docker’s MySQL volume intentionally preserves local test data between rebuilds.

---

## 3. Target authorization model

| Identity | Scope |
|---|---|
| Platform owner | Creates and administers institutes; not an institute administrator by implication |
| Institute administrator | Manages one institute, its branding, branches, administrators, and staff |
| Branch administrator | Limited to permitted branches inside one institute |
| Staff/trainer | Assigned institute, branches, batches, programs, and students |
| Student | One institute and their own student records |

Important rules:

1. An ordinary Global IT administrator must never become a platform owner
   automatically.
2. Platform-owner access is stored separately in `users.platform_role`.
3. Platform-owner permission is checked against the database on every protected
   request, not trusted only from a signed session.
4. Tenant identity is determined by the verified request hostname.
5. The authenticated session institute must match the hostname institute.
6. Record authorization must include `institute_id`; branch-only checks are not
   sufficient.

---

# Completed work

## 4. Phase 0 — Baseline and isolation test harness

### 4.1 Objective

Freeze the current Global IT behavior, catalogue every tenant assumption, and
create tests capable of detecting cross-institute leakage before changing the
schema.

### 4.2 Deliverables

The Phase 0 package is under `phase0/`:

- `global_it_baseline_20260722.json`
- `table_ownership_registry.json`
- `route_scope_rules.json`
- `two_institute_fixture.json`
- `global_it_reconciliation.py`
- `README.md`

The main characterization harness is:

```text
scratch/test_multi_institute_phase0.py
```

### 4.3 What the audit established

The original system assumed:

- one global company profile;
- globally searched staff usernames;
- globally searched student codes;
- branches without institute ownership;
- dashboards aggregating every row;
- direct-ID routes without tenant conditions;
- one shared set of SMS and integration credentials;
- shared storage prefixes such as `documents/`, `student_photos/`, `logos/`,
  `signatures/`, and `certificates/`;
- no platform-owner control plane.

### 4.4 Route classification

Every Flask endpoint is classified as one of:

- `public_platform`
- `public_tenant`
- `tenant_staff`
- `tenant_student`
- `tenant_mixed_legacy`
- `platform_owner`

New routes must be added to the route registry. An unclassified route must fail
the Phase 0 test.

### 4.5 Exit evidence

- Database table registry matches the actual MySQL schema.
- Every Flask route receives a declared scope.
- The two-institute fixture intentionally overlaps usernames, branch codes,
  student codes, filenames, and business identifiers.
- Cleanup runs after characterization tests.

### 4.6 Commit

```text
ce4a348 test: add multi-institute phase 0 baseline
```

---

## 5. Phase 1 — Tenant foundation without behavior change

### 5.1 Objective

Create the tenant control-plane schema and request context without changing
Global IT’s visible production behavior.

### 5.2 Schema introduced

- `institutes`
- `institute_domains`
- `institute_branding`
- `institute_settings`
- `institute_integrations`
- `institute_memberships`
- `tenant_migration_runs`
- `tenant_security_audit`
- `activity_logs.institute_id`

Primary migration:

```text
migrations/20260722_multi_institute_phase1_foundation.sql
```

### 5.3 Global IT backfill

- Global IT Education is institute ID `1`.
- `globaliterp.com` and `www.globaliterp.com` resolve to institute `1`.
- Existing users received institute memberships.
- Historical activity logs were assigned to institute `1`.
- Compatibility branding and settings were seeded.

### 5.4 Tenant resolution

`services/tenant_context.py` now:

- normalizes hostnames;
- resolves verified active domains;
- stores request-local tenant context using `contextvars`;
- supports observe and strict resolution modes;
- detects hostname/session mismatches;
- records security denials in `tenant_security_audit`;
- provides tenant-aware cache keys;
- clears request tenant state safely.

### 5.5 Session foundation

Staff and student sessions carry institute context. Authentication later phases
must continue validating that session institute against the request hostname.

### 5.6 Cache isolation

Company and generic cache keys are namespaced by institute. A cache entry from one
institute must never be reused for another.

### 5.7 Tests

```text
scratch/test_multi_institute_phase1.py
```

The test verifies:

- schema and Global IT seed;
- domain resolution;
- localhost fallback;
- strict unknown-host denial;
- session/hostname mismatch denial;
- parallel request isolation;
- tenant security auditing;
- tenant cache namespaces;
- company-profile cache separation.

### 5.8 Commit

```text
369e100 feat: add multi-institute phase 1 foundation
```

---

## 6. Phase 2 — Core identity, platform administration, users, and branches

### 6.1 Objective

Introduce a platform control plane and make staff users and branches tenant-owned
without exposing legacy Global IT business data to secondary institutes.

### 6.2 Schema changes

Migration:

```text
migrations/20260723_multi_institute_phase2_core_identity.sql
```

Changes:

- `branches.institute_id`
- `users.institute_id`
- `users.platform_role`
- foreign keys to `institutes`
- per-institute unique branch code
- per-institute unique branch name
- per-institute unique username
- institute/status indexes

Global IT branches and users were backfilled to institute `1`.

### 6.3 Platform Administration

New blueprint:

```text
modules/platform_admin/
```

Platform-owner routes support:

- listing institutes;
- creating an institute;
- editing institute identity and settings;
- activating/deactivating an institute;
- creating and editing tenant-owned branches;
- activating/deactivating branches;
- creating and editing institute administrators;
- activating/deactivating administrators.

Templates:

```text
templates/platform_admin/
```

### 6.4 Platform owner separation

The original bootstrap temporarily promoted the first admin. This was corrected.

Current behavior:

- `naveen` is only a Global IT institute administrator;
- platform owners use a dedicated account;
- institute User Management does not list or edit platform identities;
- the `platform_owner_required` decorator revalidates the role in the database on
  every request;
- stale sessions cannot retain platform access after role revocation.

Provisioning utility:

```text
scripts/create_platform_owner.py
```

The password must be supplied through `PLATFORM_OWNER_PASSWORD` and must not be
stored in source code.

### 6.5 Tenant-scoped staff login

Staff authentication now requires:

- the username to belong to the hostname’s institute;
- an active user;
- an active institute membership.

The same username can exist in two institutes and authenticate only on the
matching hostname.

### 6.6 Tenant-scoped branch and user CRUD

All branch/user list, create, edit, and status operations include
`institute_id`.

Direct-ID requests for another institute are rejected.

### 6.7 Secondary-tenant containment

At this point, students, leads, finance, attendance, reporting, and LMS were still
global. A secondary institute initially displayed Global IT dashboard totals.
This was treated as a serious isolation defect and contained immediately.

Secondary institutes currently have access only to:

- safe setup dashboard;
- branches;
- users;
- branding added in Phase 3;
- logout.

All unmigrated modules are:

- hidden from the sidebar; and
- blocked server-side with `403`.

The containment must remain until each later phase passes its isolation exit gate.

### 6.8 Local tenant domains

Non-production `.localhost` domains activate automatically:

```text
test2.localhost
```

Real custom domains remain pending.

### 6.9 Tests

```text
scratch/test_multi_institute_phase2.py
```

The suite verifies:

- schema/backfill;
- platform/institute role separation;
- institute/branch/admin CRUD;
- overlapping usernames and branch codes;
- hostname-scoped login;
- branch direct-object isolation;
- legacy module containment;
- platform-owner authorization;
- platform identity hidden from tenant User Management.

### 6.10 Commits

```text
442c7c1 feat: add phase 2 platform tenant administration
f792b2a fix: separate platform owners from institute admins
9380142 fix: revalidate platform access on every request
b84aee2 feat: support local tenant hostnames for testing
ec4afb3 fix: contain legacy data for secondary tenants
```

---

## 7. Phase 3 — Branding, domains, and storage foundation

### 7.1 Objective

Give each institute an independent brand and establish private tenant-prefixed
storage before enabling student or operational uploads.

### 7.2 Tenant branding

Secondary institutes now render their own:

- display name;
- short name;
- tagline;
- primary color;
- secondary color;
- address;
- phone;
- email;
- website;
- registration number;
- logo;
- favicon.

Branding appears on login and authenticated layouts.

Institute administrators manage their own branding at:

```text
/institute/branding
```

Platform owners retain cross-institute branding controls.

### 7.3 Brand upload security

Accepted formats:

- PNG
- JPG/JPEG
- WEBP
- ICO

Maximum size:

```text
2 MB
```

SVG uploads are intentionally not accepted because serving user-controlled SVG
inline can create script/content-injection risk.

### 7.4 Domain readiness rules

- `.localhost` hostnames activate automatically only when the environment is not
  production.
- Real new or changed hostnames remain `pending`.
- Production must not activate a hostname until DNS and load-balancer ownership
  verification is complete.

### 7.5 Tenant-prefixed storage

Secondary-institute object keys use:

```text
tenants/{institute_id}/{category}/{filename}
```

Examples:

```text
tenants/16/branding/logos/{uuid}.png
tenants/16/branding/favicons/{uuid}.ico
tenants/16/documents/example.pdf
tenants/16/student_photos/example.jpg
```

Global IT retains its legacy paths temporarily:

```text
documents/...
student_photos/...
logos/...
```

This compatibility rule prevents existing production files from breaking before
their controlled object migration.

### 7.6 Authorized file delivery

Tenant-prefixed files are served through:

```text
/tenant-files/tenants/{institute_id}/...
```

Rules:

- the request hostname must resolve to the same institute;
- branding may be public only on the matching tenant hostname;
- non-branding files require an authenticated matching-institute session;
- a verified platform owner may preview tenant branding from the control plane;
- private tenant files are not exposed to the platform owner by default;
- cross-institute reads return `404` to avoid revealing object existence.

### 7.7 Storage-layer enforcement

The centralized storage provider:

- automatically prefixes secondary-tenant writes;
- preserves already-canonical tenant paths;
- denies cross-institute reads, replacements, and deletes;
- supports both local storage and GCS;
- keeps Global IT public-path compatibility until migration.

Authorization is enforced in both the delivery route and storage layer.

### 7.8 Tests

```text
scratch/test_multi_institute_phase3.py
```

The suite creates two synthetic institutes and verifies:

- distinct branding by hostname;
- institute-admin branding self-service;
- same filename stored independently by both institutes;
- tenant-prefixed object keys;
- public branding only on the correct hostname;
- authenticated private file delivery;
- unauthenticated private-file denial;
- cross-tenant read denial;
- cross-tenant delete denial;
- platform-owner branding preview;
- Global IT legacy path compatibility;
- cleanup of synthetic database rows and files.

### 7.9 Commit

```text
033dbeb feat: add phase 3 tenant branding and storage isolation
```

### 7.10 Deployment-dependent work

The Global IT production bucket cannot become private yet.

Before removing public access:

1. inventory every stored Global IT path referenced by the database;
2. copy objects to private tenant-prefixed keys in staging;
3. update a staging database copy;
4. reconcile counts, hashes, MIME types, and missing objects;
5. verify every preview/download route;
6. test rollback to legacy paths;
7. repeat in production through a no-traffic revision;
8. only then remove `allUsers: roles/storage.objectViewer`.

---

# Current application state after Phase 3

## 8. What secondary institutes can use now

- tenant-specific login hostname;
- tenant-specific branding;
- safe setup dashboard;
- branch management;
- institute administrator and staff-user management.

## 9. What remains locked

- leads and follow-ups;
- students and admissions;
- student portal;
- student documents;
- batches and attendance;
- finance and assets;
- reports and import/export;
- LMS, assignments, submissions, and reviews;
- exams;
- certificates;
- SMS and tenant integrations.

These modules must not be unlocked merely by changing the sidebar. Both schema
ownership and every backend route must pass the relevant phase exit gate first.

---

# Remaining roadmap

## 10. Phase 4 — CRM and student identity

### 10.1 Scope

Tenant-scope:

- leads;
- lead follow-ups;
- lead conversion;
- students;
- student admission/profile data;
- student documents;
- profile update requests;
- student notes;
- student portal authentication;
- mobile remember tokens;
- website lead routing;
- student numbering.

### 10.2 Required schema work

Add and backfill `institute_id` on all direct CRM/student owner tables.

At minimum review:

- `leads`
- lead follow-up/history tables
- `students`
- `student_uploaded_documents`
- `student_profile_update_requests`
- `student_notes`
- student portal/authentication support tables
- public enquiry/website lead records

Use composite uniqueness:

```text
UNIQUE(institute_id, student_code)
```

Where a child inherits ownership, enforce that its parent belongs to the same
institute. Prefer composite foreign keys or explicit transactional validation.

### 10.3 Authentication work

- student lookup must include hostname institute;
- the same student code may exist in different institutes;
- session and remember-token payloads must include institute ID;
- invalidate or version old mobile tokens;
- restored sessions must revalidate hostname/institute;
- wrong-domain authentication must fail without revealing whether the student
  exists elsewhere.

### 10.4 Route work

Every:

- list query;
- count/dashboard query;
- search;
- export;
- create;
- edit;
- delete/status operation;
- direct-ID profile/document route

must include institute scope.

### 10.5 Storage work

All new student photos and documents must use tenant-prefixed paths.
Historical Global IT student files remain compatible until migration.

### 10.6 Tests

Create two institutes with:

- the same student code;
- the same student name;
- the same phone number where allowed;
- the same uploaded filename.

Verify:

- each student logs in only on the matching domain;
- an institute admin lists only its students;
- direct foreign student IDs return `404` or `403`;
- documents cannot cross tenants;
- lead conversion preserves institute ownership;
- dashboard counts reconcile independently.

### 10.7 Exit gate

> Overlapping student codes work on different tenant domains and never
> authenticate on the wrong domain.

Only after this gate passes may **Leads** and **Students** be unlocked for
secondary institutes.

---

## 11. Phase 5 — Finance and assets

### 11.1 Scope

Tenant-scope:

- invoices;
- invoice items;
- receipts;
- installment plans;
- receivables;
- expenses and categories;
- bad-debt write-offs;
- reminders;
- assets;
- finance activity logs;
- printed/downloadable financial documents.

### 11.2 Numbering

Replace global prefixes/counters with atomic tenant sequences:

```text
institute_settings.invoice_prefix
institute_settings.receipt_prefix
```

Two institutes must be allowed to produce the same visible number without a
database collision because ownership includes `institute_id`.

### 11.3 Authorization

- invoice/receipt/student/branch IDs must all belong to the same institute;
- branch selectors must never contain foreign branches;
- public download tokens must include institute ownership;
- exports must be tenant-limited;
- tenant branding must appear on documents.

### 11.4 Reconciliation

Before and after migration, compare Global IT:

- invoice count and totals;
- receipt count and totals;
- outstanding balances;
- installment balances;
- expense totals;
- bad-debt totals;
- asset counts.

### 11.5 Exit gate

> Global IT financial totals match the frozen baseline exactly, and all
> cross-tenant financial direct-ID tests deny access.

---

## 12. Phase 6 — Attendance and reporting

### 12.1 Scope

Tenant-scope:

- batches;
- trainers and assignments;
- student-batch relationships;
- attendance records;
- attendance patterns;
- holidays/calendars;
- leave requests and documents;
- attendance reports;
- daily/monthly analytics;
- imports and exports;
- scheduled/background processing.

### 12.2 Ownership validation

Enforce that:

- branch belongs to institute;
- trainer belongs to institute;
- batch belongs to institute;
- student belongs to institute;
- every student-batch/trainer-batch link uses the same institute.

### 12.3 Bulk operations

Imports must:

- require a selected institute context;
- reject foreign IDs;
- report row-level ownership errors;
- be transaction-safe;
- never infer institute from an untrusted spreadsheet field alone.

### 12.4 Exit gate

> Attendance totals reconcile by institute, selectors never show foreign
> branches/trainers/students, and bulk imports reject foreign IDs.

---

## 13. Phase 7 — LMS and exams

### 13.1 Ownership model

Separate:

- platform-owned reusable library content;
- institute-owned programs, mappings, publishing decisions, and operational data.

Tenant-scope:

- programs and access mappings;
- assignments;
- submissions and attempts;
- review queue and reviewer identity;
- student progress;
- topic completion;
- tests and results;
- final-exam applications and attempts;
- LMS uploads and previews.

### 13.2 Cross-owner rules

Institutes may copy/use platform content, but:

- assignments are institute-owned;
- student submissions are institute-owned;
- review decisions are institute-owned;
- progress belongs to the student’s institute;
- trainers see only authorized tenant students/batches.

### 13.3 Storage

All new LMS operational files must use tenant prefixes.
Preview and download routes must enforce tenant authorization and must not depend
on publicly accessible bucket objects.

### 13.4 Exit gate

> Two institutes may use the same platform content while assignments,
> submissions, reviews, attempts, and progress remain completely private.

---

## 14. Phase 8 — Certificates and integrations

### 14.1 Certificates

Tenant-scope:

- certificate templates;
- signatures/seals;
- sequences;
- issued certificates;
- issuer branding;
- public verification.

Public verification must resolve the issuing institute and reveal only intended
certificate fields.

### 14.2 Integrations

Introduce tenant-owned references and policies for:

- SMS;
- email;
- payment services;
- AI/provider settings where applicable;
- quotas and rate limits.

Secrets must remain in Secret Manager. Database rows should store secret
references, not raw credentials.

### 14.3 Exit gate

> Certificates and messages contain the correct issuer, and no institute can
> consume, reveal, or modify another institute’s integration.

---

## 15. Phase 9 — Onboarding and subscription enforcement

### 15.1 Onboarding workflow

Build a platform-owner wizard:

1. institute identity;
2. plan and limits;
3. primary domain;
4. branding;
5. first branch;
6. first institute administrator;
7. settings and numbering;
8. integration readiness;
9. activation checklist.

### 15.2 Subscription and limits

Support:

- plan assignment;
- branch limit;
- administrator/staff limit;
- student limit;
- storage quota;
- feature flags;
- grace period;
- suspension;
- reactivation.

Limits must be enforced server-side and transactionally.

### 15.3 Exit gate

> A platform owner can onboard, limit, suspend, and reactivate an institute
> without database commands, and the institute cannot bypass its plan.

---

## 16. Final rollout and production migration

After all functional phases:

1. capture a fresh production reconciliation baseline;
2. restore or sanitize a production-like database in staging;
3. apply migrations in exact order;
4. run Phase 0 through final-phase suites;
5. test every role and tenant domain;
6. verify private storage migration;
7. deploy a no-traffic Cloud Run revision;
8. run authenticated smoke tests;
9. shift traffic gradually;
10. monitor errors, latency, database connections, Redis, storage, and security
    audit events;
11. retain a rollback revision and database/object rollback procedure;
12. remove compatibility and public-storage behavior only after reconciliation.

Never combine schema migration, object migration, public-bucket removal, and
100% traffic cutover into one irreversible action.

---

# Team development rules

## 17. Mandatory query rules

For every tenant-owned table:

```sql
SELECT ...
FROM tenant_table
WHERE institute_id = ?
```

For direct IDs:

```sql
SELECT ...
FROM tenant_table
WHERE id = ?
  AND institute_id = ?
```

Never load by ID and check ownership only in the browser.

## 18. Mandatory create/update rules

- derive institute ID from trusted request/session tenant context;
- do not accept `institute_id` from ordinary tenant forms or JSON;
- validate every referenced branch/user/student/batch belongs to that institute;
- use a transaction for parent/child writes;
- include institute ownership in uniqueness rules.

## 19. Mandatory storage rules

- use the centralized storage service;
- do not build raw GCS public URLs;
- do not upload secondary-tenant files to legacy global prefixes;
- do not trust a database path without verifying its tenant prefix;
- use authorized application delivery for private files;
- do not delete an old object before the replacement and database commit are
  safely completed.

## 20. Mandatory test pattern

Each phase must include:

- two institutes;
- intentionally overlapping business identifiers;
- positive same-tenant tests;
- negative cross-tenant list tests;
- negative direct-ID tests;
- negative file tests;
- hostname/session mismatch tests;
- Global IT reconciliation;
- cleanup;
- migration rerun/idempotency;
- Docker/MySQL execution.

## 21. Definition of done for a phase

A phase is complete only when:

- schema migration is idempotent;
- backfill is deterministic;
- every affected route is tenant-scoped;
- UI selectors are tenant-scoped;
- direct IDs are protected;
- storage is tenant-scoped;
- caches are tenant-scoped;
- tests pass for overlapping fixtures;
- Global IT baseline reconciles;
- local Docker is healthy;
- staging no-traffic verification passes before production;
- documentation and route/table registries are updated.

---

## 22. Current test commands

Run inside the rebuilt Docker web container with `PYTHONPATH=/app`:

```text
scratch/test_multi_institute_phase0.py
scratch/test_multi_institute_phase1.py
scratch/test_multi_institute_phase2.py
scratch/test_multi_institute_phase3.py
```

Expected final markers:

```text
phase0_isolation_characterization=OK
phase1_tenant_foundation=OK
PHASE2_MYSQL_TESTS=PASS
PHASE3_MYSQL_TESTS=PASS
```

---

## 23. Immediate next task

Start **Phase 4 — CRM and student identity**.

Do not unlock the Leads or Students sidebar modules until:

1. all relevant tables are backfilled and constrained;
2. staff and student authentication is hostname-bound;
3. all direct-ID routes are tenant-scoped;
4. student uploads use tenant-prefixed storage;
5. two institutes with the same student code pass the full isolation suite.

