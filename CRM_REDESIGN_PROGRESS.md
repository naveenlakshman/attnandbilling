# CRM Redesign Progress

## Phase 0 - Safety Setup
Date: 2026-05-08
Status: Completed

### Safety actions completed
- Git branch created: `leads-crm-redesign`
- Database backup created:
  - Source: `instance/database.db`
  - Backup: `instance/database_backup_before_crm_redesign.db`
- Business logic changes in this phase: None

### Current lead routes
Source: `modules/leads/routes.py`

- `/leads/`
- `/leads/new` (GET, POST)
- `/leads/<int:lead_id>`
- `/leads/list`
- `/leads/<int:lead_id>/followups/new` (POST)
- `/leads/<int:lead_id>/edit` (GET, POST)
- `/leads/<int:lead_id>/stage` (POST)
- `/leads/<int:lead_id>/reassign` (POST)
- `/leads/followups`
- `/leads/pipeline`
- `/leads/reports`
- `/leads/activity-log`
- `/leads/<int:lead_id>/delete` (POST)
- `/leads/deleted`
- `/leads/<int:lead_id>/restore` (POST)
- `/leads/<int:lead_id>/mark-lost` (POST)
- `/leads/<int:lead_id>/ai-assist` (POST)

### Current leads templates
Source: `templates/leads/`

- `activity_log.html`
- `base.html`
- `dashboard.html`
- `deleted_leads.html`
- `followups.html`
- `leads_list.html`
- `lead_detail.html`
- `lead_form.html`
- `pipeline.html`
- `reports.html`

### Current table schema - leads
```sql
CREATE TABLE leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    whatsapp TEXT,
    gender TEXT,
    age INTEGER,
    education_status TEXT,
    stream TEXT,
    institute_name TEXT,
    career_goal TEXT,
    interested_courses TEXT,
    lead_source TEXT,
    decision_maker TEXT DEFAULT 'Self',
    start_timeframe TEXT,
    lead_score INTEGER DEFAULT 0,
    stage TEXT DEFAULT 'New Lead',
    status TEXT DEFAULT 'active',
    lost_reason TEXT,
    last_contact_date TEXT,
    next_followup_date TEXT,
    followup_count INTEGER DEFAULT 0,
    notes TEXT,
    is_deleted INTEGER DEFAULT 0,
    assigned_to_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    lead_location TEXT,
    email TEXT,
    FOREIGN KEY (assigned_to_id) REFERENCES users(id)
)
```

### Current table schema - followups
```sql
CREATE TABLE followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    user_id INTEGER,
    method TEXT,
    outcome TEXT,
    note TEXT,
    next_followup_date TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
```

### Current table schema - users
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
    phone TEXT,
    branch_id INTEGER,
    can_view_all_branches INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (branch_id) REFERENCES branches(id)
)
```

### Backup command reference
Use this before any DB-changing phase:

```powershell
Copy-Item -Path "instance/database.db" -Destination "instance/database_backup_before_crm_redesign.db" -Force
```

## Phase 1 - Lead Access Security Hardening
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/helpers.py` (new)
- `modules/leads/routes.py`

### What was implemented
- Added `can_access_lead(user_id, role, lead_assigned_to_id)` helper.
- Added `get_lead_or_404_with_access(conn, lead_id, session_obj, include_deleted=False)` helper.
- Applied centralized access checks on these routes:
    - `/leads/<int:lead_id>`
    - `/leads/<int:lead_id>/edit`
    - `/leads/<int:lead_id>/followups/new`
    - `/leads/<int:lead_id>/stage`
    - `/leads/<int:lead_id>/reassign`
    - `/leads/<int:lead_id>/delete`
    - `/leads/<int:lead_id>/restore`
    - `/leads/<int:lead_id>/mark-lost`
    - `/leads/<int:lead_id>/ai-assist`

### Access policy now enforced
- Admin can access all leads.
- Staff can access only assigned leads.
- Unassigned leads are restricted for staff by default.
- Existing admin behavior remains intact.

### Manual test checklist
1. Login as admin and open any lead detail page.
2. Login as staff and open an assigned lead.
3. Login as staff and try opening another staff member's lead by URL.
4. As staff, try posting to edit/followup/stage/reassign/delete/restore/mark-lost/ai-assist on unassigned or other-owner lead IDs.
5. Confirm blocked actions show safe access-denied behavior.

