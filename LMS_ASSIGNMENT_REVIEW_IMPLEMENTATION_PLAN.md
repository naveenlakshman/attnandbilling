# LMS Assignment Review Implementation Plan

This document tracks the assignment-review redesign. Work will be completed one phase at a time. A phase is complete only after its implementation, automated tests, local Docker/MySQL verification, and acceptance criteria all pass.

## Delivery order

- Release 1: Phases 0–5 — baseline tests, responsive layout, authorization, correct counts, clickable indicators, and pagination.
- Release 2: Phases 6–8 — centralized queue, integrated review, reviewer identity, and attempt history.
- Release 3: Phases 9–10 — scores, rubrics, due dates, completion rules, and controlled production deployment.

## Phase 0 — Baseline and regression coverage

Status: Completed locally on 2026-07-21

### Tasks

- [x] Add reusable MySQL fixtures for an administrator, two trainers, two batches, and students with initial and resubmitted attempts.
- [x] Test student upload, pending review, acceptance, rejection, resubmission, topic completion, and assignment deletion.
- [x] Record current query behavior with approximately 400 assignments and 1,100 submissions.
- [x] Ensure test records are transactional or safely removed.

### Acceptance criteria

- [x] The current workflow is reproducible in local Docker.
- [x] Tests expose the existing authorization and count inconsistencies.
- [x] Test execution does not leave unwanted records or files.

### Phase 0 evidence

- Test: `scratch/test_assignment_phase0_mysql.py`
- Environment: local Docker web container and MySQL 8 container.
- External GCS writes are mocked; Flask routes and MySQL operations are real.
- Passed flows: upload, duplicate-pending prevention, reject, resubmit, accept, topic completion, assignment deletion, trainer list scoping, and token-based cleanup.
- Measured during fixtures: 390 assignments, 1,061 submission attempts, 203.8 ms response time, and 1,210,461 response bytes for the unpaginated administrator assignment dashboard.
- The temporary test contribution was two active assignments and three attempts at measurement time; the underlying local dataset was therefore 388 assignments and 1,058 attempts.

### Baseline defects confirmed

- Critical authorization gap: a trainer can accept another trainer's submission by posting a known submission ID. The list view is scoped, but the mutation endpoint does not independently enforce trainer/batch ownership. Phase 2 will fix this.
- Counting inconsistency (resolved in Phase 3): assignment dashboard totals previously included historical attempts, while operational review lists used only `is_latest = 1`. The regression fixture preserves two attempts but now verifies that only one latest attempt is counted operationally.
- Scalability evidence: the current dashboard sends approximately 1.21 MB of HTML for 390 assignments because it has no server-side pagination. Phase 5 will address this.

## Phase 1 — Assignment list layout

Status: Completed locally on 2026-07-21

### Target layout

| Assignment | Course context | Review progress | Actions |
| --- | --- | --- | --- |
| Title, description, attachment | Chapter, topic, date | Submitted, reviewed, pending | Review, manage |

### Tasks

- [x] Combine submission counters into one review-progress column.
- [x] Set predictable column widths and constrain long rich content, titles, and filenames.
- [x] Keep the Actions column visible or sticky on desktop.
- [x] Switch to card layout below approximately 992px.
- [x] Make small-screen actions full width.
- [x] Add accessible labels and preserve keyboard focus behavior through native links/buttons.
- [x] Verify responsive behavior visually in the local browser; the user confirmed the redesigned layout and visible Actions column.

### Acceptance criteria

- [x] The page has no horizontal scrolling at the user's tested desktop viewport.
- [x] Review and Manage are represented in a sticky desktop cell and full-width card actions below 992px.
- [x] Long content is constrained by fixed columns, wrapping, and a two-line rich-description clamp.
- [x] The route renders successfully with the production-sized assignment list.

### Phase 1 evidence

- Updated template: `templates/lms_admin/lms_all_assignments.html`.
- Added regression check: `scratch/test_assignment_layout_phase1.py`.
- Four-column desktop layout: Assignment, Course context, Review progress, and Actions.
- Desktop Actions cell is sticky at the right edge; tablet/mobile Actions are full-width card buttons.
- Card conversion now occurs below 992px rather than only below 576px.
- Docker route regression passed with 388 underlying assignments and 1,058 submission attempts.
- Rendered response decreased from approximately 1.21 MB in Phase 0 to approximately 1.00 MB after duplicate mobile markup was removed.
- The Phase 0 MySQL lifecycle regression suite still passes unchanged.
- Automated verification passed, and the user confirmed the rendered local layout on 2026-07-21.

