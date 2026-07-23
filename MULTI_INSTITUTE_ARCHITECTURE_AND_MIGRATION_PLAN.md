# Multi-Institute Architecture and Migration Plan

**Application:** Global IT ERP / LMS  
**Current stack:** Flask, raw SQL through the project database wrapper, MySQL 8.4, Cloud Run, Cloud SQL, GCS, Redis/Flask-Limiter  
**Audit date:** 22 July 2026  
**Status:** Architecture and code audit complete; implementation not started

## 1. Executive decision

The application can support multiple independent institutes, each with its own branding, branches, administrators, staff, students, operational data, LMS configuration, documents, numbering rules, and integrations.

The recommended first architecture is:

- one Flask application and deployment;
- one shared MySQL database and schema;
- an explicit `institute_id` ownership column on every institute-owned root table;
- tenant scope derived from a trusted hostname and revalidated against the authenticated account;
- database queries and writes that fail closed when an institute context is absent;
- branches as children of an institute, never as the tenant boundary;
- private, institute-prefixed object storage;
- platform-owned content separated explicitly from institute-owned content.

Do **not** combine this migration with a Flask-to-Django rewrite. Existing planning documents under `docs/planning/` describe a Django target, but the running application contains hundreds of raw SQL statements across Flask blueprints. Changing the framework and the tenancy boundary together would make data-isolation regressions much harder to detect and roll back.

## 2. Current business model understood from the code

### 2.1 Current ownership hierarchy

The effective hierarchy today is:

```text
One implicit company (Global IT Education)
  ├─ company_profile row id=1
  ├─ globally unique users and student codes
  ├─ globally shared courses, LMS library, settings and integrations
  └─ branches
       ├─ users/staff
       ├─ students and leads
       ├─ batches and attendance
       ├─ invoices and expenses
       └─ assets
```

There is no `institutes` table and no active `institute_id` or `tenant_id` request context. A certificate template has an unused-looking `institution_id` column, but it has no corresponding institute table or enforced foreign key and does not provide isolation.

### 2.2 Main business capabilities

The current code supports:

- administrator and staff authentication;
- multiple Global IT Education branches;
- CRM leads and follow-ups;
- student admission and profile records;
- course, batch and trainer management;
- attendance, leave, warnings and follow-ups;
- invoices, installments, receipts, expenses and bad debt;
- assets and allocations;
- LMS programs, master content, assignments, submissions, grading and progress;
- exams, question banks and applications;
- certificates, templates, sequences and public verification;
- imports, exports, reports, SMS messages and reminders;
- a public marketing website and enquiry form.

The application therefore already has most institute-level business functions. The missing layer is secure ownership above branches.

## 3. Evidence that the application is single-institute

### 3.1 Authentication and session

- Staff login searches `users` by username globally in `modules/core/routes.py`; the session stores `user_id`, `role`, `branch_id`, and `can_view_all_branches`, but no institute.
- `login_required`, `admin_required`, and `lms_content_manager_required` in `modules/core/utils.py` validate authentication and role only.
- Student login in `modules/students/routes.py` searches globally by `student_code`.
- The mobile remember token contains only `student_id`, `student_code`, and a password fingerprint. It has no institute binding.
- Student restoration looks up a global student ID/code pair and does not validate the request hostname.
- The role named `admin` currently means administrator of the entire application, not administrator of one institute.

**Consequence:** if a second institute were inserted into the existing tables, usernames, student codes and direct object IDs would exist in one global security namespace.

### 3.2 Branding and settings

- `company_profile` is constrained to one row (`id = 1`) in `db.py`.
- `get_company_profile()` always loads that single row and caches it globally.
- `app.py` injects that same company into every rendered request.
- company logo object paths use the shared `logos/` prefix.
- `attendance_calendar_settings` and `certificate_settings` are also single-row tables using `id = 1`.
- certificate verification and certificate services explicitly read the global company/settings rows.
- templates and seed data contain hard-coded `Global IT Education`, `Global IT ERP`, `GIT`, Hoskote contact details, and old Global IT domains.

**Consequence:** one institute changing its logo, certificate settings, working calendar, or prefix would change it for everyone.

### 3.3 Branch management

- `branches` has no institute owner.
- branch list/create/edit/toggle routes query by branch ID alone.
- branch name and code checks are global instead of unique within an institute.
- users can have `can_view_all_branches`, which currently means all branches in the entire database.
- many operational modules correctly enforce branch scope, but branch scope cannot separate two institutes.

**Consequence:** enabling another institute to create branches now would expose Global IT branches to its administrator.

### 3.4 Raw SQL scope

The major route files contain approximately:

| Module | Routes | SQL operations/references | Existing tenant references |
|---|---:|---:|---:|
| LMS administration | 91 | 428 | 0 |
| Billing | 49 | 324 | 0 |
| Attendance | 20 | 169 | 0 |
| Student portal | 27 | 149 | 0 |
| Reports/imports | 15 | 96 | 0 |
| Leads | 18 | 93 | 0 |
| Exams | 21 | 74 | 0 |
| Core users/branches/dashboard | 17 | 61 | 0 |
| Certificates | 15 | 38 | 0 |