---
## Phase 2 - Database Hardening Without Breaking Data
Date: 2026-05-08
Status: Completed

### Files changed
- `db.py`

### What was implemented
- Added safe indexes using `CREATE INDEX IF NOT EXISTS` in `init_db()` for:
    - `leads.assigned_to_id`
    - `leads.status`
    - `leads.stage`
    - `leads.next_followup_date`
    - `leads.created_at`
    - `leads.is_deleted`
    - `followups.lead_id`
    - `followups.created_at`
    - `activity_logs.module_name`
    - `activity_logs.user_id`
    - `activity_logs.created_at`

### Safety guarantees kept
- No existing column removed.
- No existing route changed for behavior in this phase.
- No NOT NULL or UNIQUE constraints introduced.
- No conversion flow changes.

### Manual test checklist
1. Start app and ensure startup completes without DB errors.
2. Open leads list page.
3. Open leads dashboard page.
4. Open follow-up page.
5. Open leads reports page.

---
## Phase 3 - Extract Lead Business Logic
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/services.py` (new)
- `modules/leads/routes.py`

### Service functions added
- `compute_lead_score(lead_data)`
- `map_stage_to_status(stage)`
- `get_next_stages(current_stage)`
- `update_lead_stage(conn, lead_id, new_stage, user_id)`
- `log_lead_activity(conn, lead_id, user_id, action_type, description)`

### Route wiring completed
- Create and edit flows now use service score + stage status mapping.
- Stage update flow now uses `update_lead_stage(...)` with centralized transition + logging.
- Mark-lost flow now uses service status mapping and service activity logging.
- Existing UI routes and templates were not redesigned in this phase.

### Safety guarantees kept
- Existing route URLs preserved.
- Existing templates preserved.
- Existing billing conversion flow unchanged.
- No schema change in this phase.

### Manual test checklist
1. Create a lead and verify score/stage/status behavior remains correct.
2. Edit a lead and verify score recalculation + status mapping remain correct.
3. Change stage from lead detail/pipeline/list and verify update + activity log entry.
4. Mark lead as lost with reason and verify status, reason, and log entry.
5. Confirm convert-to-student path still redirects to existing billing flow.

---
## Phase 4 - Create CRM-Specific Helper Layer
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/services.py`
- `modules/leads/routes.py`

### Helper functions added
- `get_followup_status(next_followup_date)`
    - Returns: `overdue`, `today`, `upcoming`, `none`
- `get_inactive_days(last_contact_date, updated_at)`
    - Returns days since last contact fallbacking to updated date
- `get_lead_temperature(score, followup_status, stage)`
    - `Converted` and `Lost` terminal temperatures
    - Score based: `Hot`, `Warm`, `Cold`
- `get_next_action(lead)`
    - Stage-aware action recommendations with overdue override
- `enrich_lead_for_crm(lead)`
    - Injects computed fields into lead objects for view rendering

### Route integration done (no UI redesign yet)
- Dashboard lead collections now include computed CRM fields.
- Lead detail lead object now includes computed CRM fields.
- Leads list now includes computed CRM fields.
- Follow-ups page now includes computed CRM fields and overdue count uses follow-up status.
- Pipeline card data now includes computed CRM fields.

### Safety guarantees kept
- No database schema change in this phase.
- No route URL changes.
- No conversion flow changes.
- Existing templates left structurally unchanged.

### Manual test checklist
1. Open dashboard and verify pages render with no errors.
2. Open leads list and verify list renders with existing filters.
3. Open lead detail and verify page renders and existing actions work.
4. Open followups page and confirm overdue count still matches expected records.
5. Open pipeline and verify stage columns and cards render normally.