## Phase 2 — Authorization hardening

Status: Completed locally on 2026-07-21

### Tasks

- [x] Require the LMS content-manager role on management and review routes.
- [x] Create a shared server-side submission authorization helper.
- [x] Allow administrators within their authorized branch scope.
- [x] Restrict staff to students in batches assigned to them.
- [x] Apply authorization to current lists, previews, downloads, and accept/reject actions; future history/queue routes must reuse the same helper.
- [x] Never use trainer or batch query parameters as proof of authorization.
- [x] Return HTTP 403 for unauthorized direct-ID requests.
- [x] Audit accept/reject review activity in the same transaction.

### Acceptance criteria

- [x] Changing a URL ID cannot expose another trainer's submission.
- [x] Staff cannot review outside their assigned batches.
- [x] Authorized administrator and trainer flows continue to work.
- [x] Cross-trainer authorization tests pass.

### Phase 2 evidence

- Shared authorization functions: `_current_lms_actor`, `_can_access_submission`, and `_require_submission_access` in `modules/lms_admin/routes.py`.
- All current assignment management/review routes require `lms_content_manager_required`.
- Global administrators can review all submissions; branch-limited administrators are restricted to their branch; staff are restricted to students in their active assigned batches.
- Preview, submission download, accept, and reject independently authorize the submission ID.
- Assignment and submission list queries enforce staff and branch-limited administrator scope rather than trusting filter parameters.
- Accept/reject decisions create `activity_logs` records inside the review transaction.
- Regression test: `scratch/test_assignment_authorization_phase2.py`.
- Verified denials: invalid role, inactive staff, cross-trainer direct ID, and cross-branch administrator direct ID.
- Verified allowed flows: assigned trainer and same-branch administrator.
- Phase 0 workflow and Phase 1 layout regressions continue to pass in local Docker/MySQL.

## Phase 3 — Correct submission counts

Status: Completed locally on 2026-07-21

### Counting rules

- Total submissions: latest submissions only.
- Pending: latest submission with `review_status = submitted`.
- Accepted: latest submission with `review_status = accepted`.
- Rejected: latest submission with `review_status = rejected`.
- Reviewed: accepted plus rejected.
- Attempts: all historical submission rows.

### Tasks

- [x] Add `is_latest = 1` consistently to assignment dashboard and topic-management count queries.
- [x] Use `review_status` consistently for pending and reviewed decisions.
- [x] Apply trainer, batch, and program filters to the same latest-attempt scoped dataset.
- [x] Add a composite assignment/latest/review-status index for the corrected count queries.
- [x] Exercise global, trainer-scoped, and topic-management query paths against production-sized local MySQL data.

### Acceptance criteria

- [x] Pending plus accepted plus rejected equals total latest submissions for supported statuses.
- [x] Historical attempts do not inflate dashboard totals.
- [x] Dashboard and submission-list counting rules agree on `is_latest` and `review_status`.
- [x] Counts stay correct after rejection and resubmission.

### Phase 3 evidence

- Corrected the global assignment overview, trainer/batch/program-scoped overview, and topic-level assignment management queries.
- Counts now follow these rules: total is every `is_latest = 1` row; reviewed is latest accepted plus rejected; pending is latest submitted.
- The template uses the query's explicit `pending_count` instead of deriving pending from potentially inconsistent totals.
- Added idempotent MySQL migration: `migrations/20260721_lms_assignment_latest_review_index.sql`.
- Added composite index: `idx_lms_asn_assignment_latest_review (assignment_id, is_latest, review_status)`.
- Regression test: `scratch/test_assignment_counts_phase3.py`.
- The fixture contains rejected history, a latest pending attempt, and a latest accepted attempt whose legacy `status` is deliberately inconsistent; the rendered counts correctly report total 2, reviewed 1, pending 1.
- Trainer A and Trainer B scoped dashboards correctly report only their respective latest attempts.
- Phase 0–2 suites continue to pass in local Docker/MySQL.
- The latest local dashboard test completed in approximately 43 ms after the corrected query/index changes; this is an observed smoke-test timing, not a formal performance guarantee.

