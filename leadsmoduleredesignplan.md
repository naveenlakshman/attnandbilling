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

==================================================
PHASE 11 — OPTIONAL DATABASE ENRICHMENT
==================================================

Only after UI and current flow are stable.

Consider adding columns safely:

ALTER TABLE leads ADD COLUMN branch_id INTEGER;
ALTER TABLE leads ADD COLUMN conversion_date TEXT;
ALTER TABLE leads ADD COLUMN lost_reason TEXT;
ALTER TABLE leads ADD COLUMN parent_discussion_status TEXT DEFAULT 'Pending';
ALTER TABLE leads ADD COLUMN visit_status TEXT DEFAULT 'Not Visited';

Do this only with:
- migration backup
- backfill plan
- UI support
- test plan

Do not add all columns blindly.

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