You are working on the Global IT Education ERP.

Goal:
Redesign the current Leads Module into a conversion-focused counseling CRM without breaking the current production system.

Current stack:
- Flask 2.3
- Jinja2 templates
- Bootstrap UI
- Vanilla JavaScript
- Raw sqlite3 via db.py
- SQLite database at instance/database.db
- Leads blueprint at /leads
- Main leads logic in modules/leads/routes.py
- Leads templates in templates/leads/

Important:
Do NOT rewrite the entire project.
Do NOT break existing routes.
Do NOT remove existing columns.
Do NOT change billing conversion flow immediately.
Work step by step with safe commits.

Business context:
Global IT Education is a local training institute. Leads come from walk-ins, referrals, website, Instagram, workshops, and counseling. The CRM must help staff follow up quickly, track parents/decision makers, identify hot leads, reduce missed follow-ups, and improve admissions conversion.

Current audit findings:
- Leads module already has leads, followups, stages, assigned counselor, score, pipeline, reports, and student conversion link.
- Current system uses raw sqlite3, not SQLAlchemy.
- Current route files are large, so new logic should be moved into helper/service files where possible.
- Authorization must be hardened before major CRM redesign.
- Staff should only access assigned leads unless admin.
- Dashboard should become an action center, not only a number display.

==================================================
REDESIGN PRINCIPLE
==================================================

The CRM should answer these questions every day:

1. Which lead should I call now?
2. Which follow-up is overdue?
3. Which lead is hot?
4. Which parent discussion is pending?
5. Which lead is likely to convert?
6. Which counselor is performing well?
7. Which source/course gives better conversion?
8. Why are leads getting lost?

Rule:
No lead should sleep without a next action.

==================================================
SAFE DEVELOPMENT RULES
==================================================

Before each phase:
1. Inspect existing routes, templates, and database schema.
2. Explain what files will be changed.
3. Make the smallest safe change.
4. Preserve old behavior.
5. Do not delete working code unless replaced safely.
6. After each change, mention how to test manually.

Use this order:
- First safety
- Then helper extraction
- Then database hardening
- Then UI improvement
- Then automation/reports

==================================================
PHASE 0 — SAFETY SETUP
==================================================

Task:
Prepare the project for safe CRM redesign.

Actions:
1. Create a new Git branch:
   leads-crm-redesign

2. Create database backup instruction:
   copy instance/database.db to instance/database_backup_before_crm_redesign.db

3. Do not edit production database directly without backup.

4. Create a simple CHANGELOG section or notes file:
   CRM_REDESIGN_PROGRESS.md

5. Every phase should be documented there.

Expected output:
- List of current lead routes
- List of current leads templates
- Current leads table schema
- Current followups table schema
- Current users table schema

Do not modify business logic in this phase.

==================================================
PHASE 1 — LEAD ACCESS SECURITY HARDENING
==================================================

Problem:
Staff may be able to access or update another counselor’s lead if they know the lead ID.

Goal:
Create one central lead access control helper.

Create or update helper file:
modules/leads/helpers.py

Add helper function:

can_access_lead(user_id, role, lead_assigned_to_id)

Rules:
- Admin can access all leads.
- Staff can access only assigned leads.
- If assigned_to_id is null, admin can access; staff should not access unless current logic already allows unassigned leads.
- Do not break existing admin behavior.

Also create:
get_lead_or_404_with_access(conn, lead_id, session)

Apply access check to:
- lead detail
- edit lead
- add followup
- stage change
- reassign
- delete
- restore
- mark lost
- AI assist

Do not redesign UI yet.

Manual test:
1. Login as admin and open any lead.
2. Login as staff and open assigned lead.
3. Login as staff and try another staff lead ID.
4. Staff should be blocked safely.

==================================================
PHASE 2 — DATABASE HARDENING WITHOUT BREAKING DATA
==================================================

Goal:
Improve performance and reporting safety without changing current workflows.

Add safe indexes only if they do not exist.

Suggested indexes:
- leads.assigned_to_id
- leads.status
- leads.stage
- leads.next_followup_date
- leads.created_at
- leads.is_deleted
- followups.lead_id
- followups.created_at
- activity_logs.module_name
- activity_logs.user_id
- activity_logs.created_at

Use CREATE INDEX IF NOT EXISTS.

Do not add NOT NULL constraints now.
Do not enforce unique phone now.
Do not restructure interested_courses now.

Manual test:
1. App starts without error.
2. Leads list loads.
3. Dashboard loads.
4. Follow-up page loads.
5. Reports load.

