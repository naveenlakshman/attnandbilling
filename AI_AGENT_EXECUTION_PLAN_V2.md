# AI Agent Execution Plan V2

This document updates roles, contexts, and success criteria for the 10 specialized AI agents, aligning their tasks with SaaS multi-tenancy requirements.

---

## Agent Registry & Specifications

### Agent 1: SaaS Architecture Analyst
* **Responsibilities**: Configure the boilerplate Django project structure, setting dynamic template path routing and the base wildcard subdomain resolver middleware configurations.
* **Inputs**: `SYSTEM_ARCHITECTURE_V2.md`, `DJANGO_PROJECT_STRUCTURE_V2.md`.
* **Outputs**: Django configuration structure in `settings/base.py`, main `urls.py`, and base template wrappers.
* **Success Criteria**:
  * Scaffolding passes local check commands (`python manage.py check` returns 0).
  * System correctly serves files through the dynamic static files pipeline.

### Agent 2: SaaS Database Architect
* **Responsibilities**: Map all legacy models to MySQL tables, injecting the base `TenantModel` class, custom Manager query filters, and compound index definitions.
* **Inputs**: `db_schema.txt`, `DATABASE_MIGRATION_PLAN_V2.md`.
* **Outputs**: Model definitions (`models.py`) containing foreign keys to the `Institution` model on all tenant-isolated tables.
* **Success Criteria**:
  * Compiling database migrations runs without circular reference warnings.
  * DB schema executes cleanly against a local MySQL database.

### Agent 3: SaaS Core Developer
* **Responsibilities**: Create the custom user auth structure, tenant middleware context binder, branch management, and SMS REST client wrapper.
* **Inputs**: `PROJECT_ANALYSIS.md`, `SECURITY_REVIEW_V2.md`, `apps/core/models/`.
* **Outputs**: AbstractUser custom classes, login/logout routing, and `TenantResolutionMiddleware`.
* **Success Criteria**:
  * Middleware identifies subdomains and binds tenant IDs to the thread-local state.
  * Suspending an institution blocks traffic and redirects to a suspension screen.

### Agent 4: Scoped CRM Developer
* **Responsibilities**: Migrate Leads and Follow-ups database structures, and implement lead scoring heuristics under the active tenant context.
* **Inputs**: `modules/leads/`, `apps/crm/models.py`.
* **Outputs**: Lead dashboards, followup forms, pipeline Kanban API endpoints.
* **Success Criteria**:
  * Leads are isolated: a user in Tenant A cannot view or edit leads in Tenant B, returning a HTTP 404.

### Agent 5: SaaS Billing Developer
* **Responsibilities**: Create invoices, receipts, payment allocation engines, and public download pages. Enable custom invoice/receipt prefixes based on tenant white-label properties.
* **Inputs**: `modules/billing/`, `apps/finance/models.py`.
* **Outputs**: Billing collection views, receipt creation forms, invoice PDF generators, and Stripe/Razorpay webhook handlers.
* **Success Criteria**:
  * Invoices and receipts load tenant-specific logo URLs and metadata.
  * Receipts distribute funds chronologically across installments.

### Agent 6: Academics Developer
* **Responsibilities**: Build batches, daily roll-calls, student leaves, and consecutive absence defaulter lists.
* **Inputs**: `modules/attendance/`, `apps/academics/models.py`.
* **Outputs**: Batch calendars, attendance marking sheets, leave request forms.
* **Success Criteria**:
  * Double-marking checks prevent duplicate attendance records.
  * Defaulters analytics are isolated within each tenant scope.

### Agent 7: LMS Developer
* **Responsibilities**: Create chapter mapping syllabus interfaces and course slides. Configure file storage to redirect private media requests to pre-signed S3 links.
* **Inputs**: `modules/lms_admin/`, `apps/lms/models.py`.
* **Outputs**: Program manager views, lesson slide player, and homework upload APIs.
* **Success Criteria**:
  * Media download request views verify active enrollments and redirect to short-lived pre-signed URLs.

### Agent 8: Exams Developer
* **Responsibilities**: Build mock exam builders, quiz grading modules, and certificate applications, isolated to student enrollment contexts.
* **Inputs**: `modules/exams/`, `apps/exams/models.py`.

### Agent 9: QA & Isolation Auditor
* **Responsibilities**: Write automated test suites verifying views, form parameters, database constraints, and cross-tenant data leaks.
* **Inputs**: All Django apps, models, and views.
* **Outputs**: Integration tests in `tests/` folders.
* **Success Criteria**:
  * Test suites run successfully (`python manage.py test` returns no failures).
  * Automated cross-tenant tests verify that requests targeting other tenant IDs are rejected with a 404.

### Agent 10: Security Auditor
* **Responsibilities**: Audit views for IDOR gaps, confirm secure headers config, and run dependency vulnerability scans.
* **Inputs**: `SECURITY_REVIEW_V2.md`, settings modules, target codebase.
* **Outputs**: Vulnerability assessment reports.
* **Success Criteria**:
  * `python manage.py check --deploy` returns zero warnings.
  * Static analysis tools (e.g. `bandit`) return zero high-severity warnings.