---
## Phase 5 - Dashboard Redesign Into Action Center
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/dashboard.html`

### Route updates
- Dashboard route now computes action-center datasets:
    - overdue follow-up count and top overdue list
    - today follow-up count
    - hot leads count and top hot list
    - inactive leads count (7+ days idle)
    - new leads not contacted list
- Owner fields are included in action lists (`owner_name` / `owner_username`).
- Existing summary metrics are preserved for legacy/secondary display.

### UI updates
- Added top section: **Today's Action Center**.
- Added priority KPI cards in required order:
    1. Overdue Follow-ups
    2. Today Follow-ups
    3. Hot Leads
    4. New Leads Today
    5. Inactive Leads
    6. Converted This Month
- Added quick action lists:
    - Top 5 overdue follow-ups
    - Top 5 hot leads
    - New leads not contacted
- Each list item shows:
    - name
    - phone
    - course (`interested_courses`)
    - owner
    - next follow-up date
    - quick buttons: Call, WhatsApp, Open
- Kept legacy metrics and pipeline snapshots in secondary sections.

### Safety guarantees kept
- No database schema change.
- No route URL changes.
- No billing conversion flow changes.
- Existing metrics retained below action center.

### Manual test checklist
1. Login as admin and open leads dashboard.
2. Verify six action-center cards display counts in priority order.
3. Verify quick lists render and each item shows name, phone, course, owner, next follow-up date.
4. Verify Call, WhatsApp, and Open actions work.
5. Login as staff and verify dashboard only reflects assigned leads.
6. Compare overdue/today counts against `/leads/followups` filtered results.

---
## Phase 6 - Leads List Redesign
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/leads_list.html`

### Backend updates (`/leads/list`)
- Added new filters while preserving existing ones:
    - search (`q`)
    - my leads (`my_leads`) for admin scope
    - stage (`stage`)
    - priority/temperature (`temperature`)
    - course (`course`)
    - source (`source`)
    - follow-up due state (`followup_due`: `today`/`overdue`)
    - status (`status_filter`: `active`/`converted`/`lost`)
    - existing date range filters retained
    - existing active-only toggle retained
- Added role-aware metrics scope so staff and admin scoped views align better with displayed lead set.
- Added dynamic course options from existing lead data.

### UI updates
- Redesigned leads list filters for counseling workflow while retaining old filters.
- Mobile card view now shows:
    - name, phone, course
    - stage badge
    - temperature badge
    - follow-up urgency badge (Overdue/Today)
    - score
    - last contact
    - next follow-up
    - owner
    - actions: Call, WhatsApp, Add Follow-up, Open
- Desktop table now includes required columns:
    - Name
    - Phone
    - Course
    - Stage badge
    - Temperature badge
    - Score
    - Last Contact
    - Next Follow-up
    - Owner
    - Actions
- Badge color rules applied:
    - Hot = danger
    - Warm = warning
    - Cold = primary
    - Converted = success
    - Lost = secondary
    - Overdue = danger
    - Today = warning

### Safety guarantees kept
- Existing route URL preserved (`/leads/list`).
- Existing filters retained (no destructive removal).
- No database schema changes.
- No billing conversion flow changes.

### Manual test checklist
1. Open `/leads/list` and verify page loads in desktop and mobile widths.
2. Validate search by name/phone.
3. Validate stage, source, temperature, course, status filters.
4. Validate Today Follow-up and Overdue quick filters.
5. Validate Active Only toggle still works.
6. As admin, test My Leads scope and user filter behavior.
7. As staff, verify only assigned leads are listed.
8. Verify Call, WhatsApp, Add Follow-up, and Open actions work from list.

---
## Phase 7 - Lead View Page Redesign
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/lead_detail.html`

### Route updates
- `lead_detail` now fetches lead activity log entries (`module_name='leads'`) for the same lead ID.
- Added unified timeline preparation by merging:
    - followups
    - activity log entries
- Added alert context for lead detail view:
    - overdue follow-up alert
    - due-today alert
    - inactive-days alert
    - never-contacted alert

### UI updates
- Lead detail now behaves more like a CRM action screen:
    - Expanded top summary badges include stage, temperature, score, last contact, next follow-up, next action
    - Primary actions include: Call, WhatsApp, Add Follow-up, Convert to Student, Mark Lost, Edit
    - Added dedicated Next Action panel in the right column
    - Quick follow-up form is anchored for direct action links
    - Timeline now combines followups + activity logs in one stream with type badges
    - Alert banner area added for important lead conditions

### Safety guarantees kept
- Existing lead detail route URL preserved.
- Existing conversion flow to billing preserved.
- Existing follow-up/add/edit/lost actions preserved.
- No schema changes.

### Manual test checklist
1. Open an active lead and verify top summary values render (stage, temperature, score, next action).
2. Use Call and WhatsApp buttons.
3. Use Add Follow-up button and submit a follow-up.
4. Mark lead as lost and verify behavior unchanged.
5. Use Convert to Student button and ensure billing flow opens as before.
6. Verify timeline shows both follow-up and activity entries.
7. Login as admin and staff and verify access restrictions still apply from Phase 1.

---
## Phase 8 - Follow-up Page Redesign
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/followups.html`