These counts are an audit indicator, not a claim that every query needs a direct `institute_id` predicate. Child rows can sometimes be safely scoped through a verified parent join. Every read and mutation path still needs an explicit ownership decision and a regression test.

### 3.5 Global dashboards and direct-ID access

Representative single-institute patterns include:

- the admin dashboard aggregates all receipts, expenses, students, leads, attendance, batches, leave requests and activity logs;
- core user edit/toggle routes use `WHERE id = ?`;
- branch edit/toggle routes use `WHERE id = ?`;
- multiple route modules load students, invoices, assignments, submissions, certificates, content, or batches by numeric ID and rely on branch/role checks where available;
- student LMS access checks student/program relationships but assumes all programs belong to the one institute;
- global LMS master-library routes have no institute ownership concept.

**Consequence:** direct-object-reference checks must become institute-aware before a second tenant is activated.

### 3.6 Public website and lead ownership

- `/` displays globally shared courses.
- course detail pages are hard-coded template files rather than institute-owned records.
- public enquiries are inserted without a branch or institute.
- website leads are assigned to hard-coded user ID `2`.
- phone validation assumes Indian mobile numbers for all tenants.

**Consequence:** the platform cannot currently determine which institute owns a public enquiry or which branding/catalogue should appear for a hostname.

### 3.7 File storage

- production uses one bucket (`global-it-erp-storage`).
- object keys are shared prefixes such as `student_photos/`, `documents/`, `logos/`, `signatures/`, and `certificates/`.
- object keys do not include institute IDs.
- `generate_public_url()` returns permanent public GCS URLs.
- the previously recorded production audit notes that the application bucket grants public object viewing.
- deleting or replacing an object is based on the supplied path without checking its tenant prefix.

**Consequence:** filename collisions, cross-institute discovery, unauthenticated access, and accidental cross-tenant deletion are possible unless storage is redesigned before onboarding tenants.

### 3.8 Integrations and secrets

- SMS gateway credentials are process-global environment variables.
- SMS sender wording includes Global IT Education in several billing paths.
- Google APIs, TinyMCE and storage configuration are deployment-global.
- reminder and automation scripts do not establish a tenant context.
- Redis rate-limit keys are shared and are not deliberately namespaced by institute.

**Consequence:** all institutes would use Global IT's SMS account and branding unless configuration is separated. Platform-wide provider credentials may remain shared, but tenant-owned credentials require encrypted per-institute configuration.

### 3.9 Numbering and uniqueness

Current identifiers are effectively global:

- staff username;
- student code;
- branch name and branch code;
- course name/slug assumptions;
- invoice and receipt numbers, including hard-coded `GIT/B/...` and `GIT/...` generation;
- certificate number and certificate settings prefix;
- certificate sequence `(template_code, year)`;
- LMS program slug and other names where application checks assume a single catalogue.

Many expected uniqueness rules are enforced in application code rather than MySQL constraints. Multi-institute migration must replace them with tenant-composite unique constraints.

## 4. Data ownership classification

### 4.1 New platform tables

Create these before altering business tables:

| Table | Purpose |
|---|---|
| `institutes` | Legal/display identity, slug, status, locale, timezone and lifecycle |
| `institute_domains` | Verified subdomains/custom domains and primary-domain selection |
| `institute_branding` | Logos, colours, portal labels, contact and document branding |
| `institute_settings` | Locale, currency, numbering, attendance and module settings |
| `institute_integrations` | References to tenant-specific secrets, never plaintext credentials |
| `platform_users` or platform role membership | Platform-owner access separated from tenant admins |
| `institute_memberships` | User-to-institute membership and role; initially one institute per staff user |
| `subscription_plans` | Platform-owned feature and capacity definitions |
| `institute_subscriptions` | Tenant plan, lifecycle, grace period and limits |
| `tenant_migration_runs` | Checkpoints, counts, errors, operator and rollback metadata |
| `tenant_security_audit` | Cross-tenant denials and privileged platform operations |

### 4.2 Direct institute-owned root tables

Add a non-null `institute_id` after backfill to at least:

```text
company_profile (or replace with institute_branding/settings)
branches
users / institute_memberships
students
leads
courses
expense_categories
attendance_calendar_settings
attendance_holidays
lms_programs
lms_master_chapters (if libraries are private per institute)
lms_rubrics
certificate_templates
certificate_settings
certificate_sequences
activity_logs
```

For defense in depth and efficient queries, also add `institute_id` to high-volume transactional tables even when ownership is derivable through a parent:

```text
batches, attendance_records, attendance_time_warnings, attendance_followups
invoices, receipts, installment_plans, expenses, bad_debt_writeoffs, reminder_logs
assets, asset_allocation, asset_logs
lms_student_program_access, lms_batch_program_access
lms_assignments, lms_assignment_submissions
lms_master_topic_progress, student_program_last_activity
lms_final_exam_applications, lms_final_exam_attempts, lms_chapter_mock_attempts
certificates, certificate_audit_logs
student_uploaded_documents, student_notes, leave_requests
```

### 4.3 Child tables that may inherit scope

Some tables can derive ownership from a parent foreign key, but every query must join the parent or the table should carry a denormalized `institute_id` for safer raw SQL. Examples include invoice items, follow-ups, LMS topic content, rubric criteria, and certificate template fields.

