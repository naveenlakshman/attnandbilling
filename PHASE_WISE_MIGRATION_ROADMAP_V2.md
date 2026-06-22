# Phase-Wise Migration Roadmap V2

This document schedules the step-by-step roadmap for migrating the ERP into a SaaS multi-tenant, white-label platform across 10 distinct, topologically ordered phases.

---

## Roadmap Overview

```text
Phase 1: Planning ──────────► Phase 2: Foundation ────────► Phase 3: SaaS Core
                                                                   │
Phase 6: Attendance ◄───────── Phase 5: Billing ◄───────── Phase 4: CRM
       │
Phase 7: LMS ───────────────► Phase 8: Exams ─────────────► Phase 9: Async Reports ──► Phase 10: Cutover
```

---

## Detailed Phase Breakdown

### Phase 1: Planning & SaaS Design
* **Goals**: Establish architectural specifications for the SaaS layers (host resolver middleware, dynamic CSS color injection, custom Manager query filters, and data isolation schemas).
* **Deliverables**: Finalized schema maps for `Institution` and `Subscription` models, compound index specifications, and developer guidelines.
* **Dependencies**: None.

### Phase 2: MySQL Database & Django Project Foundation
* **Goals**: Create the central MySQL database, scaffold the Django project directory, inject application path routing, and declare the base abstract `TenantModel`.
* **Deliverables**: MySQL instance, Django scaffolding, base models, database connection pool configurations.
* **Exit Criteria**: `python manage.py migrate` executes successfully against a local MySQL database.

### Phase 3: SaaS Routing & Core System
* **Goals**: Build the subdomain resolver middleware, custom user auth models (with role mappings and institution foreign keys), branch managers, and system audit logs.
* **Deliverables**: `TenantResolutionMiddleware`, custom User model, login/logout workflows, branch CRUD, and SMS gateway interfaces.
* **Exit Criteria**: Logins dynamically identify if user is staff vs student, check active subscription status, and load correct tenant branding variables.

### Phase 4: CRM (Leads) Scoped Migration
* **Goals**: Migrate lead pipelines, follow-ups, and Gemini AI counseling integrations, enforcing that counselors can only view or edit prospects belonging to their tenant scope.
* **Deliverables**: CRM dashboard, follow-up timeline scheduler, and Kanban stage endpoints.
* **Exit Criteria**: Leads can be filtered by tenant context, and counselors trying to view/mutate foreign leads trigger an HTTP 404/403.

### Phase 5: Scoped Billing & Financial Transactions
* **Goals**: Build course configurations, invoices, receipts, payment allocation engines, and public download pages. Enable custom invoice/receipt prefixes based on tenant white-label properties.
* **Deliverables**: Billing collection screens, invoice generators (rendering tenant-specific logos and headers), and bad debt write-offs.
* **Exit Criteria**: Receipts automatically distribute funds chronologically across installments, and financial calculations match legacy SQLite balances.

### Phase 6: Academics, Batches, & Attendance
* **Goals**: Migrate class scheduling, daily roll-calls, student leaves, and consecutive absence defaulter trackers.
* **Deliverables**: Batch planner calendar, roll-call grids, and leave requests.
* **Exit Criteria**: Mark-attendance prevents duplicates via composite primary keys, and approved leaves backfill attendance fields correctly.

### Phase 7: LMS & Courseware Sharing
* **Goals**: Build master chapters repository, dynamic syllabus mapping, lecture slides, and assignment grading systems. Include custom visibility mappings to share master chapters while allowing custom branding.
* **Deliverables**: Master chapter editor, slide viewer, and homework upload portals.
* **Exit Criteria**: File responses check active enrollment and redirect to pre-signed S3 links, blocking unauthenticated downloads.

### Phase 8: Exams Module Scoping
* **Goals**: Migrate MCQ banks, chapter mock tests, and final certification exam proctoring, isolated to student enrollment contexts.
* **Deliverables**: Question pool managers, mock quiz layouts, and certificate exam review boards.

### Phase 9: Reports & Async Celery Exporters
* **Goals**: Integrate a background worker queue (Celery + Redis) to process bulk operations and compile tenant-scoped data backups without blocking HTTP threads.
* **Deliverables**: Celery queue scaffold, metrics dashboards, and tenant backup exporter utility.
* **Exit Criteria**: Institution Admins can download a ZIP backup of their isolated data, generated asynchronously.

### Phase 10: Production ETL Cutover & Dry-Runs
* **Goals**: Execute the ETL migration script to backfill data into the multi-tenant schema, validate row counts and checksums on a staging database, test white-label domains, and switch DNS.
* **Deliverables**: Live multi-tenant SaaS production server, active DNS mappings, operational backup profiles.
* **Exit Criteria**: Data validation audits (row counts, collections sums) show 100% matching results, UAT verifies correct branding colors, and DNS routes live traffic to the Django cluster.