### Route updates
- Redesigned `/leads/followups` data flow into tab buckets:
    - Overdue
    - Today
    - Tomorrow
    - Upcoming
    - Completed (today)
- Added last-note enrichment on due follow-up rows using latest followup note per lead.
- Added completed-today feed from `followups.created_at` with role-based access filtering.
- Added new POST endpoint: `/leads/followups/complete` for quick complete and reschedule actions.
- Quick complete/reschedule now:
    - inserts followup record
    - updates `leads.last_contact_date`
    - updates `leads.next_followup_date`
    - updates `leads.next_action`
    - increments `leads.followup_count`
    - logs activity (`followup_completed`)

### UI updates
- Follow-up page now acts as a daily calling screen with tabbed workflow.
- Added tab chips and counts for Overdue, Today, Tomorrow, Upcoming, Completed.
- Added richer row/card fields:
    - lead name
    - phone
    - course
    - stage
    - temperature
    - counselor
    - due/completed date
    - last note
- Added required actions:
    - Call
    - WhatsApp
    - Complete
    - Reschedule
    - Open
- Added Quick Complete modal with fields:
    - outcome
    - notes
    - next follow-up date
    - next action

### Safety guarantees kept
- Existing `/leads/followups` URL preserved.
- Existing lead detail and conversion routes preserved.
- No schema changes.
- Staff/admin access restrictions still enforced via assignment checks.

### Manual test checklist
1. Open `/leads/followups` and switch across all five tabs.
2. Validate Overdue and Today counts against expected leads.
3. As admin, filter by counselor and confirm tab counts/list update.
4. As staff, verify only assigned followups are visible.
5. Use Complete action and verify lead last contact, next follow-up, and activity log update.
6. Use Reschedule action without outcome and verify default behavior works.
7. Verify Completed tab shows today's followup entries.
8. Verify Call, WhatsApp, and Open buttons from desktop and mobile views.

---
## Phase 9 - Pipeline Redesign Into Kanban
Date: 2026-05-08
Status: Completed

### Files changed
- `templates/leads/pipeline.html`

### Route compatibility kept
- Existing `/leads/pipeline` route preserved.
- Existing stage update route preserved (`/leads/<int:lead_id>/stage`).
- Existing permission model preserved:
    - admin sees all (or selected counselor)
    - staff sees assigned leads only

### UI updates
- Pipeline transformed into Kanban-style board with 7 columns:
    - New Lead
    - Contacted
    - Interested
    - Counseling Done
    - Follow-up
    - Converted
    - Lost
- Each card now displays required details:
    - Name
    - Phone
    - Course
    - Score
    - Temperature
    - Owner
    - Next follow-up
    - Follow-up status
- Card border color rules applied:
    - Red for overdue
    - Orange for today
    - Green for converted
    - Gray for lost
- Stage movement remains button-based (no drag and drop in this phase).

### Safety guarantees kept
- No schema changes.
- No route URL changes.
- No billing conversion flow changes.

### Manual test checklist
1. Open `/leads/pipeline` and verify all 7 columns render.
2. As admin, switch counselor filter and verify board updates.
3. As staff, verify only assigned leads are visible.
4. Verify card details show name, phone, course, score, temperature, owner, next follow-up, status.
5. Verify border colors for overdue/today/converted/lost cards.
6. Click stage move buttons and confirm lead moves to next column.
7. Verify Converted and Lost cards show no further stage buttons.