Because this application uses raw SQL rather than an ORM that automatically scopes relationships, the safer default is to denormalize `institute_id` onto frequently accessed child tables and validate it against the parent during writes.

### 4.4 Platform-global versus tenant-private LMS content

This is a required product decision. Recommended model:

- `library_scope = 'platform' | 'institute'` on master chapters/topics/content;
- platform content is readable but not directly editable by institute admins;
- an institute attaches platform content to its programs and can store approved overrides separately;
- institute-private content carries `institute_id` and is invisible to other institutes;
- assignments, submissions, student progress and reviews are always institute-owned;
- copying platform content creates a new institute-owned record with source lineage.

Do not use `institute_id IS NULL` casually as a bypass. All platform-global reads should require an explicit platform-content scope and permission.

## 5. Target request and security architecture

### 5.1 Tenant resolution

Resolve the institute in this order:

1. normalize and validate the original HTTPS hostname;
2. look up an active, verified row in `institute_domains`;
3. bind an immutable request-local `TenantContext` containing institute ID, status, primary domain, locale and timezone;
4. after login, verify the user/student belongs to exactly that institute;
5. store `institute_id` in the session/token as supporting evidence, but never trust the session without database revalidation;
6. reject unknown hosts and host/session mismatches before reaching business routes.

Local Docker should support hosts such as:

```text
globalit.localhost:8080
demo-institute.localhost:8080
platform.localhost:8080
```

Production should begin with `tenant-slug.globaliterp.com`. Custom domains should be a later phase because they require domain ownership verification, certificate provisioning, Cloud Load Balancer configuration and safe canonical redirects.

### 5.2 Flask implementation components

Add:

```text
modules/tenants/
  routes.py
  service.py
  permissions.py
services/tenant_context.py
services/tenant_query.py
services/tenant_storage.py
services/tenant_settings.py
```

Use Flask `g` or a request-local `contextvars.ContextVar`, cleared after every request. It must not be a process-global variable because Cloud Run/Gunicorn serves concurrent requests.

### 5.3 Query enforcement for the current raw-SQL codebase

An ORM manager described in the older Django documents cannot protect this code. Introduce current-stack controls:

- `require_tenant()` fails if no tenant is bound;
- `tenant_id()` returns only a verified request-local ID;
- scoped repository/service functions for root entities;
- `fetch_tenant_record(table, record_id, institute_id)` for authorized tables;
- write helpers that automatically include `institute_id` and reject cross-tenant foreign keys;
- a temporary SQL audit mode that logs tenant-table queries lacking a tenant predicate;
- production fail-closed guards for migrated routes;
- explicit `platform_scope()` available only to platform-owner services and background jobs.

Avoid accepting `institute_id` from forms, query strings, JSON, or URLs as authority. Platform-owner screens may select a tenant, but server-side authorization must bind the selected ID.

### 5.4 Permissions

Recommended roles:

| Role | Scope |
|---|---|
| `platform_owner` | Creates/suspends institutes, plans and platform catalogue; audited impersonation only |
| `institute_admin` | All enabled modules and all branches within one institute |
| `branch_admin` | Assigned branches within one institute |
| `staff` / `counselor` / `accountant` | Explicit module permissions and branch assignments |
| `trainer` | Assigned batches/programs/students |
| `student` | Own tenant and own records only |

Replace `can_view_all_branches` with institute-bounded branch grants. During compatibility, its meaning must become “all branches in my institute,” never all database branches.

### 5.5 Background jobs

Every scheduled or manual job must either:

- receive one `institute_id` and process only that tenant; or
- enumerate active institutes and create a separate, observable unit of work per institute.

Idempotency keys, Redis locks, cache keys, exported filenames and logs must include institute ID.

## 6. Branding and institute administration

An institute administrator should be able to manage:

- institute display name and short name;
- logo, favicon and optional login background;
- primary/secondary colours with contrast validation;
- address, phone, email, website and legal/registration numbers;
- timezone, locale, currency and date format;
- invoice, receipt, student and certificate prefixes;
- certificate templates, signatures and seals;
- public portal configuration;
- branches, branch administrators and staff;
- allowed modules within subscription limits.

Branding must be rendered from the resolved institute context, not a global context processor. User-supplied CSS must not be permitted; store validated design tokens only.

## 7. Storage and integration design

### 7.1 Storage keys

All new objects should use immutable tenant-prefixed keys:

```text
tenants/{institute_id}/branding/{uuid.ext}
tenants/{institute_id}/students/{student_id}/photos/{uuid.ext}
tenants/{institute_id}/students/{student_id}/documents/{uuid.ext}
tenants/{institute_id}/lms/content/{content_id}/{uuid.ext}
tenants/{institute_id}/lms/submissions/{submission_id}/{uuid.ext}
tenants/{institute_id}/certificates/{certificate_id}/{uuid.ext}
```

The storage service must require `institute_id` for upload, download, replace and delete. It must reject a key outside the active tenant prefix.

### 7.2 Private delivery