==================================================
PHASE 3 — EXTRACT LEAD BUSINESS LOGIC
==================================================

Problem:
Lead logic is currently inside routes.py.

Goal:
Move repeated logic into helper/service functions without changing behavior.

Create:
modules/leads/services.py

Move or create functions:

1. compute_lead_score(lead_data)
Use existing scoring logic first.
Do not introduce new scoring yet.

2. map_stage_to_status(stage)
Rules:
- Converted -> converted
- Lost -> lost
- All others -> active

3. get_next_stages(current_stage)
Preserve existing stage movement.

4. update_lead_stage(conn, lead_id, new_stage, user_id)
Should update stage/status safely and log activity.

5. log_lead_activity(conn, lead_id, user_id, action_type, description)
Use existing activity_logs if possible.
Do not create new activity table yet unless required.

Important:
Routes should call service functions.
Do not change UI.

Manual test:
- Create lead
- Edit lead
- Change stage
- Mark lost
- Convert lead flow should still work

==================================================
PHASE 4 — CREATE CRM-SPECIFIC HELPER LAYER
==================================================

Goal:
Add conversion-focused logic without breaking old pages.

Add these helper functions:

1. get_followup_status(next_followup_date)

Return:
- overdue
- today
- upcoming
- none

2. get_inactive_days(last_contact_date or updated_at)

Return number of days since last contact.

3. get_lead_temperature(score, followup_status, stage)

Rules:
- Converted = Converted
- Lost = Lost
- score >= 75 = Hot
- score >= 40 = Warm
- else Cold

4. get_next_action(lead)

Examples:
- New Lead -> Call and qualify
- Contacted -> Understand course interest
- Interested -> Schedule counseling
- Counseling Done -> Discuss fees/parents
- Follow-up -> Complete follow-up
- Overdue -> Call immediately

Do not save these to database initially.
Calculate and display first.

==================================================
PHASE 5 — DASHBOARD REDESIGN INTO ACTION CENTER
==================================================

Current dashboard shows numbers.
New dashboard must push action.

Modify:
templates/leads/dashboard.html
modules/leads/routes.py dashboard route

Add top section:
Today’s Action Center

Cards:
1. Overdue Follow-ups
2. Today Follow-ups
3. Hot Leads
4. New Leads Today
5. Inactive Leads
6. Converted This Month

Priority order:
- Overdue first
- Today follow-ups second
- Hot leads third
- New leads fourth

Add quick lists:
1. Top 5 overdue follow-ups
2. Top 5 hot leads
3. New leads not contacted

Each list item should show:
- Name
- Phone
- Course
- Owner
- Next follow-up date
- Quick buttons: Call, WhatsApp, Open

Do not remove existing metrics immediately.
Keep old metrics below or in secondary section.

Manual test:
- Admin sees all leads.
- Staff sees only assigned leads.
- Counts match filters.

==================================================
PHASE 6 — LEADS LIST REDESIGN
==================================================

Goal:
Make leads list faster for counseling work.

Modify:
templates/leads/leads_list.html
/leads/list route if needed

Add filters:
- Search name/phone
- My Leads
- Stage
- Priority/Temperature
- Course
- Source
- Today Follow-up
- Overdue
- Converted
- Lost

Table columns:
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

Actions:
- Call
- WhatsApp
- Add Follow-up
- Open

Important:
Keep existing search and filters working.
Do not remove current filters until new filters are tested.

UI rule:
Use Bootstrap badges:
- Hot = danger
- Warm = warning
- Cold = primary
- Converted = success
- Lost = secondary
- Overdue = danger
- Today = warning

Manual test:
- Search works.
- Stage filter works.
- Staff only sees assigned leads.
- Quick action links work.

==================================================
PHASE 7 — LEAD VIEW PAGE REDESIGN
==================================================

This is the most important CRM screen.

Modify:
templates/leads/lead_detail.html

Top summary card should show:
- Name
- Phone
- WhatsApp
- Course
- Stage
- Temperature
- Score
- Owner
- Last contacted
- Next follow-up
- Next action

Primary action buttons:
- Call
- WhatsApp
- Add Follow-up
- Convert to Student
- Mark Lost
- Edit

Layout:
Left column:
- Lead profile
- Education
- Course interest
- Source
- Parent/decision maker
- Notes

Right column:
- Quick follow-up form
- Next action
- AI assist if existing
- Important alerts

Bottom:
- Timeline

Timeline should combine:
- followups
- activity_logs where module_name = leads

