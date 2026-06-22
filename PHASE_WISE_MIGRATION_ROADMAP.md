# Phase-Wise Migration Roadmap

This document outlines the step-by-step roadmap for migrating the ERP system from Flask + SQLite to Django + MySQL across 10 distinct, logically ordered phases.

---

## Roadmap Overview

```text
Phase 1: Planning ──────────► Phase 2: Foundation ────────► Phase 3: Core System
                                                                   │
Phase 6: Attendance ◄───────── Phase 5: Billing ◄───────── Phase 4: CRM
       │
Phase 7: LMS ───────────────► Phase 8: Exams ─────────────► Phase 9: Reports ──► Phase 10: Cutover
```

---

## Detailed Phase Breakdown

### Phase 1: Planning & Design
* **Goals**: Establish architectural guidelines, secure team alignment, design data mapping specifications, and set development standards.
* **Deliverables**: Finalized architecture blueprints, SQL-to-MySQL mapping documents, security hardening specifications, and task boards.
* **Dependencies**: None.
* **Risks**: Missed constraints in data schemas leading to late-stage database restructuring.
* **Exit Criteria**: All planning documentation is approved, the repository structure is initialized, and the team is assigned roles.

### Phase 2: Foundation Setup
* **Goals**: Build the target database environment, initialize the Django codebase, and write database model mappings.
* **Deliverables**: MySQL database instances (local and staging), active Django project directory, settings configurations, and initial database migrations.
* **Dependencies**: Phase 1.
* **Risks**: Mismatches in database schema conversion leading to failing migrations.
* **Exit Criteria**: `makemigrations` and `migrate` commands run successfully against MySQL without warnings or errors.

### Phase 3: Core System Migration
* **Goals**: Migrate user models, branch structures, activity log tables, custom authentication backends, and company profiles.
* **Deliverables**: Custom User models, branch CRUD views, session middlewares, SMS gateway wrappers, and Django admin mappings.
* **Dependencies**: Phase 2.
* **Risks**: Session state leakage between student and staff login views.
* **Exit Criteria**: Core authentication works, staff can CRUD branches in Django Admin, and SMS alert APIs test successfully.

### Phase 4: CRM (Leads) Migration
* **Goals**: Migrate leads pipelines, followup timelines, lead scoring heuristics, and Gemini AI counseling integrations.
* **Deliverables**: Leads dashboard, pipeline views, followup logs, and AI counseling scripts endpoints.
* **Dependencies**: Phase 3.
* **Risks**: Loss of historical lead followups during transition, or IDOR exposure in lead mutation routes.
* **Exit Criteria**: CRM dashboards show correct counts, lead scores calculate correctly on leads saving, and counselor authorization checks pass.

### Phase 5: Billing & Finance Migration
* **Goals**: Migrate billing structures (courses, invoices, installments, receipts, expenses, write-offs).
* **Deliverables**: Course registry admin, student enrollment and fee allocation panels, printable invoices, receipt logs, and public invoice token download pages.
* **Dependencies**: Phase 4 (students are generated from converted leads).
* **Risks**: Floating-point rounding errors in transactions, and incorrect payment distribution algorithms across installments.
* **Exit Criteria**: Enrolling a student generates correct installment plans, receipts automatically update invoice totals, and financial aggregate validations match SQLite source.

### Phase 6: Academics & Attendance Migration
* **Goals**: Migrate batches schedules, trainer assignments, daily roll call marking, student leave requests, and defaulters followups.
* **Deliverables**: Batch planner panels, mark attendance grids, leave forms (with file uploading), and defaulters lists.
* **Dependencies**: Phase 5 (requires course codes and billing student ids).
* **Risks**: Database lock contention when multiple trainers mark attendance concurrently, and database-level unique constraint violations.
* **Exit Criteria**: Active batches can schedule classes, double-marking attendance is prevented by database unique indices, and consecutive absent lists update in real-time.

### Phase 7: LMS Migration
* **Goals**: Migrate syllabus structures, chapter mappings, topic content screens (slides, HTML content, hotspots), and assignments submissions.
* **Deliverables**: Master course catalog editor, slide viewers, assignment upload endpoints, and submission grading interfaces.
* **Dependencies**: Phase 6 (student-batch assignments dictate program access).
* **Risks**: Unauthenticated access to courseware files, and file size limits blocking student homework uploads.
* **Exit Criteria**: Syllabus access list checks enforce enrollment rules, private media storage serves files through authenticated views, and progress tracking tables capture completions.

### Phase 8: Exams Module Migration
* **Goals**: Migrate MCQ question pools, mock quiz sheets, final exam application approvals, and interactive testing screens.
* **Deliverables**: Question bank CRUD panels, mock quiz taking pages, final exam request tables, and grading screens.
* **Dependencies**: Phase 7 (requires topic completion status for final exams).
* **Risks**: Cheating vectors in online final exam taking, and quiz generator query lag under high concurrent user load.
* **Exit Criteria**: Mocks randomly query MCQs from correct chapters, final exams block unapproved applications, and grade attempts calculate and write to database correctly.

### Phase 9: Reports & Backup Utilities
* **Goals**: Migrate management dashboards, daily transaction sheets, counselor dashboards, and backup utilities.
* **Deliverables**: Financial metrics views, CSV import-export pipelines, and database backup routines.
* **Dependencies**: Phases 3 to 8.
* **Risks**: Reporting query performance degrades due to full-table scans.
* **Exit Criteria**: All CSV import-export test files execute and write without data corruption, and reports complete queries within a 3-second threshold.

### Phase 10: Production Cutover
* **Goals**: Complete data migration, execute staging tests, perform dry runs, deploy to production servers, and open traffic.
* **Deliverables**: Live production database, live DNS mapping, rollback scripts, and operational training guidelines.
* **Dependencies**: Phase 9.
* **Risks**: Data loss due to post-migration activity or server failure.
* **Exit Criteria**: ETL validation checks verify matching row counts and sums, the staging verification suite passes, DNS is switched, and the system is verified live by core administrators.