## Phase 4 — Clickable review indicators

Status: Implemented locally; user visual QA pending

### Tasks

- [x] Link the main Pending Review card to assignments containing pending work; Phase 6 will retarget it to the centralized queue when that route exists.
- [x] Link assignment-level pending counts to filtered submissions.
- [x] Link Total Submissions and Reviewed counts to their matching assignment/submission filters.
- [x] Preserve current trainer, batch, and program context; future search/sort/page context will be added with Phase 5.
- [x] Add descriptive accessible labels and keyboard focus states.
- [x] Provide disabled zero-count indicators and useful empty-filter states.

### Acceptance criteria

- [x] Every non-zero review statistic opens the records it represents using the currently available pages.
- [x] Trainer, batch, program, and review-status filters survive navigation and review redirects.
- [x] Zero-result views show a useful empty state.

### Phase 4 evidence

- Dashboard cards now act as assignment activity filters for all assignments, assignments with submissions, pending review, and reviewed work.
- Summary totals remain stable while the assignment list shows the selected subset and displays “visible of total”.
- Per-assignment Submitted, Reviewed, and Pending counters link to the matching submission view.
- Added a combined Reviewed submission filter that displays both accepted and rejected latest submissions.
- Accept/reject redirects preserve the combined Reviewed filter.
- Zero counts render as disabled, non-clickable indicators.
- Added regression test: `scratch/test_assignment_indicators_phase4.py`.
- Phase 0–4 tests pass together in local Docker/MySQL.
- The centralized cross-assignment review queue is intentionally deferred to Phase 6; the Pending Review card will be retargeted then.
- User visual confirmation remains the final Phase 4 completion gate.

## Phase 5 — Server-side filtering and pagination

Status: Completed locally on 2026-07-21; user visual QA recommended

### Assignment filters

- [x] Assignment, chapter, or topic search
- [x] Trainer
- [x] Batch
- [x] Program/course
- [x] Review activity through the Phase 4 cards
- [x] Created-date range
- [x] Has pending submissions

### Submission filters

- [x] Student name, registration number, or filename
- [x] Assignment context through the assignment-specific route
- [x] Trainer
- [x] Batch
- [x] Program context inherited from the assignment
- [x] Review status
- [x] Submission-date range
- [x] Late/on-time status — implemented in Phase 9 with server-calculated due-date enforcement.

### Tasks

- [x] Move status filtering from browser-only JavaScript to SQL.
- [x] Add server-side pagination with a default page size of 25 and options for 50 or 100.
- [x] Support safe `page`, `per_page`, `sort`, and `direction` parameters.
- [x] Allowlist sortable database columns.
- [x] Preserve filters in dashboard cards, status links, pagination, batch selection, and review redirects.
- [x] Display “showing X–Y of Z”.
- [x] Calculate statistics with aggregate SQL without loading all rows.
- [x] Validate performance with production-sized and explicit 60-record fixtures.

### Acceptance criteria

- [x] Only displayed records are retrieved for each page.
- [x] Filtering and sorting cannot inject SQL because values are parameterized and sort columns are allowlisted.
- [x] Invalid page, page-size, sort, direction, date, and status parameters fall back safely.
- [x] Response times remain acceptable at expected local production volume.

### Phase 5 evidence

- Assignment overview now performs a summary aggregate, filtered count, and one `LIMIT/OFFSET` page query instead of loading every assignment.
- Assignment filters: text search, created-date range, trainer, batch, program, review activity, safe sorting, direction, and 25/50/100 page size.
- Submission view now performs summary, count, and one `LIMIT/OFFSET` page query instead of loading all latest submissions.
- Submission filters: student/registration/filename search, submitted-date range, batch/trainer scope, SQL-backed review status, safe sorting, direction, and 25/50/100 page size.
- Review actions preserve search, date, sorting, status, page size, and page context on redirect.
- Added regression test: `scratch/test_assignment_pagination_phase5.py`.
- The test creates exactly 60 assignments and 60 submissions and verifies page 1, middle/final pages, search, dates, accepted status, invalid inputs, and cleanup.
- Injection-like sort/direction parameters are rejected through allowlists; tables remain intact.
- Latest observed production-sized assignment route: approximately 28 ms and 116 KB for 25 displayed rows, compared with approximately 1.0–1.2 MB before pagination. Timings are local smoke-test observations, not production guarantees.
- A 25-row submission page measured approximately 37 ms and 102 KB in the 60-record fixture.
- Phase 0–5 suites pass together in local Docker/MySQL.

