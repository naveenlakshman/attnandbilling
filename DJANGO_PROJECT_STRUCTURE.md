# Django Project Structure

This document outlines the detailed folder layout, module boundaries, model distribution, settings configuration, and static/media routing strategies for the migrated ERP.

---

## 1. Django Directory Structure Layout

The target Django project is structured with an `apps/` container directory to isolate business modules from the project configuration root.

```text
global_education_erp/
├── manage.py
├── requirements.txt
├── .gitignore
├── global_education_erp/           # Project Configuration Directory
│   ├── __init__.py
│   ├── settings/                   # Modular settings folder
│   │   ├── __init__.py
│   │   ├── base.py                 # Core configurations
│   │   ├── development.py          # Local/debugging parameters
│   │   └── production.py           # Production configurations
│   ├── urls.py                     # Main project URL router
│   ├── wsgi.py                     # WSGI gateway for application servers (Gunicorn)
│   └── asgi.py                     # ASGI gateway for future real-time features
├── apps/                           # Application Modules Folder
│   ├── __init__.py
│   ├── core/                       # Core App: Auth, Branches, Audit Logs
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── middleware.py           # Branch access checks, session terminations
│   │   ├── models/                 # Split models for readability
│   │   │   ├── __init__.py
│   │   │   ├── user.py             # Custom user models
│   │   │   ├── branch.py           # Branches
│   │   │   ├── profile.py          # Company profiles
│   │   │   └── audit.py            # Activity logs
│   │   ├── services/
│   │   │   └── sms_gateway.py      # SMS cloud client interface
│   │   ├── views.py
│   │   └── urls.py
│   ├── crm/                        # CRM App: Leads, Follow-ups, Counseling
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py               # Lead and Followup models
│   │   ├── services.py             # Heuristic scoring, AI counselors
│   │   ├── urls.py
│   │   └── views.py
│   ├── finance/                    # Finance App: Invoices, Receipts, Expenses
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py               # Invoice, Installment, Expense tables
│   │   ├── services.py             # Receipt allocator, fee aging calculators
│   │   ├── urls.py
│   │   └── views.py
│   ├── academics/                  # Academics App: Batches, Attendance, Leaves
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py               # Batches, Attendance, Leave requests
│   │   ├── urls.py
│   │   └── views.py
│   ├── lms/                        # LMS App: Syllabuses, Assignments
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py               # Programs, Chapters, Submissions
│   │   ├── storage.py              # Custom storage backends (S3, local private)
│   │   ├── urls.py
│   │   └── views.py
│   └── exams/                      # Exams App: MCQ Banks, Mock & Finals
│       ├── __init__.py
│       ├── admin.py
│       ├── apps.py
│       ├── models.py               # MCQ pool, application, attempts
│       ├── urls.py
│       └── views.py
├── static/                         # Unified static files directories
│   ├── css/
│   ├── js/
│   └── images/
└── media/                          # Local media uploads (fallback storage)
    ├── company_logos/
    ├── student_photos/
    ├── signatures/
    └── lms_private/
```

---

## 2. Setting Import Paths for `apps/`

To allow clean import syntax like `from core.models import User` instead of `from apps.core.models import User`, add the `apps` path to Python's system path inside the settings initialization.

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

Django enforce model relationships through clear architectural boundaries. Below is the mapping of the model schema distribution across the applications:

| Target Django App | Defined Models | Responsible Database Tables | Scope & Boundaries |
| :--- | :--- | :--- | :--- |
| **`core`** | `User`<br>`Branch`<br>`CompanyProfile`<br>`ActivityLog` | `users`<br>`branches`<br>`company_profile`<br>`activity_logs` | Manages core organization data, security controls, user profiles, and operational logs. |
| **`crm`** | `Lead`<br>`Followup` | `leads`<br>`followups` | Coordinates prospect tracking and followups. Interacts with the `core` app to assign owners (`User`) and branches (`Branch`). |
| **`finance`** | `Invoice`<br>`InvoiceItem`<br>`InstallmentPlan`<br>`Receipt`<br>`BadDebtWriteoff`<br>`ExpenseCategory`<br>`Expense`<br>`ReminderLog` | `invoices`<br>`invoice_items`<br>`installment_plans`<br>`receipts`<br>`bad_debt_writeoffs`<br>`expense_categories`<br>`expenses`<br>`reminder_logs` | Governs financial tracking. Bridges students in the `core` profile structure with actual accounts receivable. |
| **`academics`** | `Batch`<br>`StudentBatch`<br>`AttendanceRecord`<br>`AttendanceTimeWarning`<br>`AttendanceFollowup`<br>`LeaveRequest` | `batches`<br>`student_batches`<br>`attendance_records`<br>`attendance_time_warnings`<br>`attendance_followups`<br>`leave_requests` | Oversees student progress scheduling. Tracks batch timings and attendance roll calls. |
| **`lms`** | `Program`<br>`MasterChapter`<br>`ProgramChapter`<br>`MasterTopic`<br>`TopicContent`<br>`TopicAttachment`<br>`Assignment`<br>`AssignmentSubmission`<br>`StudentProgramAccess`<br>`BatchProgramAccess`<br>`MasterTopicProgress`<br>`TopicProgress`<br>`StudentTopicProgress`<br>`StudentProgramActivity`<br>`StudentNote` | `lms_programs`<br>`lms_master_chapters`<br>`lms_program_chapters`<br>`lms_master_topics`<br>`lms_topic_contents`<br>`lms_topic_attachments`<br>`lms_assignments`<br>`lms_assignment_submissions`<br>`lms_student_program_access`<br>`lms_batch_program_access`<br>`lms_master_topic_progress`<br>`lms_topic_progress`<br>`lms_student_topic_progress`<br>`student_program_last_activity`<br>`student_notes` | Houses the learning syllabus content. Controls topic visibility, progress logs, and assignment deliveries. |
| **`exams`** | `QuestionBank`<br>`ChapterMockAttempt`<br>`FinalExamApplication`<br>`FinalExamAttempt` | `lms_question_bank`<br>`lms_chapter_mock_attempts`<br>`lms_final_exam_applications`<br>`lms_final_exam_attempts` | Executes test and exam validation mechanisms. |

---

## 4. Key Configuration Strategies

### A. Authentication Engine Configuration
In `base.py`:
```python
AUTH_USER_MODEL = 'core.User'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'
```

### B. Static & Media Routing Configuration
To optimize serving speed and maintain security parameters, static and media paths are separated in settings configuration:

```python
# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media uploads (User profile pictures, student signatures)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

#### Media Serving for Protected LMS Files
To prevent unauthenticated users from scanning directories and downloading course attachments, the default storage is split:
1. **Public Storage**: Standard files (ID card photos, parent signatures) use Django's local directory `MEDIA_ROOT`.
2. **Private Storage Backend**: LMS attachments and submission items use a custom file storage handler. Under local deployment, this maps to a folder outside the static web server scope; under staging/production deployment, this hooks into secure cloud bucket storage using short-lived tokens.