- remove public bucket access after all application paths use authorized downloads or short-lived signed URLs;
- validate tenant, role and record ownership before generating a URL;
- use short expirations and safe `Content-Disposition`;
- retain a controlled public path only for intentionally public assets such as logos or verified certificate renderings;
- record object owner, checksum, MIME type, size and lifecycle status in the database.

### 7.3 Secrets and SMS

Recommended options:

1. platform-managed SMS plan: shared gateway credentials, tenant-specific templates/quotas and platform billing;
2. bring-your-own-provider: institute settings store Secret Manager resource references, never secret values in MySQL;
3. hybrid plans supporting both.

Every outbound message should record institute, provider, template, recipient, purpose, result and cost. Message text must use tenant branding, not hard-coded Global IT strings.

## 8. Schema and migration mechanics

### 8.1 Global IT becomes tenant 1

Create the first institute from the existing profile:

```text
institutes.id = 1
name = Global IT Education
slug = global-it-education
primary domain = www.globaliterp.com
timezone = Asia/Kolkata
status = active
```

Backfill every existing institute-owned row with `institute_id = 1`. No current primary keys or public URLs should change in this step.

### 8.2 Expand, backfill, constrain

For each table:

1. add nullable `institute_id` and supporting index;
2. deploy dual-read compatibility;
3. backfill in small primary-key batches;
4. verify zero nulls and zero parent/child mismatches;
5. deploy dual-write;
6. change `institute_id` to non-null;
7. add foreign key and composite uniqueness constraints;
8. remove legacy unscoped reads only after regression and shadow-query comparison.

Do not add a non-null default of `1` for runtime inserts. That could silently place a new institute's records into Global IT. Defaults may be used only in a controlled one-time backfill migration and must then be removed.

### 8.3 Composite uniqueness changes

Examples:

```text
users:                 UNIQUE(institute_id, username)
students:              UNIQUE(institute_id, student_code)
branches:              UNIQUE(institute_id, branch_code)
branches:              UNIQUE(institute_id, branch_name)
courses:               UNIQUE(institute_id, course_name)
lms_programs:          UNIQUE(institute_id, slug)
expense_categories:    UNIQUE(institute_id, category_name)
invoices:              UNIQUE(institute_id, invoice_no)
receipts:              UNIQUE(institute_id, receipt_no)
certificates:          UNIQUE(institute_id, certificate_number)
certificate_sequences: UNIQUE(institute_id, template_code, year)
```

Parent-child foreign-key ownership must also be validated. For example, an invoice from institute A cannot refer to a student or branch from institute B even if the numeric IDs are valid.

### 8.4 Index design

Make `institute_id` the leftmost column in frequent tenant filters, for example:

```text
leads(institute_id, branch_id, stage, status)
students(institute_id, branch_id, status)
batches(institute_id, branch_id, status)
attendance_records(institute_id, attendance_date, batch_id)
invoices(institute_id, branch_id, status, invoice_date)
receipts(institute_id, receipt_date)
lms_assignment_submissions(institute_id, review_status, submitted_at)
lms_master_topic_progress(institute_id, student_id, program_id, master_topic_id)
activity_logs(institute_id, created_at)
```

Use `EXPLAIN` against realistic tenant sizes before dropping previous indexes.

## 9. Module-by-module remediation checklist

### Core, users and branches — critical

- tenant-aware staff login and session binding;
- distinguish platform owner from institute admin;
- scope user and branch CRUD by institute;
- validate selected branch belongs to active institute;
- convert company profile and global dashboard aggregates;
- institute-bound cache keys and activity logs;
- institute-level branch limits.

### Students and admission — critical

- tenant-aware student login and mobile cookie payload;
- decide whether student code is unique per institute or platform-wide;
- scope every student direct-ID read/write;
- prefix photos, signatures and documents in storage;
- validate lead, course, batch and branch ownership during admission;
- clear/reject sessions after domain or institute mismatch.

### Billing, expenses and bad debt — critical

- tenant-scope all financial reads and writes;
- tenant-specific invoice/receipt prefixes and atomic sequences;
- tenant branding in PDFs, print views, SMS and public tokens;
- bind public invoice/receipt tokens to institute and retain high-entropy tokens;
- institute-specific categories, tax/legal fields and currency;
- tenant filters in all dashboard totals, receivables and exports.

### Attendance and reports — critical

- all-branches means all branches within one institute;
- verify batch/student/trainer/branch share the same institute;
- tenant-specific calendars and holidays;
- tenant filters in reports, CSV imports and bulk updates;
- prevent imported branch/user IDs from selecting another tenant's rows.

### Leads and public website — high

- resolve institute before showing catalogue or accepting an enquiry;
- remove hard-coded owner ID `2` and configure per-tenant routing;
- scope pipelines, follow-ups and AI context;
- allow tenant-specific country/phone validation;
- replace hard-coded course pages with tenant-aware content or clearly retain the root domain as Global IT's public site.

### LMS and exams — critical

- decide platform catalogue versus institute-private content;
- scope programs, course mappings, access, assignments, submissions, reviews and progress;
- verify trainer/batch/student/program all belong to the same tenant;
- tenant-aware editorial revisions and review queues;
- prevent copied object paths from crossing storage prefixes;
- tenant-scope test attempts, applications, question banks and completion rules.