---
## Phase 10 - Reports Redesign
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/reports.html`

### Route updates
- Enhanced `/leads/reports` with additional business metrics:
    - follow-up completion rate
    - hot lead conversion rate
    - average days to conversion
- Added new report datasets:
    - lost reason report (`lost_reason` grouped counts)
    - monthly conversion trend (grouped by `updated_at` month)
- Kept existing report capabilities:
    - counselor performance
    - lead source conversion
    - course-wise conversion
    - date range and user filters
- Access policy unchanged (admin-only reports route preserved).

### UI updates
- KPI section expanded to include:
    - Total Leads
    - Active Leads
    - Converted Leads
    - Lost Leads
    - Conversion Rate
    - Follow-up Completion Rate
    - Hot Lead Conversion Rate
    - Avg Days to Conversion
- Retained and improved tables for:
    - Counselor performance
    - Lead source conversion
    - Course-wise conversion
- Added two new report blocks:
    - Lost Reason Report
    - Monthly Conversion Trend

### Safety guarantees kept
- Existing `/leads/reports` URL preserved.
- Existing filters preserved (`date_from`, `date_to`, `user_id`).
- No schema changes.
- Staff access behavior remains aligned with existing policy (admin-only route).

### Manual test checklist
1. Open `/leads/reports` as admin and verify all KPI cards render.
2. Filter by date range and confirm KPI + tables update.
3. Filter by counselor and confirm metrics update.
4. Verify counselor performance table sorting/values look correct.
5. Verify lead source and course conversion tables render expected counts and rates.
6. Verify lost reason report renders grouped reasons.
7. Verify monthly conversion trend renders month-wise converted counts.
8. Verify non-admin cannot access reports route.

---
## Phase 11A - Pre-Migration Safety
Date: 2026-05-08
Status: Completed

### Safety actions completed
- Database backup created:
    - Source: `instance/database.db`
    - Backup: `instance/database_backup_before_phase_11.db`
- App initialization check passed (`app_init_ok`).
- Core leads template compile checks passed:
    - `leads/leads_list.html`
    - `leads/lead_detail.html`

### Schema inspection completed
Tables inspected:
- `leads`
- `followups`
- `students`
- `users`
- `branches`

Current `leads` columns confirmed:
- `id, name, phone, whatsapp, gender, age, education_status, stream, institute_name, career_goal, interested_courses, lead_source, decision_maker, start_timeframe, lead_score, stage, status, lost_reason, last_contact_date, next_followup_date, followup_count, notes, is_deleted, assigned_to_id, created_at, updated_at, lead_location, email`

### Phase 11 target columns status
- `branch_id` -> missing
- `conversion_date` -> missing
- `lost_reason` -> already exists
- `parent_discussion_status` -> missing
- `visit_status` -> missing

### Suggested ALTER statements (missing columns only)
```sql
ALTER TABLE leads ADD COLUMN branch_id INTEGER;
ALTER TABLE leads ADD COLUMN conversion_date TEXT;
ALTER TABLE leads ADD COLUMN parent_discussion_status TEXT DEFAULT 'Pending';
ALTER TABLE leads ADD COLUMN visit_status TEXT DEFAULT 'Not Visited';
```

### Notes
- `lost_reason` must not be added again.
- Migration should be implemented in `db.py` `init_db()` with `add_column_if_not_exists(...)` for safety.
- Pre-Phase 11 git commit is still pending (not created in this step).

---
## Phase 11B - Add Columns Safely
Date: 2026-05-08
Status: Completed

### Files changed
- `db.py`

### Migration implementation
- Added safe migration columns in `init_db()` using `add_column_if_not_exists(...)` for `leads`:
    - `branch_id INTEGER`
    - `conversion_date TEXT`
    - `parent_discussion_status TEXT DEFAULT 'Pending'`
    - `visit_status TEXT DEFAULT 'Not Visited'`
- Confirmed `lost_reason` is not re-added (already exists).

### Indexes added
- `idx_leads_branch_id`
- `idx_leads_conversion_date`
- `idx_leads_lost_reason`
- `idx_leads_parent_discussion_status`
- `idx_leads_visit_status`

### Validation
- `db.py` has no editor errors.
- App init passed after migration logic update (`app_init_ok`).
- Database schema re-check confirms required Phase 11 fields now exist:
    - `branch_id`
    - `conversion_date`
    - `lost_reason`
    - `parent_discussion_status`
    - `visit_status`

### Safety guarantees kept
- No destructive data migration in this step.
- No route URL changes.
- No billing conversion flow changes in this step.

---
## Phase 11C - Backfill Existing Data
Date: 2026-05-08
Status: Completed

### Files changed
- `db.py`

### Backfill logic implemented (idempotent)
- Added safe backfill in `init_db()` for `leads`:
    - `branch_id` from `users.branch_id` where lead has `assigned_to_id` and branch is available
    - `conversion_date` for legacy converted leads using `COALESCE(substr(updated_at,1,10), substr(created_at,1,10))`
    - `parent_discussion_status` defaulted to `Pending` where null/blank
    - `visit_status` defaulted to `Not Visited` where null/blank
- `lost_reason` left untouched (no guessed backfill).

### Validation
- `db.py` has no editor errors.
- App initialization passed (`app_init_ok`).
- Live DB sanity checks after startup:
    - `parent_null=0`
    - `visit_null=0`
    - `converted_without_conversion_date=0`
    - `assigned_without_branch=0`

### Safety guarantees kept
- Backfill is non-destructive and repeat-safe.
- No route URL changes.
- No billing conversion flow changes in this step.

---
## Phase 11D - Update Add/Edit Lead Form
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/lead_form.html`