## Phase 6 — Centralized pending-review queue

Status: Completed locally on 2026-07-21; user visual QA recommended

Suggested route: `/lms_admin/reviews`

### Queue content

- Student and registration number
- Assignment
- Program, batch, and trainer
- Submitted time
- Attempt number
- Due/late status
- Review status
- Review action

### Tasks

- [x] Default to pending submissions, oldest first.
- [x] Reuse Phase 5 search, date, status, sorting, page-size, and pagination behavior.
- [x] Automatically scope trainers to their own active assigned batches.
- [x] Let authorized administrators view their global or branch-limited scope.
- [x] Show pending workload totals by trainer, batch, and program.
- [x] Link entries to the existing Preview and filtered per-assignment Review views; Phase 7 will retarget Review to the integrated screen.

### Acceptance criteria

- [x] Trainers can find and enter their complete pending workload from one queue.
- [x] Users do not need to open every assignment to find pending work.
- [x] Queue entries respect trainer, batch, administrator, and branch authorization scope.
- [x] Queue totals use the same latest-attempt/status rules as the assignment dashboard.

### Phase 6 evidence

- Added authorized route: `/lms_admin/master/reviews` (`lms_admin.review_queue`).
- Added responsive template: `templates/lms_admin/lms_review_queue.html`.
- The default queue is pending-only and oldest-submitted-first.
- Available filters: trainer, batch, program, status, student/registration/assignment/filename search, submitted-date range, sorting, direction, and 25/50/100 rows per page.
- Status views: Pending, Reviewed, Accepted, Rejected, and All through query parameters.
- Each queue record shows student, registration number, assignment, chapter/topic, program, active batch, trainer, submitted time, status, filename, Preview, and Review actions.
- Pending workload breakdowns display the top authorized trainer, batch, and program groupings.
- Staff are forced to their own active batches; branch-limited administrators cannot see other branches; global administrators can use all authorized filters.
- Assignment dashboard Total Submissions, Pending Review, and Reviewed cards now open the centralized queue with scope/search/date context.
- Added Review Queue navigation to desktop LMS sidebars and assignment activation to mobile navigation.
- Added regression test: `scratch/test_assignment_review_queue_phase6.py`.
- The 60-submission fixture verifies pending=20, reviewed=40, all=60, pagination, search, program filtering, trainer isolation, branch isolation, role denial, navigation, workload breakdowns, invalid-input safety, and cleanup.
- Phase 0–6 suites pass together in local Docker/MySQL.

## Phase 7 — Integrated preview-and-review screen

Status: Complete (local Docker/MySQL verification)

Suggested route: `/lms_admin/reviews/<submission_id>`

### Tasks

- [x] Show assignment instructions and student/submission details.
- [x] Preview PDFs and supported images directly.
- [x] Provide secure downloads for unsupported formats.
- [x] Retain Office preview only where securely available.
- [x] Put feedback and decision controls beside the preview.
- [x] Add Previous Pending and Next Pending navigation.
- [x] Preserve queue filters while navigating.
- [x] Confirm final review actions.
- [x] Use atomic updates to prevent double review.
- [x] Explain when another reviewer already processed the submission.

### Acceptance criteria

- [x] Preview and decision controls work on one screen.
- [x] Reviewers do not need multiple tabs.
- [x] Previous/Next stays inside the authorized filtered queue.
- [x] Concurrent reviews cannot overwrite a decision.

### Phase 7 evidence