### Certificates — critical

- replace single global settings row with one settings row per institute;
- tenant-specific templates, signatures, sequences and certificate prefixes;
- include institute ID in verification lookup or guarantee platform-global certificate numbers;
- render the issuing institute snapshot into the certificate for historical accuracy;
- keep public verification limited to the minimum intended public fields.

### Assets — high

- tenant-scope assets, allocations and logs;
- ensure assigned user/student and branch are within the same institute;
- make asset codes unique within the institute.

### Automation, imports and exports — critical

- require tenant context for every script;
- remove hard-coded numeric branch/user IDs;
- namespace idempotency locks and output files;
- provide tenant-level export and restore tooling;
- audit every bulk import for cross-tenant foreign-key injection.

## 10. Implementation phases

### Phase 0 — Baseline and isolation test harness

- freeze schema documentation from production;
- enumerate routes, SQL statements, tables, unique indexes and file paths;
- build two synthetic institutes with overlapping usernames, student codes, branch codes and record names;
- add negative tests that tenant A cannot list, view, update, delete, download, review, export, or infer tenant B records;
- record current Global IT totals for reconciliation.

**Exit gate:** existing Global IT tests pass and cross-tenant tests fail against the old code for the expected reasons, proving the harness detects leaks.

**Completed locally — 22 July 2026.** Evidence:

- `phase0/table_ownership_registry.json` covers all 65 current MySQL tables.
- `phase0/route_scope_rules.json` classifies all 299 current Flask routes, including eight legacy file-serving routes called out explicitly for later hardening.
- `phase0/two_institute_fixture.json` defines two logical institutes with intentionally overlapping branch codes, usernames, student codes, course slugs, document numbers and storage filenames.
- `scratch/test_multi_institute_phase0.py` validates the registries and fixtures, then safely detects and cleans up five known gaps: no tenant schema, global staff login namespace, global student-code namespace, global admin branch visibility and non-prefixed storage keys.
- `phase0/global_it_reconciliation.py` emits read-only, PII-free schema, row-count and financial/LMS aggregates.
- `phase0/global_it_baseline_20260722.json` freezes the local Docker clone baseline. A fresh production baseline must be captured immediately before any production backfill.

### Phase 1 — Tenant foundation without behavior change

- create institute/domain/branding/settings/membership/audit tables;
- seed Global IT as institute 1;
- introduce request-local tenant resolution in observe-only mode;
- add institute ID to sessions and logs while retaining current authorization;
- add tenant-aware cache key helpers.

**Exit gate:** `www.globaliterp.com` always resolves to institute 1; unknown hosts fail safely; existing production behavior is unchanged.

**Completed locally — 22 July 2026.** Evidence:

- Added the idempotent MySQL migration `migrations/20260722_multi_institute_phase1_foundation.sql` and matching SQLite bootstrap schema.
- Added `institutes`, domains, branding, settings, integrations, memberships, migration-run and tenant-security-audit tables.
- Seeded Global IT as institute `1`, mapped `globaliterp.com` and `www.globaliterp.com`, copied compatibility branding/settings, and created memberships for all existing staff.
- Added nullable `activity_logs.institute_id`, backfilled every historical log to Global IT, indexed it, and enforced its institute foreign key.
- Added request-local `TenantContext` using `contextvars`, verified-domain resolution, localhost development fallback, observe-mode compatibility and strict-mode host/session rejection.
- Staff/student sessions and new mobile tokens now carry institute context; old student mobile tokens remain valid during compatibility.
- Company profile and generic cache-key helpers are institute-keyed without changing rendered Global IT branding.
- Unknown-host and tenant/session strict denials are recorded in `tenant_security_audit` without storing credentials.
- `scratch/test_multi_institute_phase1.py` verifies schema/seed integrity, observe and strict modes, session compatibility, security auditing, tenant cache namespaces and parallel request isolation.
- Local migration was applied twice successfully; dedicated Phase 0/1 and existing assignment/LMS regression suites passed.
- Production remains unchanged. The migration must be applied before deploying this application code.

### Phase 2 — Core identity, users and branches

- backfill and constrain users and branches;
- tenant-scope staff login and branch CRUD;
- introduce platform-owner/institute-admin separation;
- change `can_view_all_branches` semantics;
- implement branch limits and tenant administration UI.

**Exit gate:** a second institute admin can create only its own branches and cannot address Global IT users/branches by ID.

### Phase 3 — Branding, domains and storage foundation

- migrate global profile/settings to institute settings;
- render branding through tenant context;
- add subdomain support locally and at the load balancer;
- implement tenant-prefixed storage and authorized file delivery;
- migrate existing Global IT objects without breaking stored paths.

**Exit gate:** two domains render different brands; files cannot be read/replaced/deleted across tenants; public bucket access can be removed.

### Phase 4 — CRM and student identity

- scope leads, follow-ups, students, documents, admission and portal authentication;
- migrate website lead routing;
- version and invalidate old student mobile cookies;
- add tenant-specific student numbering.

**Exit gate:** overlapping student codes work on different tenant domains and never authenticate on the wrong domain.

### Phase 5 — Finance and assets

