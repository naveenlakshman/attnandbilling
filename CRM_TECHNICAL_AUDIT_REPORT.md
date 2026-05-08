# Technical Audit Report

This audit is based on read-only inspection of the current codebase and the live SQLite schema in production storage. No code was modified.

## 1. Technology Stack Analysis

### Core stack
| Area | Current implementation |
|---|---|
| Backend framework | Flask 2.3, initialized in `app.py` |
| Template engine | Jinja2 via Flask templates |
| Database access | Raw sqlite3, centralized in `db.py` |
| Database engine | SQLite file at `instance/database.db`, configured in `config.py` |
| ORM | None in active use |
| Session handling | Flask signed cookie session |
| Auth hashing | Werkzeug password hashes |
| Frontend | Server-rendered HTML, Bootstrap-based UI, vanilla JavaScript |
| CSS framework | Bootstrap plus module-specific inline CSS and `static/css/style.css` |
| JS libraries | Bootstrap bundle, Flatpickr, html2pdf, PDF.js, TinyMCE, browser fetch |
| AI/API usage | Google Gemini via `modules/leads/ai_helper.py`, Google Maps Geocoding proxy in `modules/billing/routes.py` |
| Rate limiting | Flask-Limiter in `extensions.py` |
| CSRF protection | Flask-WTF CSRFProtect in `extensions.py` |

### Flask extensions used
- Flask-WTF via CSRFProtect
- Flask-Limiter
- python-dotenv for environment loading
- google-generativeai for AI follow-up assistance

### Important architecture facts
- The app is not using Flask-SQLAlchemy, even though `config.py` still contains SQLALCHEMY settings. Those settings are currently dead or legacy configuration.
- Database schema creation and migrations are handled imperatively inside `db.py`, not via Alembic or a formal migration framework.
- Rate limiting uses in-memory storage in `extensions.py`. That is acceptable for single-process development, but not reliable for multi-process or multi-instance production deployments.

### Blueprint structure
Registered in `app.py`:
- core, no prefix
- website, no prefix
- leads, `/leads`
- billing, `/billing`
- assets, `/assets`
- reports, `/reports`
- import_export, `/import-export`
- baddebt, `/baddebt`
- attendance, `/attendance`
- lms_admin, blueprint-level prefix
- students, blueprint-level routes

### Authentication system
ERP login is handled in `modules/core/routes.py`:
- Username/password lookup from `users`
- Password verification with `check_password_hash`
- Session keys set: `user_id`, `full_name`, `username`, `role`, `branch_id`, `can_view_all_branches`
- Session is marked permanent

Student portal login is separate in `modules/students/routes.py`:
- Uses `students` table, not `users`
- Requires `portal_enabled = 1`
- Rejects dropped students
- Uses separate session keys: `student_id`, `student_name`, `student_code`

### Session handling
Configured in `config.py`:
- 7-day sliding expiration
- Secure, HttpOnly, SameSite=Lax cookies
- This is production-oriented, but it means plain HTTP local sessions can behave differently unless proxied correctly

### Environment and config handling
- `.env` is loaded from the project root in `config.py`
- `SECRET_KEY` is mandatory and the app raises at startup if missing
- Config also stores Google AI, Google Maps, TinyMCE, upload limits, and upload folder settings
- There is no committed sample env file visible in the repo

### Deployment-related files
No deployment scaffolding files were found:
- No Dockerfile
- No docker-compose
- No Procfile
- No wsgi.py
- No gunicorn config
- No nginx or supervisor config
- No formal migration directory

Current deployment posture appears to be direct Flask app execution, with development run mode still present in `app.py`.

## 2. Project Structure Analysis

### Folder structure
The project is organized as a modular Flask ERP with blueprint-based feature folders and a shared raw-SQL database layer.

Important top-level folders:
- `modules`
- `templates`
- `static`
- `instance`

Important top-level Python files:
- `app.py`: Flask app factory, blueprint registration, Jinja filters
- `config.py`: environment and runtime configuration
- `db.py`: connection factory, schema initialization, activity logging, company cache
- `extensions.py`: CSRF and limiter setup

### Main app entry point
- App factory in `app.py`
- Database initialization runs during app creation via `init_db()`
- Company profile is injected into every template from `db.py`