Do not create a new activity table in this phase unless absolutely needed.
Use existing followups and activity_logs first.

Manual test:
- Open existing lead.
- Add follow-up.
- Timeline updates.
- Convert button still goes to billing admission flow.
- Mark lost still works.

==================================================
PHASE 8 — FOLLOW-UP PAGE REDESIGN
==================================================

Goal:
Make this the staff daily calling screen.

Modify:
templates/leads/followups.html
/leads/followups route

Add tabs:
- Overdue
- Today
- Tomorrow
- Upcoming
- Completed

Each row/card:
- Lead name
- Phone
- Course
- Stage
- Temperature
- Counselor
- Due date
- Last note
- Actions

Actions:
- Call
- WhatsApp
- Complete
- Reschedule
- Open

Add quick complete modal:
Fields:
- Outcome
- Notes
- Next follow-up date
- Next action

Outcomes:
- Interested
- Call Later
- No Response
- Parent Discussion Pending
- Fees Concern
- Visited
- Not Interested
- Converted

Important:
Completing follow-up should:
- Insert followup record or update existing depending on current structure
- Update lead.last_contact_date
- Update lead.next_followup_date
- Increment followup count if current logic does this
- Log activity

Manual test:
- Overdue count correct.
- Today count correct.
- Staff sees assigned followups only.
- Complete modal updates lead correctly.

==================================================
PHASE 9 — PIPELINE REDESIGN INTO KANBAN
==================================================

Goal:
Make pipeline visually useful.

Modify:
templates/leads/pipeline.html
/leads/pipeline route

Columns:
- New Lead
- Contacted
- Interested
- Counseling Done
- Follow-up
- Converted
- Lost

Each card:
- Name
- Phone
- Course
- Score
- Temperature
- Owner
- Next follow-up
- Follow-up status

Card border:
- Red = overdue
- Orange = today
- Green = converted
- Gray = lost

Initial version:
Use buttons to move to next stage.
Do not implement drag-and-drop first.

Later version:
Add drag-and-drop only after stage update route is stable.

Manual test:
- Admin sees all pipeline.
- Staff sees assigned pipeline.
- Stage move works.
- Converted and lost stay terminal.

==================================================
PHASE 10 — REPORTS REDESIGN
==================================================

Goal:
Make reports useful for business decisions.

Modify:
templates/leads/reports.html
/leads/reports route

Reports needed:
1. Counselor performance
2. Lead source conversion
3. Course-wise conversion
4. Follow-up completion rate
5. Lost reason report
6. Monthly conversion trend

Metrics:
- Total leads
- Active leads
- Converted leads
- Lost leads
- Conversion rate
- Follow-up completion rate
- Hot lead conversion rate
- Average days to conversion if possible

Important:
Do not make report queries too heavy.
Use indexes added in Phase 2.
Keep date filters.

Manual test:
- Filter by date range.
- Filter by user.
- Conversion rate correct.
- Staff access should follow existing permission policy.

PHASE 11 — DATABASE ENRICHMENT + CRM FIELD INTEGRATION
==================================================

Purpose:
Add important CRM fields to the leads system and make them useful in forms, detail pages, dashboard, reports, and conversion tracking.

Important:
Do NOT only add columns.
Every new column must be connected to:
1. Database
2. Add/Edit form
3. Route logic
4. Lead detail page
5. Dashboard/report where useful
6. Manual testing

Current audit context:
- Leads table exists.
- Followups table exists.
- students.lead_id is used for conversion connection.
- Conversion is mainly handled in billing route, not inside leads module.
- Leads currently do not have branch_id.
- Current CRM should be improved without breaking production.

==================================================
PHASE 11A — PRE-MIGRATION SAFETY
==================================================

Goal:
Prepare safely before touching the database.

Tasks:
1. Create database backup:
   instance/database_backup_before_phase_11.db

2. Create Git commit before Phase 11:
   "Before Phase 11 CRM database enrichment"

3. Inspect current schema:
   - leads table
   - followups table
   - students table
   - users table
   - branches table

4. Confirm whether these columns already exist:
   - branch_id
   - conversion_date
   - lost_reason
   - parent_discussion_status
   - visit_status

5. Do not add duplicate columns.

Expected output:
- Show current leads table schema.
- Show which columns are missing.
- Suggest only missing ALTER TABLE statements.

Manual test:
- App should run before migration.
- Leads list should open.
- Lead detail should open.

==================================================
PHASE 11B — ADD COLUMNS SAFELY
==================================================