### Form/UI updates
- Added `Branch` field to lead form with role-safe behavior:
    - admin / all-branch users: selectable active branch dropdown
    - staff with mapped branch: auto-mapped and locked display
    - staff without mapped branch: nullable branch allowed with info hint
- Added `Parent Discussion Status` dropdown options:
    - Pending
    - Not Required
    - Scheduled
    - Completed
    - Parent Not Responding
    - Parent Rejected
- Added `Visit Status` dropdown options:
    - Not Visited
    - Visit Scheduled
    - Visited
    - Demo Attended
    - Not Interested After Visit

### Route logic updates
- Create flow (`/leads/new`) now saves:
    - `branch_id`
    - `parent_discussion_status`
    - `visit_status`
- Edit flow (`/leads/<id>/edit`) now updates these fields safely.
- Added targeted activity logs on edit when these fields change:
    - parent discussion status changes
    - visit status changes
    - branch changes

### Safety guarantees kept
- No route URL changes.
- Existing required validation (name/phone) preserved.
- Existing lead score/stage/status update behavior preserved.

### Validation
- No editor errors in modified files.
- Lead form template compile check passed (`lead_form_template_ok`).
- App initialization passed (`app_init_ok`).

---
## Phase 11E - Update Lead Detail Page
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/lead_detail.html`

### Route updates
- Lead detail query now includes branch metadata via `branches` join:
    - `branch_name`
    - `branch_code`
- Added fallback display label when `branch_id` exists but branch name is unavailable.
- Added new alert rules for CRM fields:
    - parent discussion pending
    - visit scheduled
    - visited but not converted
    - lost reason prominent alert when stage is lost

### UI updates
- Lead summary badges now include:
    - Parent discussion status
    - Visit status
- Lead details section now shows:
    - Branch (name/code)
    - Parent Discussion Status
    - Visit Status
    - Conversion Date (for converted leads)
    - Lost Reason (existing, retained)
- Existing action bar, follow-up form, timeline, and AI assist blocks preserved.

### Safety guarantees kept
- No route URL changes.
- No schema changes.
- No conversion-flow changes.
- Existing lead actions and timeline behavior preserved.

### Validation
- No editor errors in modified files.
- Lead detail template compile check passed (`lead_detail_template_ok`).
- App initialization passed (`app_init_ok`).

---
## Phase 11F - Update Mark Lost Flow
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/lead_detail.html`

### Route updates
- Added `LOST_REASONS` constant with 10 defined options:
  Fees High, Joined Other Institute, Parent Rejected, No Response,
  Course Not Required, Timing Issue, Location Issue, Not Eligible,
  Duplicate Lead, Other
- `lead_mark_lost` route now:
  - Validates `lost_reason` is non-empty and must be one of the defined options (whitelist)
  - Accepts optional `lost_note` from form
  - Appends note to activity log description when provided
- Flash message updated to "Please select a lost reason."

### Template updates
- Mark Lost panel replaced plain text input with:
  - Required `<select>` dropdown pre-selecting current `lead.lost_reason` if already lost
  - Optional `<textarea>` for additional notes
  - Properly labeled fields with required marker on reason

### Safety guarantees kept
- No schema changes.
- No route URL changes.
- Empty/invalid reason still blocked server-side.

### Validation
- No editor errors in modified files.
- Lead detail template compile passed (`lead_detail_template_ok`).
- App initialization passed (`app_init_ok`).

