# Global IT Education ERP

# UI/UX Design System & Frontend Engineering Rule Book

Version: 1.0
Owner: Global IT Education
Technology Stack: Flask + Jinja2 + Bootstrap 5 + SQLite

---

# 1. Vision

The Global IT Education ERP must feel like a modern, professional Education Management System.

The application should combine:

* Professional ERP structure
* Student-friendly experience
* Clean and modern design
* Fast workflows
* Mobile responsiveness
* Long-term scalability

Design inspiration:

* Zoho CRM
* Odoo
* Freshworks
* Notion
* Google Workspace

The ERP should NEVER feel like:

* A college project
* A Bootstrap demo
* A collection of unrelated pages
* A developer-only admin panel

---

# 2. Brand Identity

Global IT Education represents:

* Education
* Career Growth
* Skill Development
* Trust
* Technology
* Opportunity

The UI should communicate:

* Professionalism
* Simplicity
* Confidence
* Growth

---

# 3. Official Color System

## Primary Colors

Primary Blue: #2563eb
Growth Green: #16a34a

## Layout Colors

Sidebar Background: #0f172a
Sidebar Border: #1e293b
Sidebar Text: #94a3b8

Page Background: #f8fafc
Card Background: #ffffff

Primary Text: #1e293b
Secondary Text: #64748b

## Status Colors

Success: #16a34a
Warning: #f59e0b
Danger: #ef4444
Info: #3b82f6

---

# 4. Navigation Architecture

Use business language.

Never expose technical names.

Wrong:

* Leads Module
* Billing Module
* Attendance Module

Correct:

* Admissions
* Students
* LMS
* Finance
* Reports
* Administration

---

# 5. Sidebar Structure

Dashboard

Admissions

* Leads
* Add Lead
* Follow-ups
* Pipeline

Students

* Student List
* Registration
* Attendance
* Certificates

LMS

* Courses
* Chapters
* Topics
* Progress

Finance

* Invoices
* Payments
* Receipts
* Expenses
* Installments

Reports

* Lead Reports
* Student Reports
* Finance Reports
* Analytics

Administration

* Users
* Branches
* Company Profile
* Settings

---

# 6. Sidebar Rules

Only one sidebar exists across the entire application.

Requirements:

* Accordion style
* Active page highlighting
* Active section auto-expand
* Collapsible mode
* Mobile offcanvas mode
* Bootstrap Icons
* Smooth animations

Never create separate sidebars for modules.

---

# 7. Responsive Design Rules

Mobile First Development.

## Mobile

Less than 576px

* Sidebar becomes offcanvas
* Single column layout
* Tables scroll horizontally
* Forms stack vertically

## Tablet

576px - 991px

* Sidebar hidden by default
* Offcanvas navigation
* Two-column cards where appropriate

## Desktop

992px+

* Sidebar always visible
* Collapsible sidebar supported
* Multi-column dashboards

---

# 8. Typography Rules

Use:

Font Family:

* Inter
* System UI
* Segoe UI

H1:
2rem
Weight 700

H2:
1.5rem
Weight 600

Body:
0.95rem

Small Text:
0.85rem

Never use random font sizes.

Use rem units only.

Never use px for typography.

---

# 9. Card Design Rules

All cards must:

* Border radius: 12px
* Soft shadow
* White background
* Consistent padding

Example usage:

Dashboard Cards
Student Cards
Reports
Widgets

All cards should look visually consistent.

---

# 10. Button Standards

Primary Actions

* Blue button

Examples:

* Save
* Submit
* Create
* Register

Success Actions

* Green button

Examples:

* Mark Paid
* Complete

Danger Actions

* Red button

Examples:

* Delete
* Cancel Admission

Never use random button colors.

---

# 11. Form Standards

Use Bootstrap form controls.

Requirements:

* Proper labels
* Required field indicators
* Validation messages
* Mobile-friendly layout

Example:

Name
Phone
Email
Course

Forms should feel simple and fast.

---

# 12. Table Standards

All tables must use:

.table-responsive

Example:

Student List
Invoice List
Lead List

Requirements:

* Horizontal scroll on mobile
* Sticky header when appropriate
* Hover states
* Proper spacing

Never allow tables to break mobile layouts.

---

# 13. Dashboard Standards

Every dashboard should answer:

What happened?
What needs attention?
What should I do next?

Dashboard cards should prioritize:

1. Revenue
2. Students
3. Leads
4. Follow-ups
5. Due Payments

Important information must be visible without scrolling.

---

# 14. Notification Standards

Use badges for:

* Follow-ups
* Pending Payments
* Unread Notifications
* Tasks

Examples:

Follow-ups (12)

Pending Fees (8)

---

# 15. Accessibility Standards

Minimum touch target:

44px

Requirements:

* Keyboard accessible
* Good contrast ratio
* Clear focus states
* Readable text

Never rely only on color to convey information.

---

# 16. CSS Engineering Rules

STRICT RULES

Do not use inline CSS.

Wrong:

<div style="margin-top:20px">

Correct:

<div class="page-header">

All styling must live in:

static/css/style.css

or component CSS files.

---

# 17. HTML Rules

Use semantic HTML.

Prefer:

header
nav
main
section
article
footer

Avoid excessive div nesting.

Keep markup clean.

---

# 18. Bootstrap Standards

Use Bootstrap 5 utilities.

Avoid custom CSS when Bootstrap already provides the solution.

Examples:

Use:

* row
* col
* gap
* d-flex
* align-items-center

Before creating custom CSS.

---

# 19. Jinja2 Standards

Use:

Base Template
Reusable Components
Template Inheritance

Avoid duplicated HTML.

Create reusable:

* Sidebar
* Navbar
* Flash Messages
* Dashboard Cards

---

# 20. Code Quality Standards

Every new page must be:

* Responsive
* Consistent
* Reusable
* Accessible
* Maintainable

Before implementation ask:

1. Does it follow the design system?
2. Is it mobile friendly?
3. Is it consistent?
4. Can it be reused?
5. Is there a simpler solution?

---

# 21. Final Rule

When multiple design options exist:

Choose the option that provides:

* Better user experience
* Better maintainability
* Better responsiveness
* Better consistency

over the option that simply requires fewer lines of code.

The Global IT Education ERP must be built to commercial software standards, not tutorial-project standards.