Goal:
Add only missing columns using safe migration logic.

Suggested columns:

ALTER TABLE leads ADD COLUMN branch_id INTEGER;
ALTER TABLE leads ADD COLUMN conversion_date TEXT;
ALTER TABLE leads ADD COLUMN parent_discussion_status TEXT DEFAULT 'Pending';
ALTER TABLE leads ADD COLUMN visit_status TEXT DEFAULT 'Not Visited';

Current-system note:
- `lost_reason` already exists in current `leads` schema.
- Do NOT add duplicate `lost_reason` column.
- Keep `lost_reason` in "columns to confirm" list, but skip ALTER if present.

Important:
Use add_column_if_not_exists if project already has this helper.
If not, first check PRAGMA table_info(leads).

Implementation location for this project:
- Put safe column-add logic in `db.py` inside `init_db()` using `add_column_if_not_exists(...)`.
- Avoid separate ad-hoc migration scripts unless absolutely required.

Do not add NOT NULL constraints.
Do not add foreign key constraint immediately.
Do not change old data destructively.

Optional index additions:

CREATE INDEX IF NOT EXISTS idx_leads_branch_id ON leads(branch_id);
CREATE INDEX IF NOT EXISTS idx_leads_conversion_date ON leads(conversion_date);
CREATE INDEX IF NOT EXISTS idx_leads_lost_reason ON leads(lost_reason);
CREATE INDEX IF NOT EXISTS idx_leads_parent_discussion_status ON leads(parent_discussion_status);
CREATE INDEX IF NOT EXISTS idx_leads_visit_status ON leads(visit_status);

Manual test:
- App starts.
- Leads dashboard loads.
- Leads list loads.
- Add lead page loads.
- Existing lead detail loads.

==================================================
PHASE 11C — BACKFILL EXISTING DATA
==================================================

Goal:
Fill useful default values for old leads.

Rules:

1. branch_id
If lead has assigned_to_id and assigned user has branch_id:
- Update leads.branch_id = users.branch_id

SQL idea:
UPDATE leads
SET branch_id = (
    SELECT branch_id FROM users WHERE users.id = leads.assigned_to_id
)
WHERE branch_id IS NULL
AND assigned_to_id IS NOT NULL;

2. conversion_date
For old converted leads:
- If stage = Converted or status = converted
- Use updated_at if available
- Else use created_at
- Else keep null

Important data quality note:
- This is an approximate historical backfill for legacy rows.
- `updated_at` may not always equal true conversion time.
- For all future conversions, always set `conversion_date` explicitly at conversion time.

3. lost_reason
Do not guess old lost reasons.
Keep null unless already available somewhere.

4. parent_discussion_status
Set default:
- Pending

5. visit_status
Set default:
- Not Visited

Manual test:
- Check old converted leads.
- Check old assigned leads have branch_id where possible.
- No old leads should disappear.

==================================================
PHASE 11D — UPDATE ADD LEAD / EDIT LEAD FORM
==================================================

Files likely involved:
- templates/leads/lead_form.html
- modules/leads/routes.py

Goal:
Allow staff/admin to capture new CRM fields.

Add fields:

1. Branch
Visible mainly for admin.
For staff, default to current user branch if available.

Staff branch behavior (must be explicit):
- If staff has `users.branch_id`, auto-fill and lock branch to that value.
- If staff has no branch_id, allow save with NULL branch_id (do not block lead creation).
- If user can view all branches/admin, allow selecting from branch dropdown.

Options:
- Pull from branches table.
- Show active branches only.

2. Parent Discussion Status
Dropdown:
- Pending
- Not Required
- Scheduled
- Completed
- Parent Not Responding
- Parent Rejected

3. Visit Status
Dropdown:
- Not Visited
- Visit Scheduled
- Visited
- Demo Attended
- Not Interested After Visit

Do NOT show conversion_date in add/edit form.
Do NOT show lost_reason in normal add/edit form unless already lost.
Lost reason should be handled in Mark Lost flow.

Route logic:
- On create lead:
  - Save branch_id
  - Save parent_discussion_status
  - Save visit_status
- On edit lead:
  - Update these fields safely
  - Log activity if changed

Manual test:
1. Add new lead with branch, parent status, visit status.
2. Edit existing lead and update parent status.
3. Edit existing lead and update visit status.
4. Reopen lead and verify values are saved.

==================================================
PHASE 11E — UPDATE LEAD DETAIL PAGE
==================================================

File:
- templates/leads/lead_detail.html

Goal:
Make these fields visible and useful.