### Module structure
Blueprint modules:
- core: ERP auth, dashboards, users, branches, company profile
- leads: CRM-like lead tracking, followups, pipeline, reports, activity
- billing: students, invoicing, receipts, admissions, conversion
- attendance: batches, attendance, followups, reports
- assets: asset inventory and allocation
- baddebt: write-off workflows
- reports: analytics, export/import support
- import_export: data import/export
- lms_admin: LMS content and access
- students: student portal
- website: public marketing site and enquiry capture

### Shared utilities and helpers
- `db.py`: `get_conn`, `log_activity`, company cache, schema bootstrap
- `modules/core/utils.py`: `login_required`, `admin_required`, `lms_content_manager_required`
- `modules/leads/ai_helper.py`: AI message/script generation

### Database helper functions
Key helpers in `db.py`:
- `get_conn`: opens sqlite3 connection with Row factory, foreign keys on, busy_timeout, `parse_date` SQL helper
- `init_db`: creates and mutates schema
- `log_activity`: generic activity logging utility
- `get_company_profile`: cached global company config
- `add_column_if_not_exists`: schema drift handling

### Template inheritance structure
Shared layout templates:
- `templates/base.html`: main ERP shell
- `templates/login_base.html`: login wrapper
- `templates/print_base.html`
- `templates/website/base.html`: public site shell
- `templates/leads/base.html`: dedicated leads shell
- Additional module bases exist for billing, attendance, baddebt, lms_admin, students

Important observation:
- Leads does not inherit the main ERP shell. It has a separate navigation shell in `templates/leads/base.html`. That gives module isolation, but increases design duplication.

### Static file organization
- CSS: Bootstrap, Flatpickr CSS, custom stylesheet
- JS: Bootstrap bundle, Flatpickr, html2pdf, PDF.js assets
- Images: company logo, student photos, signatures
- LMS file content is stored outside static under instance uploads

### Route organization
- Feature logic is concentrated inside each module’s `routes.py`
- This is simple to navigate initially, but several route files are now monoliths

Largest route files:
- `modules/billing/routes.py`: 4046 lines
- `modules/lms_admin/routes.py`: 3980 lines
- `modules/attendance/routes.py`: 2641 lines
- `modules/leads/routes.py`: 1543 lines
- `modules/reports/routes.py`: 1454 lines

## 3. Database Analysis

### Live database overview
The production SQLite file currently contains 37 tables.

High-volume tables:
- `activity_logs`: 4497 rows
- `attendance_records`: 2106 rows
- `receipts`: 754 rows
- `invoice_items`: 393 rows
- `invoices`: 383 rows
- `students`: 383 rows
- `leads`: 132 rows
- `followups`: 147 rows
- `users`: 6 rows

### A. List of all tables

### Core, users, CRM
| Table | Purpose | Important columns | PK | FKs |
|---|---|---|---|---|
| `company_profile` | Global branding and contact info | `company_name`, `company_short_name`, `logo_filename`, `reg_number` | `id` | None |
| `branches` | Branch master | `branch_name`, `branch_code`, `is_active`, `opening_time`, `closing_time` | `id` | None |
| `users` | ERP staff/admin users | `full_name`, `username`, `password_hash`, `role`, `branch_id`, `can_view_all_branches`, `is_active` | `id` | `branch_id -> branches.id` |
| `activity_logs` | Cross-module audit trail | `user_id`, `branch_id`, `action_type`, `module_name`, `record_id`, `description`, `created_at` | `id` | `user_id -> users.id`, `branch_id -> branches.id` |
| `leads` | Lead master table | `name`, `phone`, `email`, `lead_source`, `stage`, `status`, `lead_score`, `assigned_to_id`, `next_followup_date`, `is_deleted` | `id` | `assigned_to_id -> users.id` |
| `followups` | Lead follow-up history | `lead_id`, `user_id`, `method`, `outcome`, `note`, `next_followup_date`, `created_at` | `id` | `lead_id -> leads.id`, `user_id -> users.id` |
| `students` | Student master and portal login | `student_code`, `full_name`, `phone`, `branch_id`, `password_hash`, `portal_enabled`, `lead_id`, `joined_date` | `id` | `branch_id -> branches.id` |

