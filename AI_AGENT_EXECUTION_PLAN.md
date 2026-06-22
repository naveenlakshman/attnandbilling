# AI Agent Execution Plan

This document defines the roles, input contexts, expected outputs, and quantitative success criteria for 10 specialized AI agents designed to execute the Flask-to-Django ERP migration.

---

## Agent Registry & Specifications

### Agent 1: Architecture Analyst
* **Responsibilities**: Establish the Django project scaffold, structure base templates, map custom URL patterns, and define global layout settings (such as static and media directory paths).
* **Inputs**: `SYSTEM_ARCHITECTURE.md`, `DJANGO_PROJECT_STRUCTURE.md`.
* **Outputs**: Boilerplate Django project file tree, standard base Jinja/Django templates, configurations in `settings/base.py`, and primary `urls.py`.
* **Success Criteria**:
  * The project runs locally (`python manage.py check` returns 0 errors).
  * Main site assets (CSS, JS) load without HTTP 404 errors.

### Agent 2: Database Architect
* **Responsibilities**: Map all 50+ SQLite schemas into clean Django Python models. Declare proper indices, foreign key references, unique constraints, and float-to-decimal mappings.
* **Inputs**: `db_schema.txt`, `DATABASE_MIGRATION_PLAN.md`.
* **Outputs**: Django model modules inside each corresponding application directory (`apps/core/models/`, `apps/crm/models.py`, etc.).
* **Success Criteria**:
  * `makemigrations` succeeds with no circular dependency warnings.
  * SQL migrations compile and run successfully against a local MySQL database.

### Agent 3: Django Core Developer
* **Responsibilities**: Set up User authentication profiles (extending `AbstractUser`), create branch management layouts, build custom session middlewares, configure the SMS REST client service, and register lookup models in Django Admin.
* **Inputs**: `PROJECT_ANALYSIS.md`, `SECURITY_REVIEW.md`, `apps/core/models/`.
* **Outputs**: Custom User model, login/logout views, branch management views, custom session validation middleware, SMS service, and `admin.py` configurations.
* **Success Criteria**:
  * Successful authentication with staff and admin roles.
  * Attempting to access admin views as a student returns a HTTP 403 Forbidden.
  * Standard Django admin registers and allows CRUD operations on branches.

### Agent 4: CRM Developer
* **Responsibilities**: Migrate Leads and Follow-ups database structures, implement the lead temperature scoring engine, integrate the Gemini AI assistant counselor suggestions API, and design the Kanban workflow layout.
* **Inputs**: `modules/leads/`, `PROJECT_ANALYSIS.md`, `apps/crm/models.py`.
* **Outputs**: Lead list views, Lead creation forms, detail views, followup timeline endpoints, Kanban stages endpoint, and AI suggestions handler.
* **Success Criteria**:
  * Leads can be created, updated, and soft-deleted.
  * The lead score updates correctly in the database when a lead's source or timeframe is modified.
  * Counselors can only mutate leads they own, returning a HTTP 403 Forbidden if they attempt to modify unauthorized prospects.

### Agent 5: Billing Developer
* **Responsibilities**: Construct financial transaction views, invoices, custom installment calculators, receipt allocations, expense categories, cash outflows, and public PDF download tokens.
* **Inputs**: `modules/billing/`, `PROJECT_ANALYSIS.md`, `apps/finance/models.py`.
* **Outputs**: Student admission forms (generating invoice and installment tables), invoices list, invoice view and PDF generator, receipt creation form (automatically allocating payments to installments), expenses log, and secure public link handlers.
* **Success Criteria**:
  * Creating a receipt updates the parent invoice's amount paid and shifts installment statuses from `pending` -> `partially_paid` -> `paid` in chronological order.
  * Public download URL works with tokens and does not require credentials.

### Agent 6: Attendance Developer
* **Responsibilities**: Build academic batch management dashboards, batch scheduling conflict checkers, student batch mapping, daily attendance sheet marking, leave request processing, and defaulters follow-up screens.
* **Inputs**: `modules/attendance/`, `PROJECT_ANALYSIS.md`, `apps/academics/models.py`.
* **Outputs**: Batch CRUD forms, student assignment grids, daily mark-attendance templates, student leave application templates, and defaulters analysis lists.
* **Success Criteria**:
  * Attendance records cannot be marked twice for the same student-batch-date (enforcing database-level unique checks).
  * Students absent consecutively for 3 or more days appear on the Defaulters list.
  * Approved leave requests automatically backpopulate `leave` status to attendance tables.

### Agent 7: LMS Developer
* **Responsibilities**: Build syllabus course mapping, master chapters and topic trees, slide content viewers (handling embedded HTML and hotspots JSON data), assignments upload system, student progress trackers, and homework submissions review utilities.
* **Inputs**: `modules/lms_admin/`, `PROJECT_ANALYSIS.md`, `apps/lms/models.py`.
* **Outputs**: Program manager interfaces, master chapter/topic editors, student portal learning screens, assignments submission forms, and student submission review tables.
* **Success Criteria**:
  * Topic contents (videos, attachments) are served through permission-validated views.
  * Students cannot view program chapters unless explicitly authorized via student/batch program access models.
  * Student topic progress triggers database updates.

### Agent 8: Exams Developer
* **Responsibilities**: Implement MCQ question banks, randomize quiz generators, grade mock assessments, coordinate final certificate exam applications, and develop secure proctored testing screens.
* **Inputs**: `modules/exams/`, `PROJECT_ANALYSIS.md`, `apps/exams/models.py`.
* **Outputs**: MCQ management views, mock exam setup and submission endpoints, student final exam application forms, and final exam taking layout.
* **Success Criteria**:
  * Chapter mock exams dynamically query random questions from the chapter question pool.
  * Student cannot launch a final exam unless their application status is set to `APPROVED`.
  * Exam scores calculation logic matches SQLite results.

### Agent 9: QA Engineer
* **Responsibilities**: Write automated integration and unit test suites verifying views, forms validations, database constraints, business logics, and transaction calculations.
* **Inputs**: Existing test requirements, all target Django models, views, and urls.
* **Outputs**: Django tests modules (`tests/` inside each app folder) using `django.test.TestCase` and `pytest`.
* **Success Criteria**:
  * Test suites run successfully (`python manage.py test` returns no failures).
  * Code coverage exceeds 85% on billing, attendance, and LMS logic.

### Agent 10: Security Auditor
* **Responsibilities**: Audit the target codebase for security issues (SQL injection, CSRF bypasses, IDOR gaps, rate-limiting loopholes, static file vulnerabilities) and verify the final environment settings.
* **Inputs**: `SECURITY_REVIEW.md`, target Django settings, codebase files.
* **Outputs**: Vulnerability assessment reports and security hardening configurations.
* **Success Criteria**:
  * Automated tools (e.g. `bandit`, `pip-audit`) return zero high-severity findings.
  * `python manage.py check --deploy` passes with no security warnings.