Add CRM information section:

Show:
- Branch
- Parent Discussion Status
- Visit Status
- Lost Reason if lead is lost
- Conversion Date if lead is converted

Also show alerts:

If parent_discussion_status = Pending:
Show warning:
"Parent discussion pending"

If visit_status = Visited and stage is not Converted:
Show warning:
"Visited but not converted yet"

If visit_status = Visit Scheduled:
Show info:
"Visit scheduled — follow up after visit"

If lead is Lost:
Show lost reason prominently.

Manual test:
- Open normal lead.
- Open converted lead.
- Open lost lead.
- Open lead with parent discussion pending.
- Open visited lead.

==================================================
PHASE 11F — UPDATE MARK LOST FLOW
==================================================

Files likely:
- modules/leads/routes.py
- templates/leads/lead_detail.html
- maybe modal/form inside lead detail

Goal:
Lost reason must be captured properly.

Lost reason dropdown:
- Fees High
- Joined Other Institute
- Parent Rejected
- No Response
- Course Not Required
- Timing Issue
- Location Issue
- Not Eligible
- Duplicate Lead
- Other

Also allow optional note.

Route behavior:
When marking lost:
- stage = Lost
- status = lost
- lost_reason = selected reason
- updated_at = current timestamp
- log activity

Important:
Do not allow empty lost_reason when marking lost.

Manual test:
1. Mark lead as lost.
2. Select reason.
3. Save.
4. Lead detail shows lost reason.
5. Reports can count lost reason.

==================================================
PHASE 11G — UPDATE CONVERSION FLOW
==================================================

Important:
Audit says actual student conversion is handled mainly in billing, not leads.

Files likely:
- modules/billing/routes.py
- templates/leads/lead_detail.html
- maybe student registration/admission route

Goal:
When lead converts to student, save conversion_date.

Route behavior:
When student is created from lead:
- leads.stage = Converted
- leads.status = converted
- leads.conversion_date = today/current date
- leads.updated_at = current timestamp
- students.lead_id should remain connected

Current-system flow note:
- Billing already creates a synthetic converted lead when student admission has no lead_id.
- Do NOT introduce a second synthetic-lead path.
- Update existing billing synthetic-lead insert only to include:
   - conversion_date = admission/joined date or today
   - branch_id = student branch_id if available
- Keep existing `students.lead_id` linking behavior.

Manual test:
1. Convert lead to student.
2. Check lead stage = Converted.
3. Check conversion_date is saved.
4. Check student.lead_id is connected.
5. Direct student admission still works.

==================================================
PHASE 11H — UPDATE DASHBOARD ACTION CARDS
==================================================

Files:
- modules/leads/routes.py
- templates/leads/dashboard.html

Goal:
Use new fields for better counseling actions.

Add cards:

1. Parent Discussion Pending
Count leads where:
- parent_discussion_status = Pending
- status = active
- is_deleted = 0

2. Visit Scheduled
Count:
- visit_status = Visit Scheduled
- status = active

3. Visited Not Converted
Count:
- visit_status IN ('Visited', 'Demo Attended')
- status != converted

4. Lost This Month
Count:
- status = lost
- updated_at/current lost date within month

5. Converted This Month
Use conversion_date, not only updated_at.

Manual test:
- Dashboard counts load.
- Admin sees all.
- Staff sees assigned leads only.

==================================================
PHASE 11I — UPDATE LEADS LIST FILTERS
==================================================

Files:
- modules/leads/routes.py
- templates/leads/leads_list.html

Add filters:

1. Branch
Admin only or users with all-branch permission.

2. Parent Discussion Status

3. Visit Status

4. Lost Reason

5. Converted Date Range

Add columns/badges:
- Branch
- Parent Status
- Visit Status

Do not overload table.
If table becomes too wide, show these in secondary text below lead name.

Manual test:
- Filter by branch.
- Filter parent discussion pending.
- Filter visited leads.
- Filter lost reason.
- Staff restriction still works.

==================================================
PHASE 11J — UPDATE FOLLOW-UP PAGE PRIORITY
==================================================

Files:
- modules/leads/routes.py
- templates/leads/followups.html

Goal:
Use new fields to prioritize follow-ups.

Priority examples:
1. Parent discussion pending + overdue = high priority
2. Visit scheduled today/tomorrow = high priority
3. Visited but not converted = high priority
4. Fees concern/lost risk = high priority

Display badges:
- Parent Pending
- Visit Scheduled
- Visited
- Demo Attended