### Academic operations and attendance
| Table | Purpose | Important columns | PK | FKs |
|---|---|---|---|---|
| `courses` | Course catalog | `course_name`, `fee`, `course_type`, `course_domain`, `show_on_website` | `id` | None |
| `batches` | Teaching batches | `batch_name`, `course_id`, `branch_id`, `trainer_id`, `status` | `id` | `course_id -> courses.id`, `branch_id -> branches.id`, `trainer_id -> users.id` |
| `student_batches` | Student enrollment to batches | `student_id`, `batch_id`, `joined_on`, `status`, `uses_own_laptop` | `id` | `student_id -> students.id`, `batch_id -> batches.id` |
| `attendance_records` | Daily attendance | `attendance_date`, `student_id`, `batch_id`, `branch_id`, `status`, `marked_by` | `id` | `student_id -> students.id`, `batch_id -> batches.id`, `branch_id -> branches.id`, `marked_by -> users.id` |
| `attendance_time_warnings` | Off-time attendance audit | `batch_id`, `student_id`, `attendance_date`, `warning_type`, `actual_time`, `marked_by` | `id` | `batch_id -> batches.id`, `branch_id -> branches.id`, `student_id -> students.id`, `marked_by -> users.id` |
| `attendance_followups` | Attendance-related counseling/follow-up | `student_id`, `branch_id`, `batch_id`, `followup_date`, `followup_status`, `created_by` | `id` | `student_id -> students.id`, `branch_id -> branches.id`, `batch_id -> batches.id`, `created_by -> users.id` |

### Finance
| Table | Purpose | Important columns | PK | FKs |
|---|---|---|---|---|
| `invoices` | Student billing headers | `invoice_no`, `student_id`, `invoice_date`, `total_amount`, `status`, `created_by`, `branch_id` | `id` | `student_id -> students.id`, `created_by -> users.id`, `branch_id -> branches.id` |
| `invoice_items` | Invoice line items | `invoice_id`, `course_id`, `description`, `quantity`, `unit_price`, `discount`, `line_total` | `id` | `invoice_id -> invoices.id`, `course_id -> courses.id` |
| `installment_plans` | Installment schedules | `invoice_id`, `installment_no`, `due_date`, `amount_due`, `amount_paid`, `status` | `id` | `invoice_id -> invoices.id` |
| `receipts` | Payment receipts | `receipt_no`, `invoice_id`, `receipt_date`, `amount_received`, `payment_mode`, `created_by` | `id` | `invoice_id -> invoices.id`, `created_by -> users.id` |
| `bad_debt_writeoffs` | Write-off records | `invoice_id`, `amount_written_off`, `authorized_by`, `writeoff_date`, `reason` | `id` | `invoice_id -> invoices.id`, `authorized_by -> users.id` |
| `expense_categories` | Expense master | `category_name`, `is_active` | `id` | None |
| `expenses` | Expense transactions | `expense_date`, `branch_id`, `category_id`, `amount`, `payment_mode`, `created_by` | `id` | `branch_id -> branches.id`, `category_id -> expense_categories.id`, `created_by -> users.id` |
| `reminder_logs` | Payment reminder history | `student_id`, `invoice_id`, `installment_id`, `reminder_type`, `status`, `sent_via`, `sent_by` | `id` | `student_id -> students.id`, `invoice_id -> invoices.id`, `installment_id -> installment_plans.id`, `sent_by -> users.id` |

### Assets
| Table | Purpose | Important columns | PK | FKs |
|---|---|---|---|---|
| `assets` | Asset master | `asset_code`, `asset_name`, `category`, `condition`, `status`, `branch_id` | `id` | `branch_id -> branches.id` |
| `asset_allocation` | Asset assignment | `asset_id`, `assigned_to`, `assigned_role`, `assigned_date`, `status` | `id` | `asset_id -> assets.id` |
| `asset_logs` | Asset audit log | `asset_id`, `action`, `description`, `done_by`, `created_at` | `id` | `asset_id -> assets.id`, `done_by -> users.id` |