- Added integrated route: `/lms_admin/master/reviews/<submission_id>` (`lms_admin.review_submission_detail`).
- The queue Review action now opens the integrated screen while preserving trainer, batch, program, status, search, date, sort, direction, page size, and page context.
- The screen shows student and submission metadata, chapter/topic context, assignment instructions, filename, and submission time.
- PDFs and browser-safe images render inline through the authorized download endpoint; unsupported formats retain an authorized download action.
- Office documents use the existing short-lived public preview token only on public HTTPS; localhost displays a safe download fallback.
- Feedback, required rejection reason, Accept, and Reject controls sit beside the preview with final-action confirmation prompts.
- Previous Pending and Next Pending use the same authorized, filtered, latest-attempt queue and selected ordering.
- Successful decisions advance to the next pending item or return to the queue; validation failures return to the same review screen.
- Existing conditional database updates remain atomic, so an already processed or superseded attempt cannot be overwritten and displays a clear warning/read-only state.
- LMS desktop and mobile navigation keep Review Queue active on the detail screen.
- Added regression test: `scratch/test_assignment_review_detail_phase7.py`.
- Local Docker/MySQL tests verify integrated rendering, filtered navigation, queue links, trainer isolation, accept-and-advance, read-only reviewed state, and duplicate-decision protection.

## Phase 8 — Reviewer identity and attempt history

Status: Complete (local Docker/MySQL verification)

### Tasks

- [x] Display reviewer name and reviewed timestamp.
- [x] Show attempt number, submitted date, filename, decision, reviewer, feedback, reason, and score availability.
- [x] Allow authorized staff to preview earlier attempts.
- [x] Keep historical attempts read-only.
- [x] Define file and attempt retention policy.

### Acceptance criteria

- [x] Every reviewed submission identifies its reviewer, with an explicit legacy fallback where old data lacks one.
- [x] Previous attempts remain available but cannot be reviewed again.
- [x] Only the latest pending attempt is actionable.
- [x] Student and staff histories agree.

### Phase 8 evidence

- The integrated review screen now shows reviewer identity and reviewed timestamp for completed decisions.
- Added an authorized attempt-history table containing attempt number, submitted time, filename, decision, reviewed time, reviewer, feedback, rejection reason, score availability, latest marker, and a preview link.
- Historical attempt links reuse the integrated preview page and submission-level authorization but remain read-only because they are not the latest pending attempt.
- Reviewer accounts that still exist display by name; deleted-account references display by account ID; legacy rows without reviewer data are labeled explicitly rather than appearing blank.
- The student assignment API returns the same ordered attempt rows and reviewer identity as the staff view.
- The student assignment page displays a read-only expandable Attempt History with authorized downloads of the student's own earlier files.
- Phase 9 now supplies score fields; pre-Phase 9 attempts without scores display as `Not scored`.
- Added regression test: `scratch/test_assignment_attempt_history_phase8.py`.
- The reject → resubmit → accept fixture verifies two numbered attempts, reviewer identity, timestamps, feedback/reason visibility, staff/student agreement, trainer authorization, and historical read-only behavior.

### File and attempt retention policy

- Submission metadata and uploaded files are retained for the lifetime of the associated student and assignment record; superseded attempts are not automatically purged.
- `is_latest = 0` makes an earlier attempt historical, not deleted. Historical decisions and review fields are immutable through the review UI.
- Files remain protected by staff submission authorization or student ownership checks; history does not expose public file URLs directly.
- No automated retention deletion is introduced in Phase 8. Any future archival or regulatory purge must remove the database record and storage object together through a separately authorized, audited process.

## Phase 9 — Optional grading and completion rules

Status: Complete (local Docker/MySQL verification; production migration required)

### Proposed assignment fields

- `due_at`
- `max_score`
- `passing_score`
- `grading_mode`
- `rubric_id`
- `completion_rule`
- `allow_late_submission`
- `max_attempts`

### Proposed submission fields

- `score`
- `is_late`
- `graded_at`
- Optional internal reviewer notes separated from student-visible feedback

### Proposed tables

- `lms_rubrics`
- `lms_rubric_criteria`
- `lms_submission_rubric_scores`

### Supported grading modes

- Accept/reject only
- Numeric score
- Rubric
- Numeric score plus rubric

### Supported completion rules

- Accepted submission
- Score meets passing score
- All required assignments accepted
- Any required assignment accepted
- Manual topic completion
- Assignment does not affect topic completion

### Tasks

- [x] Make all new grading fields optional and backward-compatible.
- [x] Calculate late status on the server.
- [x] Validate scores against maximum score.
- [x] Require rubric criterion scores when applicable.
- [x] Centralize topic-completion calculation.
- [x] Define behavior when grading decisions change.

### Acceptance criteria

- [x] Existing assignments retain current behavior by default.
- [x] Scores and rubrics are validated on the server.
- [x] Completion rules produce predictable topic progress.
- [x] Students can see score, feedback, and resubmission eligibility.

