# LMS Admin Mobile Optimization Plan

## Summary

The LMS Admin pages were not optimized for mobile because the shared shell in `templates/lms_admin/base.html` used a permanent 260px sticky sidebar inside a horizontal flex layout. On 360px to 412px screens, that left too little width for the main content and caused clipped dashboards or body-level horizontal scrolling.

This plan covers the shared responsive foundation plus page-specific areas that need extra attention. Desktop layout should remain mostly unchanged.

Route labels used in the audit:

- Progress: `/lms_admin/progress-dashboard`
- Master Library: `/lms_admin/master/chapters`
- Assignments: `/lms_admin/master/assignments`
- Batch Access: `/lms_admin/batch-programs`
- Phase 6 Rollout: `/lms_admin/phase6/rollout`
- Student Demo View: `/lms_admin/demo/launch`, which redirects to the student portal

## Shared Layout Changes

High priority:

- Convert the fixed desktop sidebar into a mobile off-canvas drawer below 768px.
- Add a topbar menu button, backdrop, Escape-key close behavior, and auto-close after navigation.
- Ensure `body`, `.content-wrap`, flash messages, and `.content-area` do not create body-level horizontal scrolling.
- Reduce mobile content padding to about 12px to 16px while preserving desktop spacing.
- Make the topbar title truncate safely and hide the user label on very small screens.
- Add shared responsive utilities: `.mobile-stack`, `.mobile-full`, `.responsive-table-wrap`, `.action-group`, and `.mobile-card-grid`.

Medium priority:

- Standardize repeated page header, filter, action, and card patterns at mobile breakpoints.
- Keep management tables horizontally scrollable inside their local card or wrapper when table-to-card conversion is not practical.
- Set important mobile tap targets to at least 44px high.
- Keep desktop table and sidebar behavior unchanged.

## Page-by-Page Audit

| Area / Actual Route | Priority | Current Mobile Issue | Root Cause | Recommended Solution |
|---|---:|---|---|---|
| Dashboard `/lms_admin/dashboard` | High | Main content clipped; recent activity can overflow. | Sidebar consumes mobile width; activity table has no dedicated scroll behavior. | Shared drawer shell and local table overflow handling. |
| Progress `/lms_admin/progress-dashboard` | High | Dense filters, KPI cards, accordions, and 12-column detail table. | Many nowrap headers, min-width progress bars, small controls. | Stack filters/cards; keep tables in contained horizontal scroll. |
| Programs `/lms_admin/programs` | High | Active/deleted program tables can push body width. | Custom table cards used `overflow:hidden` and fixed action widths. | Use scrollable table containers on mobile; stack action buttons. |
| Program detail `/program/<id>/view` | Medium | Header actions and modal controls crowd on phones. | Hero/header and modal are desktop-biased. | Stack actions; reduce hero padding; single-column metrics on small screens. |
| Program create/edit `/program/new`, `/program/<id>/edit` | Medium | Form is mostly responsive but padding/buttons need phone sizing. | Local CSS collapses rows, but not all touch spacing. | Reduce card padding and make actions full width on mobile. |
| Master Library `/master/chapters` | High | Header action and fixed action column can overflow. | Header and table are desktop-first. | Wrap header and preserve local table scrolling. |
| Master topics `/master/chapter/<id>/topics` | High | 420px action column and reorder controls are too wide. | Fixed table columns and many inline buttons. | Scroll table locally; stack order/actions on mobile. |
| Master topic contents `/master/topic/<id>/contents` | Medium | Slot and navigation action buttons can crowd. | Flex groups wrap but remain compact. | Stack action groups below 576px. |
| Assignments `/master/assignments` | High | Assignment table had no responsive wrapper; filters used fixed min-widths. | Table lived directly inside card body. | Add `.table-responsive`; full-width filters/actions on phones. |
| Assignment submissions `/master/assignments/<id>/submissions` | Medium | Submission card headers crowd file/download/preview actions. | Two flex clusters and nowrap filename chips. | Stack card header controls and full-width buttons below 576px. |
| Assignment preview | Low | Iframe min-height is too tall on small phones. | Fixed `80vh` and `min-height:560px`. | Lower mobile min-height and stack actions. |
| Batch Access `/batch-programs` | High | Custom assignment table can overflow the page. | Fixed table columns inside custom layout. | Constrain overflow to table area; stack header actions. |
| Batch create/edit | Medium | Form layout collapses, but header/actions still crowd. | Local CSS only partly handles actions. | Full-width cancel/submit/reset buttons on phones. |
| Bulk assign `/batch-program/bulk-assign` | High | Date grid and actions stay inline. | Inline two-column style and no action hook. | Force one-column date grid and stack submit/cancel buttons. |
| Phase 6 rollout `/phase6/rollout` | Medium | Header/card metadata and migrate footer can overflow. | Non-wrapping flex rows. | Wrap/stack header and footer controls. |
| Course Mapping `/course-mapping` | High | Mapping headers/program rows can overflow. | Fixed right form column and nowrap CTA buttons. | Collapse two-column layout; stack mapping headers and CTA buttons. |
| Course Mapping edit `/course-mapping/edit/<course_id>` | Medium | Save/cancel row and order controls can overflow. | No mobile media rules. | Stack action row and allow order controls to wrap. |
| Student demo/topic student view | Medium | Preview content remains desktop-sized after sidebar hides. | Student view has separate 280px nav and large content padding/title. | Hide nav on tablet/mobile; reduce padding/title and allow tab scroll. |
| Content create/edit/view descendants | Medium | TinyMCE toolbar, hotspot modal, rich text tables/images may overflow. | Third-party editor and saved rich content can be wider than viewport. | Cap editor width, constrain modals, and keep rich content inside local overflow. |
| Resources/attachments descendants | Medium | Same pattern as Batch Access with custom grids and tables. | Reused `1fr 280px` grids and fixed columns. | Collapse grids and keep tables scrollable locally. |

## Files Touched In First Implementation Pass

- `templates/lms_admin/base.html`
- `templates/lms_admin/lms_all_assignments.html`
- `templates/lms_admin/lms_bulk_assign.html`
- `templates/lms_admin/lms_course_mapping_edit.html`
- `templates/lms_admin/phase6_rollout.html`
- `LMS_ADMIN_MOBILE_OPTIMIZATION_PLAN.md`

## Testing Checklist

Test core LMS Admin pages and representative create/edit/detail pages at:

- 360px: sidebar hidden behind drawer; no body-level horizontal scroll.
- 390px: dashboard cards, filters, headers, and actions fit without clipping.
- 412px: tables scroll only inside their local wrappers/cards when needed.
- 650px: tablet layout uses full content width and side help cards stack cleanly.
- Desktop width: sidebar remains visible and desktop layout is mostly unchanged.

Acceptance criteria:

- `document.documentElement.scrollWidth <= window.innerWidth` on mobile, except for intentional local scroll regions.
- Sidebar does not consume layout width below 768px.
- Primary actions are reachable and touch-friendly.
- Tables, modals, topbar title, form controls, and action groups are not clipped.

## Remaining Follow-Up

- Consider extracting LMS Admin responsive rules into a dedicated CSS file once the mobile behavior is accepted.
- A second polish pass can convert selected wide management tables into true mobile card lists where users need easier row scanning than horizontal table scrolling.