### LMS
| Table | Purpose | Important columns | PK | FKs |
|---|---|---|---|---|
| `lms_programs` | LMS programs | `course_id`, `program_name`, `slug`, `is_published`, `created_by` | `id` | `course_id -> courses.id`, `created_by -> users.id` |
| `lms_chapters` | Program chapters | `program_id`, `chapter_title`, `chapter_order`, `is_active` | `id` | `program_id -> lms_programs.id` |
| `lms_topics` | Chapter topics | `chapter_id`, `topic_title`, `topic_order`, `content_type`, `is_preview`, `is_required` | `id` | `chapter_id -> lms_chapters.id` |
| `lms_topic_contents` | Topic content blocks | `topic_id`, `content_mode`, `content_title`, `external_url`, `file_path`, `hotspots_json` | `id` | `topic_id -> lms_topics.id` |
| `lms_topic_attachments` | Topic attachments | `topic_id`, `file_name`, `file_path`, `uploaded_by`, `is_required` | `id` | `topic_id -> lms_topics.id`, `uploaded_by -> users.id` |
| `lms_program_resources` | Program resources | `program_id`, `resource_title`, `resource_type`, `file_path` | `id` | `program_id -> lms_programs.id` |
| `lms_mock_tests` | Tests and assessments | `program_id`, `chapter_id`, `topic_id`, `test_title`, `total_marks` | `id` | `program_id -> lms_programs.id`, `chapter_id -> lms_chapters.id`, `topic_id -> lms_topics.id` |
| `lms_student_program_access` | Student direct LMS access | `student_id`, `program_id`, `batch_id`, `access_status` | `id` | `student_id -> students.id`, `program_id -> lms_programs.id`, `batch_id -> batches.id` |
| `lms_batch_program_access` | Batch-level LMS access | `batch_id`, `program_id`, `access_start_date`, `access_end_date` | `id` | `batch_id -> batches.id`, `program_id -> lms_programs.id` |
| `lms_course_program_map` | Billing course to LMS map | `course_id`, `program_id`, `display_order`, `created_by` | `id` | `course_id -> courses.id`, `program_id -> lms_programs.id` |
| `lms_student_topic_progress` | Topic progress percentages | `student_id`, `topic_id`, `completion_percentage`, `time_spent_minutes` | `id` | `student_id -> students.id`, `topic_id -> lms_topics.id` |
| `lms_topic_progress` | Simpler completion tracker | `student_id`, `topic_id`, `is_completed`, `completed_at` | `id` | None declared |
| `lms_student_test_results` | Student test results | `student_id`, `test_id`, `score`, `obtained_percentage`, `test_date` | `id` | `student_id -> students.id`, `test_id -> lms_mock_tests.id` |

### B. Relationship analysis

### Core relationships
- Users optionally belong to a branch.
- Users own leads through `leads.assigned_to_id`.
- Activity logs reference users and branches, but `record_id` is polymorphic textless linkage, not a true foreign key.

### Lead-related relationships
- `leads -> followups` is a real parent-child relationship with cascade delete on followups.
- `leads -> users` is ownership only.
- Leads do not carry `branch_id`. That means lead ownership is user-based, not branch-based.

### Student conversion relationship
- `students.lead_id` is the intended conversion link.
- That link is not enforced by a foreign key in the live schema.
- Conversion is driven from billing admission flow in `modules/billing/routes.py`, not from the leads blueprint itself.
- If a student is created from a lead, billing updates the lead to stage `Converted` and status `converted`.
- If a student is created directly, billing auto-creates a synthetic converted lead and backfills `students.lead_id`.

### User relationship structure
- Admin/staff are both stored in `users.role`.
- `can_view_all_branches` augments branch access, especially in attendance and reporting.
- Leads use role to decide list/dashboard visibility, but not to secure individual record actions consistently.

### C. Leads Module database analysis

Lead-related tables and fields:
- `leads`: main lead record
- `followups`: follow-up timeline
- `activity_logs` with `module_name = 'leads'`: lead action audit stream
- `students.lead_id`: downstream conversion link

Current ownership structure:
- `assigned_to_id` points to `users.id`
- New leads created inside ERP default to current session user
- Website enquiries create leads without an assigned owner in `modules/website/routes.py`

Current conversion tracking:
- `stage` and `status` are both used
- Converted status is stored directly on leads
- Student creation in billing mutates the lead
- There is no dedicated `conversion_events` or `admissions_pipeline` table
- There is no enforced FK from `students.lead_id` back to `leads.id`

Current scoring logic:
Defined in `modules/leads/routes.py`:
- `lead_source` contributes up to 25
- `start_timeframe` contributes up to 25
- `education_status` contributes up to 20
- `career_goal` contributes up to 20
- Max score capped at 100

Current stage logic:
Defined in `modules/leads/routes.py`:
- `New Lead -> Contacted`
- `Contacted -> Interested`
- `Interested -> Counseling Done`
- `Counseling Done -> Follow-up`
- `Follow-up -> Converted or Lost`
- Converted and Lost are terminal

Important limitation:
- Stage is a single mutable field, not a history table
- Follow-up outcomes do not automatically drive full stage progression
- Only `followup_add` auto-advances `New Lead` to `Contacted`

### D. Database risks

#### Missing indexes
There are almost no manual performance indexes. Most indexes are only autoindexes created by unique constraints.