### Phase 9 evidence

- Added production migration `migrations/20260721_lms_assignment_grading_rules.sql` with optional assignment grading/deadline fields, submission grading fields, rubric tables, criteria, and per-submission criterion scores.
- Existing assignments default to `accept_reject`, `accepted_submission`, late submissions allowed, required assignment, unlimited attempts, and no score/rubric; this preserves the pre-Phase 9 workflow.
- Assignment create/edit forms now configure due date, maximum attempts, grading mode, maximum/passing scores, an existing active rubric, completion rule, late-submission permission, and required/optional status.
- Server validation enforces grading-mode values, completion-rule values, due-date format, positive score ranges, passing score ≤ maximum score, rubric existence, rubric total consistency, and maximum attempts from 1–100.
- The integrated review screen displays deadline/late state, numeric score controls, required rubric criteria, criterion comments, and staff-only internal notes.
- Numeric and rubric values are validated again on the server; numeric-plus-rubric totals must match and score-based acceptance must meet the configured passing score.
- Submission lateness and maximum-attempt eligibility are calculated/enforced by the student submission endpoint, independent of browser behavior.
- Topic completion is recalculated through one helper after accept/reject. Explicit all-required, any-required, score threshold, manual, and no-effect rules are supported; default accepted-submission behavior remains compatible.
- Rejection recalculates progress and permits another attempt only when deadline and maximum-attempt rules allow it. Accepted submissions remain final under the existing resubmission policy.
- Students see due date, late status, score/max score, feedback, attempt limits, history, and whether another submission is allowed. Internal reviewer notes are never included in the student API.
- Added regression test `scratch/test_assignment_grading_phase9.py` covering score bounds, required rubric criteria, rubric totals, score completion, private notes, late blocking/allowance, and maximum attempts.
- Phase 0–9 regression suites pass against local Docker/MySQL.

## Phase 10 — Full verification and deployment

Status: Pending

### Automated coverage

- [ ] Administrator access
- [ ] Authorized trainer access
- [ ] Cross-trainer and direct-ID denial
- [ ] Latest-attempt counts
- [ ] Rejection and resubmission
- [ ] Duplicate/concurrent review
- [ ] Pagination, filtering, and sorting
- [ ] Score and rubric validation
- [ ] Completion rules
- [ ] Preview and download authorization

### Manual responsive coverage

- [ ] Desktop, tablet, and mobile
- [ ] Long titles and filenames
- [ ] Rich descriptions containing tables
- [ ] Empty states
- [ ] Production-sized results

### Deployment sequence

1. Back up the database before schema migrations.
2. Apply backward-compatible migrations.
3. Build and test the Docker image.
4. Deploy a no-traffic Cloud Run revision.
5. Run authenticated smoke tests.
6. Shift traffic gradually: 5%, 25%, 50%, then 100%.
7. Monitor authorization errors, SQL errors, and response latency.
8. Retain the previous revision for rollback.

### Acceptance criteria

- [ ] Docker/MySQL regression suite passes.
- [ ] Production-like smoke tests pass.
- [ ] The new Cloud Run revision reports no blocking errors.
- [ ] Rollback remains available until post-deployment verification completes.

## Phase completion record

| Phase | Status | Completed date | Evidence/notes |
| --- | --- | --- | --- |
| 0 | Completed locally | 2026-07-21 | MySQL/Flask baseline suite passed; authorization and count gaps documented. |
| 1 | Completed locally | 2026-07-21 | Implementation, Docker regressions, and user visual verification passed. |
| 2 | Completed locally | 2026-07-21 | Role, trainer/batch, branch, direct-ID, and audit-log tests passed. |
| 3 | Completed locally | 2026-07-21 | Latest-attempt global/scoped/topic counts and composite index tests passed. |
| 4 | Visual QA pending |  | Click targets, filtering, context preservation, and regressions passed on 2026-07-21. |
| 5 | Completed locally | 2026-07-21 | SQL filtering/pagination, allowlist safety, context preservation, and 60-record tests passed. |
| 6 | Completed locally | 2026-07-21 | Central queue, scope enforcement, workload summaries, pagination, and 60-record tests passed. |
| 7 | Pending |  |  |
| 8 | Pending |  |  |
| 9 | Pending |  |  |
| 10 | Pending |  |  |