---
Next planned phase: Phase 11G - Update conversion flow
---
## Phase 11G - Update Conversion Flow
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/billing/routes.py`

### Route updates
- When an existing lead is converted via student admission:
  - `UPDATE leads` now also sets `conversion_date = today` (from `now[:10]`)
- When direct admission creates a synthetic lead record:
  - `INSERT INTO leads` now includes `conversion_date` (today) and `branch_id` (student's branch)
- No second synthetic-lead path introduced — existing auto-create block enriched only.

### Safety guarantees kept
- No schema changes.
- No route URL changes.
- `students.lead_id` linking behavior preserved.
- Billing conversion flow behavior preserved.

### Validation
- No editor errors in modified files.
- `syntax_ok: billing`, `syntax_ok: leads`.
- App initialization passed (`app_init_ok`).

---
## Phase 11H - Update Dashboard Action Cards
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/dashboard.html`

### Route updates
- `converted_this_month` now uses `COALESCE(conversion_date, updated_at)` for accuracy.
- Added 3 new CRM action counts (role-aware, respects assigned_filter_sql):
  - `parent_pending_count` — active leads with `parent_discussion_status = 'Pending'`
  - `visit_scheduled_count` — active leads with `visit_status = 'Visit Scheduled'`
  - `visited_not_converted_count` — leads visited/demo-attended but not converted
- All 3 passed to template.

### UI updates
- New **CRM Action Cards Row** added below existing priority cards:
  - Parent Discussion Pending (warning/orange) → links to filtered list
  - Visit Scheduled (info/blue) → links to filtered list
  - Visited, Not Converted (primary/blue) → links to filtered list
  - Lost This Month (danger/red) → links to filtered list
- All cards are clickable links.

### Validation
- No editor errors in modified files.
- Dashboard template compile passed (`dashboard_template_ok`).
- App initialization passed (`app_init_ok`).

---
## Phase 11I - Update Leads List Filters
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/leads_list.html`

### Route updates
- Added 4 new filter params: `branch_id`, `parent_discussion_status`, `visit_status`, `lost_reason`
- All filters applied to SQL query (branch restricted to admin only)
- `lost_reason_options` — distinct values from DB for dynamic dropdown
- `branch_options` — loaded via `_load_active_branches()` for admin only
- `PARENT_DISCUSSION_STATUS_OPTIONS` + `VISIT_STATUS_OPTIONS` constants passed to template

### UI updates
- Filter active badge `!` and collapse `show` state updated for new params
- Clear button condition updated
- New **CRM Filters Row** added inside collapsible panel:
  - Branch (admin only)
  - Parent Discussion Status dropdown
  - Visit Status dropdown
  - Lost Reason dropdown (shown only if data exists)
- **Mobile card**: Parent Pending + Visit Status badges added under stage/temp
- **Desktop table**: secondary badges under lead name (no extra columns)

### Validation
- No editor errors in modified files.
- Leads list template compile passed (`leads_list_template_ok`).
- App initialization passed (`app_init_ok`).

---
## Phase 11J - Update Follow-up Page Priority
Date: 2026-05-08
Status: Completed

### Files changed
- `templates/leads/followups.html`

### Route updates
- No route changes needed — existing query uses `l.*` so `parent_discussion_status` and `visit_status` are already available via `enrich_lead_for_crm`.

### UI updates
- **Desktop table** — lead name cell now shows priority badges below name:
  - Parent Pending (warning/orange)
  - Visit Scheduled (info/teal)
  - Visited (primary/blue)
  - Demo Attended (success/green)
- **Mobile card** — same 4 badges added alongside stage/temperature badges
- Badge display rules: only shown when status is relevant (e.g. `Not Visited` shows nothing)

### Safety guarantees kept
- No route URL changes.
- No schema changes.
- Staff/admin access restrictions preserved.

### Validation
- No editor errors in modified file.
- Followups template compile passed (`followups_template_ok`).
- App initialization passed (`app_init_ok`).

---
Next planned phase: Phase 11K - Update Reports
---
## Phase 11K - Update Reports
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/leads/routes.py`
- `templates/leads/reports.html`

### Route updates
- Monthly conversion trend now uses `COALESCE(conversion_date, updated_at)` instead of `updated_at` — accurate with Phase 11G field.
- Added 3 new report queries (respecting existing date/user filters):
  - **Branch-wise report**: total/converted/lost/rate per branch (Unassigned for null)
  - **Parent Discussion report**: count + converted count per `parent_discussion_status` value
  - **Visit Conversion report**: count + converted count + conversion % per `visit_status` value
- All 3 passed to template.