- scope billing, receipts, expenses, installments, bad debt, reminders and assets;
- replace GIT prefixes with atomic tenant sequences;
- tenant-brand all documents and messages;
- reconcile balances by institute and branch.

**Exit gate:** financial totals for Global IT match baseline exactly and cross-tenant financial ID tests all deny access.

### Phase 6 — Attendance and reporting

- scope batches, attendance, holidays, follow-ups and reports;
- harden bulk import/export;
- add institute-aware scheduling and background jobs.

**Exit gate:** tenant-level attendance totals reconcile, branch selectors never contain another institute, and imports reject foreign IDs.

### Phase 7 — LMS and exams

- implement platform versus institute library ownership;
- scope all LMS operational tables, reviews, progress and attempts;
- migrate Global IT's library/content ownership;
- tenant-prefix LMS storage and preview/download authorization.

**Exit gate:** two institutes may use/copy the same platform content while assignments, submissions, reviews and progress remain private.

### Phase 8 — Certificates and integrations

- tenant settings/templates/sequences and public verification;
- tenant-owned secret references and messaging policies;
- per-tenant quotas, audit and failure handling.

**Exit gate:** certificates and messages contain the correct issuer and no tenant can consume or reveal another tenant's integration.

### Phase 9 — Onboarding and subscription enforcement

- platform owner console;
- institute onboarding wizard;
- plans, limits, grace/suspension lifecycle and feature flags;
- domain verification and optional custom-domain workflow;
- tenant export/deactivation policy.

**Exit gate:** a new institute can be provisioned without a database/code deployment and is usable only within purchased limits.

### Phase 10 — Production migration and controlled activation

- create verified backup and restore rehearsal;
- apply expand migrations;
- backfill Global IT with reconciliation reports;
- deploy Global IT-only tenant enforcement;
- run shadow query comparison and security tests;
- activate one internal/demo tenant, then one pilot institute;
- monitor denied cross-tenant attempts, query latency, storage failures and financial reconciliation;
- only then enable general onboarding.

**Exit gate:** zero unowned rows, zero ownership mismatches, zero cross-tenant test failures, reconciled Global IT totals, documented rollback, and pilot sign-off.

## 11. Required automated security matrix

For every institute-owned resource, test:

| Operation | Same tenant/allowed role | Same tenant/wrong branch or role | Different tenant | Missing tenant context |
|---|---|---|---|---|
| List/search/count | Allow | Filter/deny | Never visible | Fail closed |
| View by ID | Allow | Deny as appropriate | 404/deny | Fail closed |
| Create | Allow within plan | Deny | Cannot choose foreign owner | Fail closed |
| Update/delete | Allow | Deny | Deny and audit | Fail closed |
| Export/download/preview | Allow | Deny | Deny and audit | Fail closed |
| Bulk action/import | Allow validated rows | Reject invalid rows | Reject entire unsafe transaction | Fail closed |

Also test hostname spoofing, stale sessions, suspended tenants, platform impersonation, signed URL expiry, cache-key isolation, background jobs, error pages, pagination counts, aggregate totals and rate limits.

## 12. Migration verification queries and invariants

Before activating a second tenant, all must be true:

- every tenant-owned row has `institute_id`;
- every branch/user/student belongs to exactly one institute;
- every child and parent institute ID matches;
- no duplicate composite business identifiers exist;
- Global IT pre/post counts and financial totals reconcile;
- no storage object referenced by one tenant exists under another tenant prefix;
- no active session lacks institute identity after the compatibility deadline;
- every route has a declared scope: public platform, public tenant, tenant user, tenant student, or platform owner;
- SQL audit reports zero unscoped tenant-table queries on exercised routes;
- production logs contain no raw secrets or cross-tenant record data.

## 13. Rollback and recovery

- use expand/contract migrations; do not drop legacy ownership columns during initial rollout;
- keep Global IT primary keys stable;
- make backfills idempotent and checkpointed;
- retain old object keys until copied objects pass checksum validation;
- feature-flag tenant resolution and each migrated module;
- rollback application traffic independently of schema expansion;
- rehearse full Cloud SQL restore and institute-level logical export/import;
- do not onboard a paying external institute until backups and deletion protection meet the agreed recovery objectives.

## 14. Principal risks

| Risk | Severity | Required mitigation |
|---|---|---|
| Cross-tenant data exposure through raw SQL/IDOR | Critical | Fail-closed tenant context, query helpers, route matrix and two-tenant tests |
| Public/shared object storage | Critical | Tenant prefixes, authorization, signed URLs and remove public bucket IAM |
| Wrong-tenant financial writes | Critical | Composite ownership checks, transactions, reconciliation and immutable audit |
| Global authentication namespace | Critical | Host-bound login and composite uniqueness |
| Global settings/cache contamination | High | Tenant settings rows and tenant-prefixed cache keys |
| Background job runs without tenant | High | Required tenant job parameter or explicit platform enumeration |
| Framework rewrite mixed with tenancy | High | Keep Flask during tenant migration |
| Per-tenant restore complexity | High | Logical export/import plus restore rehearsal |
| Custom-domain operational complexity | Medium | Subdomains first; verified custom domains later |