High-risk missing indexes:
- `leads` on `assigned_to_id`
- `leads` on `status`
- `leads` on `stage`
- `leads` on `next_followup_date`
- `leads` on `is_deleted`
- `leads` on `created_at`
- `followups` on `lead_id` and `created_at`
- `activity_logs` on `module_name`, `user_id`, `created_at`
- `invoices` on `student_id`, `branch_id`, `invoice_date`
- `receipts` on `invoice_id`, `receipt_date`
- `attendance_records` on `branch_id` and `attendance_date` beyond the current unique composite

#### Weak normalization
- `lead_source`, `stage`, `status`, `education_status`, `career_goal`, `decision_maker` are all free text enums
- No reference/master tables for CRM dimensions
- `interested_courses` is stored as text, not a many-to-many relation

#### Missing constraints
- `students.lead_id` has no foreign key
- `activity_logs.record_id` has no FK and no typed integrity
- No unique constraint on lead phone or email
- No `branch_id` on leads, which weakens branch-aware reporting and permissions

#### Date consistency issues
- DB stores most dates as TEXT
- Some code assumes `YYYY-MM-DD`
- Some import/report paths accept `DD-MM-YYYY` and `DD/MM/YYYY` in `modules/reports/routes.py`
- `created_at` and `updated_at` are ISO datetime text, while operational fields are date strings
- Queries mix `substr`, `strftime`, direct comparison, and `parse_date` SQL helper

#### Scaling concerns
- SQLite is acceptable for current size, especially with WAL and busy_timeout from `db.py`
- It will degrade under dashboard/report growth because many queries do full scans over text dates and unindexed status fields
- Schema mutation on app startup is risky for production change control

## 4. Authentication & Permission System

### Login system
ERP auth:
- Login route in `modules/core/routes.py`
- Logout route clears the entire session in `modules/core/routes.py`

Student auth:
- Separate login/logout in `modules/students/routes.py`
- Student portal uses a different table and session namespace

### Route protection decorators
Defined in `modules/core/utils.py`:
- `login_required`
- `admin_required`
- `lms_content_manager_required`

### Role system
Current ERP roles:
- `admin`
- `staff`

Branch visibility:
- `can_view_all_branches` is a second permission dimension
- Attendance and some reports use this heavily
- Leads does not, because leads has no branch field

### How admin differs from staff
Admin:
- Sees global ERP dashboard
- Can manage users, branches, company profile
- Can access admin-only modules like bad debt, import/export, some billing/report routes
- Sees all leads in list/dashboard/report contexts

Staff:
- Gets dedicated staff dashboard in `modules/core/routes.py`
- Usually sees only assigned leads
- Usually sees branch-restricted data unless `can_view_all_branches = 1`

### Current authorization structure
Strengths:
- Decorator pattern exists and is used broadly
- Session role and branch context are explicit
- Student portal is isolated from ERP login

Weaknesses:
- Authorization is inconsistent between list access and record mutation
- Some admin checks are decorators
- Some admin checks are inline route-body conditionals
- Some ownership checks are missing entirely

### Security concerns

#### 1. Major leads authorization gap
The leads list is filtered by owner for staff, but the actual record routes do not enforce owner/admin authorization consistently.

Examples:
- lead detail lookup in `modules/leads/routes.py`
- followup add in `modules/leads/routes.py`
- lead edit in `modules/leads/routes.py`
- stage change in `modules/leads/routes.py`
- reassignment in `modules/leads/routes.py`
- delete in `modules/leads/routes.py`
- restore in `modules/leads/routes.py`
- mark lost in `modules/leads/routes.py`
- AI assist in `modules/leads/routes.py`

Impact:
- A staff user who knows or guesses a lead ID can potentially view or mutate another counselor’s lead.

#### 2. Student login is not rate-limited
- ERP login is limited in `modules/core/routes.py`
- Student login has no similar rate limit in `modules/students/routes.py`

#### 3. Rate limiter backend is not production-safe
- `storage_uri` is `memory://` in `extensions.py`
- In multi-worker production, limits will not be shared

#### 4. Public content serving route
- `app.py` exposes uploaded content without auth
- It also appears to rely on `os` and `send_from_directory` without visible imports in the file
- This is both an operational bug risk and a content exposure risk, depending on file sensitivity

#### 5. Password/security maturity
- No visible MFA
- No password complexity policy
- No account lockout beyond limiter
- No audit trail for login failures

## 5. Leads Module Analysis

### Lead-related routes
From `modules/leads/routes.py`:

- `/leads/` : dashboard
- `/leads/new` : create lead
- `/leads/<lead_id>` : detail view
- `/leads/list` : searchable lead list
- `/leads/<lead_id>/followups/new` : add follow-up
- `/leads/<lead_id>/edit` : edit lead
- `/leads/<lead_id>/stage` : set stage
- `/leads/<lead_id>/reassign` : change owner
- `/leads/followups` : due follow-ups view
- `/leads/pipeline` : stage board
- `/leads/reports` : admin reporting
- `/leads/activity-log` : lead activity audit
- `/leads/<lead_id>/delete` : soft delete
- `/leads/deleted` : deleted leads listing
- `/leads/<lead_id>/restore` : restore soft-deleted lead
- `/leads/<lead_id>/mark-lost` : mark lost with reason
- `/leads/<lead_id>/ai-assist` : AI helper endpoint

### Lead creation flow
In `modules/leads/routes.py`:
- Reads form fields directly from `request.form`
- Computes score via `compute_lead_score`
- Defaults `assigned_to_id` to current session user
- Maps stage to status
- Inserts into `leads`
- Logs activity via `log_activity`

### Lead edit flow
In `modules/leads/routes.py`:
- Repeats much of create logic
- Recomputes score from current profile fields
- Rewrites `stage`, `status`, dates, notes
- No separate service/helper for transition logic

### Follow-up flow
In `modules/leads/routes.py`:
- Inserts a `followup` row
- Updates `lead.last_contact_date`
- Increments `lead.followup_count`
- Updates `next_followup_date`
- Auto-promotes stage only from `New Lead` to `Contacted`
- Logs the action

### Conversion flow
The leads module does not perform actual student conversion itself.
- Lead detail view links to billing admission using `from_lead` in `templates/leads/lead_detail.html`
- Actual conversion is handled in `modules/billing/routes.py`

This is a major architectural boundary:
- Leads owns prospect tracking
- Billing owns student creation and conversion side effects

### Pipeline logic
Current pipeline is simple and static:
- One field for stage
- One helper for next allowed stages
- One board page grouped by stage
- No drag-and-drop persistence
- No SLA, no stage timestamps, no stage history, no automation rules

### Reporting logic
Admin-only reports in `modules/leads/routes.py`:
- Total, active, converted, lost
- Conversion rate
- Source performance
- Course interest performance
- User performance leaderboard
- Date and user filters

### How lead stages currently work
- Stage is a text label
- Status is a parallel text state, usually `active`, `converted`, or `lost`
- Converted and Lost are both stage values and status values
- This duplication can drift if not updated together

### How scores currently work
- Static profile-based heuristic only
- No weighting from follow-up behavior
- No weighting from recency, response quality, meeting attendance, or source ROI
- Website leads are inserted without score calculation in `modules/website/routes.py`

### How follow-ups currently work
- Follow-up history is real and useful
- `next_followup_date` is stored on both the followup row and denormalized onto the lead
- There is no reminder scheduler in leads
- No automated escalation
- No disposition-to-stage rules except the initial `New Lead -> Contacted` bump

### How conversion to student works
- Lead detail offers a Convert to Student action
- Billing student creation accepts `from_lead`
- Billing updates the lead to Converted
- Billing also creates a lead automatically for direct admissions without a pre-existing lead

### Leads templates
Templates under `templates/leads`:
- `base.html`
- `dashboard.html`
- `lead_form.html`
- `lead_detail.html`
- `leads_list.html`
- `followups.html`
- `pipeline.html`
- `reports.html`
- `activity_log.html`
- `deleted_leads.html`

### Leads helper functions
In `modules/leads/routes.py`:
- `get_next_stages`
- `parse_date`
- `compute_lead_score`

In `modules/leads/ai_helper.py`:
- `generate_followup_script`
- `suggest_next_action`
- `draft_message_template`

### Leads SQL query profile
The leads module mostly queries by:
- `is_deleted`
- `status`
- `stage`
- `assigned_to_id`
- `next_followup_date`
- `created_at` and `updated_at`
- free-text `LIKE` on `name`/`phone`/`whatsapp`

Those are exactly the fields that currently lack supporting indexes.

## 6. UI/UX Architecture Analysis

### Bootstrap structure
- Bootstrap is the UI foundation across ERP, website, and student portal
- Module pages are server-rendered and heavily styled inline per-template