### UI updates
- 3 new report sections added after existing Lost Reason / Monthly Trend row:
  - **Branch-wise Lead Report** — table with Branch, Total, Converted, Lost, Conv %
  - **Parent Discussion Report** — table with Status, Count, Converted
  - **Visit Conversion Report** — table with Visit Status, Count, Converted, Conv %

### Safety guarantees kept
- Existing report sections (User Performance, Source, Course, Lost Reason, Monthly Trend) preserved.
- No schema changes.
- No route URL changes.
- Admin-only access policy preserved.

### Validation
- No editor errors in modified files.
- Reports template compile passed (`reports_template_ok`).
- App initialization passed (`app_init_ok`).

---
## Phase 11L - Update Pipeline Cards
Date: 2026-05-08
Status: Completed

### Files changed
- `templates/leads/pipeline.html`

### Changes
- No route changes needed — `enrich_lead_for_crm` already passes `parent_discussion_status` and `visit_status` fields.
- Added 4 CSS badge styles: `crm-badge-parent`, `crm-badge-visit`, `crm-badge-visited`, `crm-badge-demo`.
- Each card now shows **Parent** and **Visit** status meta lines (replacing Score line).
- Conditional CRM priority badges added to the badge row:
  - **Parent Pending** (yellow) — `parent_discussion_status == 'Pending'`
  - **Visit Scheduled** (blue) — `visit_status == 'Visit Scheduled'`
  - **Demo Attended** (purple) — `visit_status == 'Demo Attended'`
  - **Visited** (green) — `visit_status` in `('Visited', 'Visited - Not Converted')`

### Validation
- No editor errors.
- Template compile passed (`pipeline_template_ok`).
- App initialization passed (`app_init_ok`).

---
## Phase 11M - Activity Logging
Date: 2026-05-08
Status: Completed

### Files changed
- `modules/billing/routes.py`

### Changes
- `lead_edit` already logged `parent_discussion_status`, `visit_status`, and `branch_id` changes — no changes needed.
- `lead_mark_lost` already logged lost reason — no changes needed.
- **Added**: `log_activity` call in billing student creation route after `form_lead_id` conversion, logging `action_type="lead_converted"` with description `"Lead converted on {date} - Student: {name} (Reg No: {reg})"`.

### Full logging coverage after 11M
| Event | Where | Action type |
|---|---|---|
| parent_discussion_status changed | lead_edit | lead_field_updated |
| visit_status changed | lead_edit | lead_field_updated |
| branch changed | lead_edit | lead_field_updated |
| Lead marked lost + reason | lead_mark_lost | lead_lost |
| conversion_date set | billing student create | lead_converted |

### Validation
- No editor errors.
- App initialization passed (`app_init_ok`).

---
Next planned phase: Phase 11N - Final Test Plan

---
## Phase 11N - Final Test Plan
Date: 2026-05-08
Status: Completed

### Automated Checks Run

**Schema — all 5 CRM columns present:**
- branch_id: OK
- conversion_date: OK
- lost_reason: OK
- parent_discussion_status: OK
- visit_status: OK

**Data integrity:**
- Converted leads with conversion_date set: 83 / 83 (0 missing)
- Lost leads with lost_reason set: 25 / 25 (0 missing)
- Active leads: 23 | Converted: 79 | Lost: 25

**Template compile — all 7 leads templates OK:**
- leads/dashboard.html
- leads/leads_list.html
- leads/lead_detail.html
- leads/lead_form.html
- leads/followups.html
- leads/pipeline.html
- leads/reports.html

**App initialization: OK**

### Manual Test Checklist (to verify in browser)
**Admin:**
- [ ] Add lead with branch, parent status, visit status
- [ ] Edit lead — check field change activity logs
- [ ] Mark lost with reason — check activity log
- [ ] Convert lead to student — check conversion_date set + activity log
- [ ] Check dashboard CRM action cards
- [ ] Check reports (branch-wise, parent discussion, visit conversion)
- [ ] Check pipeline — parent/visit badges on cards

**Staff:**
- [ ] Add assigned lead
- [ ] Edit own lead
- [ ] Confirm cannot access another staff's lead
- [ ] Add follow-up
- [ ] Update parent/visit status — verify activity logged
- [ ] Confirm only own leads appear in list/dashboard/followups

---
Next planned phase: Phase 11O - Production Deployment Checklist