## 15. Decisions required before Phase 1 implementation

1. Will staff usernames be unique per institute or globally unique?
2. Will student codes be unique per institute? Recommended: yes, with domain-bound login.
3. Is the LMS master library platform-shared, institute-private, or hybrid? Recommended: hybrid with immutable platform content plus tenant copies/overrides.
4. Will the root `www.globaliterp.com` remain Global IT's website, or become a platform landing page?
5. Will institutes initially receive only `slug.globaliterp.com`, with custom domains postponed? Recommended: yes.
6. Will SMS/email be platform-managed, bring-your-own, or hybrid?
7. Which modules and limits belong to the first subscription plans?
8. What backup recovery objectives are required before external tenant onboarding?
9. Can a staff user belong to multiple institutes? Recommended initial rule: no; model memberships so this can be enabled later.
10. What data retention/export guarantee is offered when an institute leaves?

## 16. Recommended immediate next step

Start only **Phase 0 — Baseline and isolation test harness**. Do not add `institute_id` columns ad hoc in feature routes before the ownership map, test fixtures, migration invariants and platform-versus-tenant LMS decision are approved.

The first implementation deliverables should be:

1. a machine-readable table ownership registry;
2. two-tenant MySQL fixtures using overlapping business identifiers;
3. a route scope registry;
4. cross-tenant negative tests for core/users/branches;
5. Global IT baseline reconciliation queries;
6. the Phase 1 additive migration, reviewed but not yet applied to production.

## Appendix A — Current table ownership registry

This registry covers all tables present in the audited local MySQL schema. “Direct” means add and enforce `institute_id`. “Inherited” means ownership follows a parent but a direct column is still recommended where noted for raw-SQL safety/performance. “Platform/hybrid” requires an explicit product scope.

| Current table | Target ownership | Ownership path / required change |
|---|---|---|
| `institutes` | Platform | SaaS tenant registry; created in Phase 1 |
| `institute_domains` | Direct | Verified hostname-to-institute mapping; created in Phase 1 |
| `institute_branding` | Direct | Institute design/contact identity; created in Phase 1 |
| `institute_settings` | Direct | Institute numbering/locale defaults; created in Phase 1 |
| `institute_integrations` | Direct | Provider metadata and secret references; created in Phase 1 |
| `institute_memberships` | Direct | Staff-to-institute membership; created in Phase 1 |
| `tenant_migration_runs` | Direct | Checkpointed migration history; created in Phase 1 |
| `tenant_security_audit` | Direct | Tenant resolution and denial events; created in Phase 1 |
| `company_profile` | Direct | Replace singleton with institute branding/profile |
| `branches` | Direct | Institute parent; composite name/code uniqueness |
| `users` | Direct/membership | Bind to institute membership; platform owners separate |
| `students` | Direct | Composite student-code uniqueness |
| `leads` | Direct | Institute and optional branch owner |
| `followups` | Inherited | Lead and user must share institute |
| `courses` | Direct or hybrid | Tenant catalogue; optionally platform course definitions |
| `batches` | Direct | Course, branch and trainer ownership validated |
| `student_batches` | Inherited/direct recommended | Student and batch institute IDs must match |
| `attendance_records` | Direct | High-volume; student/batch/branch match |
| `attendance_time_warnings` | Direct | Student/batch/branch match |
| `attendance_followups` | Direct | Student/batch/branch match |
| `attendance_calendar_settings` | Direct | Replace singleton with one row per institute |
| `attendance_holidays` | Direct | Tenant calendar |
| `leave_requests` | Inherited/direct recommended | Student institute; reviewer must match |
| `invoices` | Direct | Student/branch ownership; tenant sequence |
| `invoice_items` | Inherited/direct recommended | Invoice and course ownership |
| `installment_plans` | Inherited/direct recommended | Invoice ownership |
| `receipts` | Direct | Invoice ownership; tenant sequence |
| `bad_debt_writeoffs` | Inherited/direct recommended | Invoice and authorizer ownership |
| `expense_categories` | Direct | Composite category uniqueness |
| `expenses` | Direct | Branch/category/user ownership |
| `reminder_logs` | Direct | Student/invoice/installment ownership |
| `assets` | Direct | Tenant/branch owner; composite asset code |
| `asset_allocation` | Inherited/direct recommended | Asset and assignee ownership |
| `asset_logs` | Inherited/direct recommended | Asset and actor ownership |
| `activity_logs` | Direct | Required for tenant audit and retention |
| `student_uploaded_documents` | Direct recommended | Student owner plus tenant storage prefix |
| `student_profile_update_requests` | Inherited/direct recommended | Student/processor ownership |
| `student_notes` | Direct recommended | Student/content ownership |
| `lms_programs` | Direct | Institute program and composite slug |
| `lms_chapters` | Inherited | Program owner; legacy path |
| `lms_topics` | Inherited | Chapter/program owner; legacy path |
| `lms_topic_contents` | Hybrid/direct recommended | Tenant or explicit platform content scope |
| `lms_topic_attachments` | Hybrid/direct recommended | Tenant or platform scope plus storage prefix |
| `lms_content_revisions` | Direct recommended | Content scope; creators/reviewers validated |
| `lms_program_resources` | Inherited/direct recommended | Program owner plus storage prefix |
| `lms_master_chapters` | Platform/hybrid | Explicit platform or institute owner |
| `lms_master_topics` | Platform/hybrid | Inherit master chapter scope |
| `lms_master_topic_bridge` | Platform/hybrid | Both linked topics must share valid scope |
| `lms_program_chapters` | Inherited | Program tenant may link approved platform/private content |
| `lms_assignments` | Direct | Institute operational data, even for platform topics |
| `lms_assignment_submissions` | Direct | Assignment and student ownership |
| `lms_rubrics` | Direct or hybrid | Institute rubric or read-only platform rubric |
| `lms_rubric_criteria` | Inherited | Rubric owner |
| `lms_submission_rubric_scores` | Inherited/direct recommended | Submission and criterion scope validated |
| `lms_student_program_access` | Direct | Student/program/batch ownership |
| `lms_batch_program_access` | Direct | Batch/program ownership |
| `lms_course_program_map` | Direct | Course/program ownership |
| `lms_student_topic_progress` | Direct recommended | Student/topic scope |
| `lms_topic_progress` | Direct recommended | Student/topic legacy scope |
| `lms_master_topic_progress` | Direct | Student/program/topic scope; unique key gains institute |
| `student_program_last_activity` | Direct | Student/program/topic scope; unique key gains institute |
| `lms_mock_tests` | Direct | Program/chapter/topic scope |
| `lms_student_test_results` | Direct | Student/test scope |
| `lms_question_bank` | Platform/hybrid | Question content scope explicit |
| `lms_chapter_mock_attempts` | Direct | Student/chapter scope |
| `lms_final_exam_applications` | Direct | Student/course scope |
| `lms_final_exam_attempts` | Direct | Application/student/course scope |
| `certificate_templates` | Direct | Replace unused/unconstrained institution field with FK |
| `certificate_template_fields` | Inherited | Template owner |
| `certificate_settings` | Direct | Replace singleton with one row per institute |
| `certificate_sequences` | Direct | Composite institute/template/year sequence |
| `certificates` | Direct | Issuer, student, course and template ownership |
| `certificate_audit_logs` | Direct recommended | Certificate and actor ownership |