### Reusable UI patterns already present
- KPI cards on dashboards
- Card-based mobile list views and table-based desktop views
- Filter bars with auto-submit behavior
- Module-specific sidebars/topbars
- Flash message blocks
- Mobile bottom nav in ERP and leads shells
- Stage badges and status pills
- Quick action bars on detail pages

Examples:
- Main ERP shell in `templates/base.html`
- Leads shell in `templates/leads/base.html`
- Website shell in `templates/website/base.html`

### Card system
The design language is card-heavy:
- dashboard KPI cards
- section cards
- lead cards
- follow-up cards
- info cards
- form cards

This is good for CRM evolution because cards map well to:
- lead summaries
- counselor task lists
- activity timelines
- pipeline columns

### Tables and lists
- Desktop uses tables for reporting-heavy pages
- Mobile often swaps to cards
- Sorting has been implemented in some lists with explicit `data-sort-key` patterns
- This dual-mode pattern is reusable

### Navigation structure
- ERP has a general shell
- Leads has a separate dedicated shell
- Website has a public marketing shell
- Student portal has its own login and student base

Current result:
- Good contextual navigation
- Weak consistency across modules

### Form patterns
Current form patterns are straightforward:
- server-rendered
- POST submit
- mostly direct `request.form` handling
- inline validation messages
- CSRF token injection duplicated across multiple base templates

### Dashboard layouts
Strong:
- Data density is reasonable
- Cards and summary panels are useful
- Mobile behavior is explicitly considered

Weak:
- Layout logic is duplicated across modules
- Large volumes of inline CSS reduce consistency and reuse

### Inconsistent design patterns
- Each module defines its own inline CSS blocks
- Leads uses emoji-heavy navigation and badges, while core ERP is more neutral
- CSRF hidden-field injection script is duplicated in multiple base templates
- Flash message rendering is repeated
- Some pages use very large inline scripts instead of shared JS modules

### Best candidates for reusable components/macros
- Flash alerts
- CSRF form helper
- KPI card
- filter toolbar
- stage badge
- lead summary card
- activity timeline item
- mobile bottom nav
- user filter dropdown
- empty-state panels

## 7. Performance & Maintainability Review

### Files becoming too large
Route files:
- `modules/billing/routes.py`: 4046 lines
- `modules/lms_admin/routes.py`: 3980 lines
- `modules/attendance/routes.py`: 2641 lines
- `modules/leads/routes.py`: 1543 lines
- `modules/reports/routes.py`: 1454 lines

Large templates:
- `templates/billing/student_profile.html`: 2115 lines
- `templates/billing/invoice_form_modern.html`: 1140 lines
- `templates/billing/student_form.html`: 1107 lines
- `templates/attendance/mark_attendance.html`: 963 lines

### Duplicate logic
Repeated logic currently appears in:
- lead stage/status mapping across create, edit, set_stage, mark_lost, billing conversion
- lead score recomputation across create and edit only
- admin/staff filtering across many leads views
- branch permission checks repeated many times in attendance
- company/CSRF/flash base-template boilerplate
- date parsing across db helper, reports helper, and route-level assumptions

### Poor separation of concerns
- Raw SQL, request parsing, authorization checks, business logic, and response rendering are all mixed inside route functions
- Billing owns conversion logic that CRM depends on
- Leads owns score/stage logic inside a route file rather than a dedicated service

### N+1 and repeated-query patterns
Concrete hotspots:
- Leads dashboard team stats loops through staff and runs multiple queries per user in `modules/leads/routes.py`
- Leads reports builds user stats by looping all users and issuing several queries per user in `modules/leads/routes.py`
- Pipeline does one query per stage in `modules/leads/routes.py`
- Dashboards often issue many separate COUNT queries over the same tables

### SQLite-specific concerns
- Heavy use of `substr` and `strftime` on text columns prevents efficient indexing
- No formal migration system means production schema drift is handled at startup
- WAL mode and busy timeout are good and deliberate in `db.py`
- Current scale is still manageable, but CRM growth will push against these limits quickly

### Logic that should later move into helpers/services
- Lead access policy service
- Lead stage transition service
- Lead scoring service
- Lead conversion service
- Leads reporting query service
- Common date parsing/formatting service
- Shared filter/query builder utilities
- Activity logging wrapper for consistent action types

## 8. CRM Transformation Readiness

### A. What is already strong
- Blueprint modularity is already in place
- There is a real leads table and followups table
- Ownership via `assigned_to_id` already exists
- Soft delete is already implemented for leads
- Activity logging already exists
- Public website enquiry already feeds the leads table
- Pipeline view already exists
- Reporting exists, even if basic
- Student conversion linkage exists conceptually through `students.lead_id`
- The app already supports counselor-like workflow, even if not fully enforced

