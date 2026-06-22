# Django Project Structure V2

This document details the updated folder layout, module configurations, model scopes, and asset management routing for the SaaS multi-tenant migration.

---

## 1. Django Directory Structure Layout

The project structure incorporates the `apps/tenants` app to act as the primary tenant-routing layer, and introduces Celery configuration directories for asynchronous exports.

```text
global_education_erp/
├── manage.py
├── requirements.txt
├── .gitignore
├── celery.py                       # Celery worker configuration
├── global_education_erp/           # Project Configuration Directory
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py                 # Common settings, apps path injects
│   │   ├── development.py          # Local settings
│   │   └── production.py           # SaaS production configurations
│   ├── urls.py                     # Main project URL router
│   ├── wsgi.py
│   └── asgi.py
├── apps/                           # Application Modules Folder
│   ├── __init__.py
│   ├── tenants/                    # Tenants App: Institution, Subscription, Host Resolution
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── middleware.py           # Subdomain resolution, context binding, suspension checks
│   │   ├── utils.py                # Thread-local tenant context accessors
│   │   ├── models.py               # Institution, Subscription, SubscriptionPlan, SubscriptionLimit
│   │   ├── views.py
│   │   └── urls.py
│   ├── core/                       # Core App: Multi-Tenant Users, Branches, Auditing
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py             # Custom User model containing role and institution FK
│   │   │   ├── branch.py           # Branches (scoped to Institution)
│   │   │   ├── audit.py            # ActivityLogs (scoped to Institution)
│   │   │   └── base.py             # TenantModel abstract base class
│   │   ├── views.py
│   │   └── urls.py
│   ├── crm/                        # CRM App: Leads, Follow-ups
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── models.py               # Lead, Followup (scoped to Institution)
│   │   ├── services.py             # AI Counseling suggestions, scoring
│   │   ├── urls.py
│   │   └── views.py
│   ├── finance/                    # Finance App: Scoped Billing & Invoicing
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── models.py               # Invoice, InvoiceItem, Receipt, Expense (scoped)
│   │   ├── services.py             # Receipt payment allocator, ageings
│   │   ├── urls.py
│   │   └── views.py
│   ├── academics/                  # Academics App: Cohorts & Attendance
│   │   ├── __init__.py
 guide   ├── admin.py
│   │   ├── models.py               # Batch, AttendanceRecord, LeaveRequest (scoped)
│   │   ├── urls.py
│   │   └── views.py
│   ├── lms/                        # LMS App: Master & Branded Courseware
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── models.py               # Program, ProgramChapter, Assignment (scoped)
│   │   ├── storage.py              # Dynamic S3 tenant prefix storage class
│   │   ├── urls.py
│   │   └── views.py
│   ├── exams/                      # Exams App: Scoped MCQ Bank & Testing
│   │   ├── __init__.py
│   │   ├── models.py               # QuestionBank, MockAttempt, FinalExam (scoped)
│   │   ├── urls.py
│   │   └── views.py
│   └── reports/                    # Reports App: Async Celery Exports & Metrics
│       ├── __init__.py
│       ├── tasks.py                # Celery tasks (anonymized tenant ZIP exporter)
│       ├── views.py
│       └── urls.py
├── static/                         # Shared CSS/JS assets
│   ├── css/
│   ├── js/
│   └── images/
└── media/                          # Tenant-partitioned media root
    └── tenants/                    # Dynamically written folder tree:
        ├── tenant_1/
        │   ├── logos/
        │   ├── student_photos/
        │   ├── signatures/
        │   └── private/
        └── tenant_2/
```

---

## 2. Setting Import Paths for `apps/`

To keep imports clean across the modular application layout, add the `apps` path to Python's system path:

In `global_education_erp/settings/base.py`:
```python
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Inject apps folder to the top of sys.path
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))
```

---

## 3. App Boundaries & Model Distribution

Every business model that contains tenant-scoped data inherits from `TenantModel` to enforce institutional isolation:

| Django App | Defined Models | Responsible Database Tables | Scope & Tenant Boundaries |
| :--- | :--- | :--- | :--- |
| **`tenants`** | `Institution`<br>`SubscriptionPlan`<br>`Subscription`<br>`SubscriptionLimit` | `saas_institutions`<br>`saas_sub_plans`<br>`saas_subscriptions`<br>`saas_sub_limits` | Global SaaS management layer. Resolution of subdomains, payment cycles, and tenant feature sets. Not isolated (shared database access). |
| **`core`** | `User`<br>`Branch`<br>`ActivityLog` | `users`<br>`branches`<br>`activity_logs` | Manages auth & users. Custom `User` inherits from `AbstractUser` and binds to an `Institution`. `Branch` and `ActivityLog` are isolated by tenant FK. |
| **`crm`** | `Lead`<br>`Followup` | `leads`<br>`followups` | Lead records and counseling timelines. Isolated by tenant FK. |
| **`finance`** | `Course`<br>`Invoice`<br>`InvoiceItem`<br>`InstallmentPlan`<br>`Receipt`<br>`BadDebtWriteoff`<br>`ExpenseCategory`<br>`Expense`<br>`ReminderLog` | `courses`<br>`invoices`<br>`invoice_items`<br>`installment_plans`<br>`receipts`<br>`bad_debt_writeoffs`<br>`expense_categories`<br>`expenses`<br>`reminder_logs` | Accounts receivable, courses definitions, and receipt ledgers. Course and financial ledger items are isolated by tenant FK. |
| **`academics`** | `Batch`<br>`StudentBatch`<br>`AttendanceRecord`<br>`AttendanceTimeWarning`<br>`AttendanceFollowup`<br>`LeaveRequest` | `batches`<br>`student_batches`<br>`attendance_records`<br>`attendance_time_warnings`<br>`attendance_followups`<br>`leave_requests` | Academic schedules, check-in records, and leave applications. Isolated by tenant FK. |
| **`lms`** | `Program`<br>`MasterChapter`<br>`ProgramChapter`<br>`MasterTopic`<br>`TopicContent`<br>`TopicAttachment`<br>`Assignment`<br>`AssignmentSubmission`<br>`StudentProgramAccess`<br>`BatchProgramAccess`<br>`MasterTopicProgress`<br>`TopicProgress`<br>`StudentTopicProgress`<br>`StudentNote` | `lms_programs`<br>`lms_master_chapters`<br>`lms_program_chapters`<br>`lms_master_topics`<br>`lms_topic_contents`<br>`lms_topic_attachments`<br>`lms_assignments`<br>`lms_assignment_submissions`<br>`lms_student_program_access`<br>`lms_batch_program_access`<br>`lms_master_topic_progress`<br>`lms_topic_progress`<br>`lms_student_topic_progress`<br>`student_notes` | Course syllabus content. LMS Programs and student files are isolated by tenant FK. Master contents are global database resources with dynamic visibility states mapping to tenants. |
| **`exams`** | `QuestionBank`<br>`ChapterMockAttempt`<br>`FinalExamApplication`<br>`FinalExamAttempt` | `lms_question_bank`<br>`lms_chapter_mock_attempts`<br>`lms_final_exam_applications`<br>`lms_final_exam_attempts` | Testing platforms and certification grades. Isolated by tenant FK. |
| **`reports`** | No database models. | None (Uses background tasks). | Handles async file imports and generates tenant-partitioned CSV datasets. |

---

## 4. Key Configuration Strategies

### A. Core Authentication Settings
In `base.py`:
```python
AUTH_USER_MODEL = 'core.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'tenants.middleware.TenantResolutionMiddleware',  # Intercepts tenant scope
]
```

### B. Tenant-Partitioned Static & Media Rules
Under local development, the media root is logically partitioned. For production cloud deployments, a custom storage backend handles file paths to ensure tenant isolation:

```python
# settings/production.py
from tenants.storage import TenantScopedS3Boto3Storage

# Public assets (e.g. dynamic branding logo)
DEFAULT_FILE_STORAGE = 'tenants.storage.TenantScopedS3Boto3Storage'

# Private attachments (LMS PDFs, Leave proof files)
PRIVATE_FILE_STORAGE = 'tenants.storage.PrivateTenantScopedS3Boto3Storage'
```
This partition ensures that when an upload triggers (e.g., `upload_to='signatures/'`), the storage engine resolves the current request's tenant context and transforms the path to:
`media/tenant_<institution_id>/signatures/filename.png`