## Appendix B — Code hotspot register

These files contain the current single-institute assumptions or must be reviewed before their module can be declared tenant-safe:

| Area | Primary code files | Main remediation |
|---|---|---|
| Database/bootstrap/cache | `db.py` | Institute schema, backfill, tenant-aware profile cache, seeds and constraints |
| App request lifecycle | `app.py` | Host resolution, request context, context processors and error behavior |
| Configuration/deployment | `config.py`, `cloudbuild.yaml`, `DEPLOYMENT.md`, Docker Compose files | trusted hosts, wildcard local domains, platform versus tenant settings |
| Auth/roles | `modules/core/utils.py`, `modules/core/routes.py` | tenant-bound login, platform/institute roles, scoped user/branch CRUD |
| Student authentication | `modules/students/routes.py` | tenant-bound code lookup, session and mobile token |
| Storage | `services/storage.py` | mandatory tenant prefixes, private delivery and delete guards |
| SMS | `modules/core/sms.py` | platform/tenant provider selection and tenant message audit |
| Leads | `modules/leads/routes.py`, `helpers.py`, `services.py`, `ai_helper.py` | tenant filters, assignments and AI context |
| Website | `modules/website/routes.py`, `templates/website/**` | host-specific brand/catalogue/enquiry ownership; remove user ID 2 |
| Billing | `modules/billing/routes.py`, `auto_reminders.py`, `templates/billing/**` | tenant financial scope, numbering, documents and messages |
| Attendance | `modules/attendance/routes.py`, `templates/attendance/**` | institute-bounded branch access and calendars |
| Reports/imports | `modules/reports/routes.py`, `modules/import_export/routes.py`, related templates | scoped aggregates, exports and foreign-ID validation |
| Bad debt | `modules/baddebt/routes.py` | invoice/authorizer tenant scope |
| Assets | `modules/assets/routes.py` | asset/branch/assignee tenant scope |
| LMS administration | `modules/lms_admin/routes.py`, `branch_helpers.py`, `publishing.py`, `editorial.py` | catalogue ownership and all operational tenant filters |
| Student LMS | `modules/students/routes.py` | program/content/access/progress ownership |
| Exams | `modules/exams/routes.py` | questions, applications and attempts |
| Certificates | `modules/certificates/*.py`, `templates/certificates/**` | issuer settings, sequences, rendering and verification |
| Automation | `scripts/*.py` | explicit tenant job context, checkpoints and tenant-safe identifiers |
| Shared layouts | `templates/base.html`, `templates/login_base.html`, `templates/print_base.html`, `templates/includes/**`, `templates/students/base.html` | tenant brand tokens and navigation permissions |
| Hard-coded branding | LMS titles, certificate verification/templates, website course templates, billing SMS strings and `db.py` seed values | replace with tenant context/settings |

No module should be marked complete merely because its list page is filtered. Its create, edit, delete, direct-ID, bulk action, count, export, file, API, background-task and public-token paths must all pass the security matrix in Section 11.