### B. What needs redesign
- Lead authorization is the first structural problem
- Lead-to-student conversion should be a first-class service, not a side effect inside billing
- Lead branching and reporting model is incomplete because leads has no `branch_id`
- Stage and status duplication needs central control
- Lead scoring is too static for a conversion-focused CRM
- Activity trail is split between followups and generic `activity_logs` without a unified CRM timeline abstraction
- No automation framework exists for reminders, stale lead escalation, or SLA tracking

### C. Safest improvement strategy
- Harden authorization first
- Centralize lead transition and conversion rules second
- Add indexes and missing constraints before UI expansion
- Keep existing routes working while extracting helpers beneath them
- Migrate to richer CRM behaviors incrementally, not through a rewrite

### D. Which parts should not be rewritten immediately
- ERP login/session foundation
- Core branch/user management
- Billing student creation flow
- Existing `activity_logs` mechanism
- Existing raw sqlite connection layer
- Existing dashboard templates unless the business flow changes first

### E. Existing structures that can be reused

#### Activity timeline
Reusable sources:
- `followups`
- `activity_logs`

#### Lead scoring
Reusable base:
- `compute_lead_score` in `modules/leads/routes.py`

#### Counselor tracking
Reusable fields:
- `leads.assigned_to_id`
- `users.role`
- `users.can_view_all_branches`

#### Follow-up automation
Reusable fields and patterns:
- `leads.next_followup_date`
- `followups.created_at`
- `reminder_logs` pattern from billing

#### Kanban pipeline
Reusable pieces:
- `leads.stage`
- `get_next_stages`
- existing pipeline page in `templates/leads/pipeline.html`

#### Reporting
Reusable pieces:
- leads reports route
- ERP dashboards
- source and course aggregation patterns

## 9. Safe Migration Plan

### Safest order of implementation
1. Authorization hardening
2. Database hardening
3. Service-layer extraction
4. CRM data model enrichment
5. UI modularization
6. Automation and advanced reporting

### Database changes that should happen first
- Add indexes on leads, followups, and activity_logs filter fields
- Add a proper foreign key or validated linkage strategy for `students.lead_id`
- Decide whether leads needs `branch_id`
- Add explicit conversion timestamp if CRM reporting will depend on conversion cohorts
- Add stage change timestamps or a `lead_stage_history` table if pipeline analytics is needed

### UI changes that should happen first
- Do not start with a visual rewrite
- First normalize reusable lead UI components:
  - stage badge
  - KPI card
  - lead list row/card
  - filter toolbar
  - activity item
- Preserve existing page routes and workflows while improving composition underneath

### Files that are risky to edit
Highest-risk route files:
- `modules/billing/routes.py`
- `modules/attendance/routes.py`
- `modules/lms_admin/routes.py`
- `modules/leads/routes.py`

Highest-risk templates:
- `templates/billing/student_form.html`
- `templates/billing/student_profile.html`
- `templates/attendance/mark_attendance.html`

Reason:
- These files already combine too many responsibilities and regression blast radius is high.

### Features that should be isolated into helper functions first
- Lead ownership/authorization checks
- Lead score calculation
- Lead stage/status transitions
- Lead conversion transaction
- Follow-up save + lead denormalized field updates
- Lead reporting filters
- Common date normalization

## 10. Output Summary

### Overall assessment
This is not a greenfield rewrite problem. It is an incremental-hardening problem.

The current project already has enough CRM primitives to become a counseling CRM:
- lead records
- follow-up history
- assignment
- pipeline
- activity logging
- conversion link to students
- website capture

The main blockers are not missing screens. They are:
- inconsistent authorization
- duplicated business logic
- weak schema constraints
- oversized route files
- raw-SQL logic spread across presentation routes

### Recommended next first step
Extract and enforce a single lead access and transition layer before adding any new CRM features. In practical terms, the first implementation step should be: lock down lead ownership/admin authorization on all lead detail and mutation routes, then centralize stage/status/conversion logic behind helper functions.

### Risk level of current project
High

### Technical debt level
High

### Readiness score for CRM transformation
6/10

### Natural next steps
1. Convert this audit into a prioritized remediation backlog with severity, owner, and effort.
2. Produce a lead-module-only hardening plan focused on authorization, indexes, and service extraction.
3. Design the target counseling CRM schema delta on top of the current tables, without rewriting billing.