Manual test:
- Follow-up page loads.
- Badges show correctly.
- Staff sees only assigned follow-ups.

==================================================
PHASE 11K — UPDATE REPORTS
==================================================

Files:
- modules/leads/routes.py
- templates/leads/reports.html

Add reports:

1. Branch-wise Lead Report
Columns:
- Branch
- Total Leads
- Converted
- Lost
- Conversion %

2. Lost Reason Report
Columns:
- Lost Reason
- Count
- Percentage

3. Parent Discussion Report
Columns:
- Pending
- Scheduled
- Completed
- Rejected

4. Visit Conversion Report
Columns:
- Not Visited
- Visit Scheduled
- Visited
- Demo Attended
- Converted from visited

5. Monthly Conversion Report
Use conversion_date.

Important:
Conversion reports should use conversion_date, not updated_at.

Manual test:
- Reports load.
- Date filter works.
- Branch filter works if added.
- Lost reason counts are correct.

==================================================
PHASE 11L — UPDATE PIPELINE CARDS
==================================================

Files:
- templates/leads/pipeline.html
- modules/leads/routes.py

Goal:
Make pipeline cards more counseling-focused.

Each card should show:
- Name
- Course
- Stage
- Temperature
- Parent Status
- Visit Status
- Next Follow-up
- Owner

Badges:
- Parent Pending
- Visit Scheduled
- Visited
- Demo Attended

Manual test:
- Pipeline loads.
- Stage movement works.
- New badges do not break layout.

==================================================
PHASE 11M — ACTIVITY LOGGING
==================================================

Goal:
Every important CRM field change should be traceable.

Log activity when:
- parent_discussion_status changes
- visit_status changes
- lost_reason added
- conversion_date set
- branch changed

Example descriptions:
- Parent discussion status changed from Pending to Completed
- Visit status changed from Not Visited to Visited
- Lead marked lost due to Fees High
- Lead converted on 2026-05-08

Manual test:
- Change parent status.
- Check activity log/timeline.
- Mark lost.
- Check activity log.

==================================================
PHASE 11N — FINAL TEST PLAN
==================================================

Test as Admin:
1. Add lead with branch, parent status, visit status.
2. Edit lead.
3. Mark lost with reason.
4. Convert lead to student.
5. Check dashboard.
6. Check reports.
7. Check pipeline.

Test as Staff:
1. Add assigned lead.
2. Edit own lead.
3. Try another staff lead ID.
4. Add follow-up.
5. Update parent status.
6. Update visit status.
7. Check only own dashboard/list/followups.

Database test:
Run:
PRAGMA table_info(leads);

Check columns exist:
- branch_id
- conversion_date
- lost_reason
- parent_discussion_status
- visit_status

Check sample data:
SELECT id, name, branch_id, conversion_date, lost_reason, parent_discussion_status, visit_status
FROM leads
ORDER BY id DESC
LIMIT 10;

==================================================
PHASE 11O — PRODUCTION DEPLOYMENT CHECKLIST
==================================================

Before production:
1. Backup database.
2. Commit code.
3. Apply migration locally first.
4. Test with old data.
5. Push to GitHub.
6. Pull on PythonAnywhere.
7. Reload web app.
8. Check error logs.
9. Test admin login.
10. Test staff login.
11. Test lead creation.
12. Test conversion.
13. Test reports.

Rollback plan:
- Keep previous database backup.
- Keep previous Git commit hash.
- If issue happens, revert code and restore backup.

==================================================
PHASE 12 — FINAL CRM POLISH
==================================================

Add:
- Empty states
- Better mobile cards
- Consistent badges
- Reusable Jinja macros
- Better button hierarchy
- Reduced inline CSS
- Shared lead UI components

Possible reusable template:
templates/leads/components/_lead_badges.html
templates/leads/components/_lead_card.html
templates/leads/components/_kpi_card.html
templates/leads/components/_timeline_item.html

==================================================
EXPECTED FINAL OUTCOME
==================================================

The final Leads Module should behave like a counseling CRM:

Admin should see:
- Team performance
- Overdue follow-ups
- Lead source conversion
- Course conversion
- Counselor conversion
- Lost reasons

Staff should see:
- My follow-ups today
- My overdue leads
- My hot leads
- My next actions
- Easy call/WhatsApp buttons
- Simple follow-up completion

Every lead should clearly show:
- Stage
- Temperature
- Last contact
- Next follow-up
- Next action
- Owner
- Timeline

Most important rule:
Do not break current production.
Improve one safe layer at a time.