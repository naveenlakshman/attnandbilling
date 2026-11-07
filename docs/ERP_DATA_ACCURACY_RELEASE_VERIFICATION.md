# ERP accuracy release verification — 7 November 2026

Owner decision package: [ERP-ACCURACY-20261107-R1](ERP_ACCURACY_OWNER_RELEASE_PACKAGE.md), with all 45 exclusions, monthly/period/lifetime cash-report impact, staff instructions and exact conditional approval scope. Preparing the package grants no approval.

Deployment remains on hold. No production migration, financial write, historical reclassification or origin backfill was performed. Production access in this verification was read-only.

## Final code and test evidence

The earlier 381-pass result is superseded. The final working-tree source fingerprint is `8f47a0f8b3325e4dcc23db1c29239cbadfa22da0962be64d37b3dfcab50b2a20`, recorded per file in [the manifest](../scratch/erp-accuracy-review/release-verification/final-code-manifest.json). This is an uncommitted working-tree fingerprint, not a Git commit or deployed revision.

| Final verification | Result | Evidence |
|---|---|---|
| Affected billing, accuracy, gateway, payment-link, receipt UI and export suite | 223 passed | [JUnit](../scratch/erp-accuracy-review/release-verification/final-affected.xml) |
| Full Python suite, including bad-debt reversal script | 416 passed, no skips | [JUnit](../scratch/erp-accuracy-review/release-verification/final-full.xml) |
| Checkout JavaScript | 17 passed | [Log](../scratch/erp-accuracy-review/release-verification/final-checkout-js.log) |
| Source compilation and diff whitespace | Passed | Final source manifest and `git diff --check` |

The full suite includes SQLite unit tests and disposable MySQL integration tests; it is not a claim that all SQLite-specific tests were converted to MySQL. Both MySQL fixtures enforce `ERP_MYSQL_EXPECTED_VERSION=8.0.45`. Critical installment, CSV metadata, credit, write-off form, admission provenance and gateway cases execute on both backends. Gateway tests use mocked responses and never charge a card. The final focused ERP suite passed 57 cases, including six oversized-schedule cases across the two backends. Existing Python deprecation warnings remain.

A timing-sensitive receipt-page test was corrected to validate the rendered payment URL's host and signed invoice/student binding, rather than require timestamped URLs generated at different times to be identical strings.

## Production snapshot and required schema

The consistent, read-only production snapshot was captured at **2026-11-07 13:35:13 UTC / 19:05:13 IST**, from `global-it-edu-app / global-it-erp-production-db / global_it_erp_production`. Its engine reports `8.0.45-google`; the isolated Oracle MySQL runtime reports **8.0.45**. SQL modes match, including `ONLY_FULL_GROUP_BY` and `STRICT_TRANS_TABLES`. Authentication hashes, SMS tokens and gateway session identifiers were redacted before local storage.

The snapshot includes 23 relevant tables, 620 invoices and 1,184 receipts across two institutes. A separate read-only check confirmed source SYSTEM time is UTC and the captured tables have no TIMESTAMP columns, so restoration does not reinterpret timestamp offsets; stored date/datetime values were preserved. It was restored into a separate local database, never pointed at by the browser fixture. The browser uses synthetic institute IDs 7 and 8.

[Final schema evidence](../scratch/erp-accuracy-review/release-verification/final-schema-verification.json) verifies:

- Two initial migration executions, followed by two final repeat executions on the isolated clone. All 23 pre-existing table row counts and row hashes remained unchanged.
- All **12 required new tables, 111 column definitions and 29 indexes**, including primary keys, uniqueness, index order, nullability, defaults, types, collations and InnoDB engines, match a fresh database created from the shipped migration.
- Repetition did not change the new schema. The integration scenario also retains newly written admission/payment history across migration repetition.
- Ownership, request/reference uniqueness, concurrency and relationship validation are exercised by integration tests. The migration does not introduce database `FOREIGN KEY` clauses; those ownership checks occur in services.

`CREATE TABLE IF NOT EXISTS` does **not** repair an incompatible pre-existing table, prove a downgrade is safe, or make MySQL DDL transactional. Comparing the required schema manifest is a deployment gate. A fresh read-only production metadata check at 14:37 UTC confirmed all 12 accuracy tables are currently absent; nothing was applied there. See [production preflight](../scratch/erp-accuracy-review/release-verification/production-schema-preflight.json).

## Reconciliation and definitions

Invoice `total_amount` already includes its discount. Write-offs reduce collectible dues; they are not cash payments. Outstanding is the sum of positive invoice balances. Credit is the sum of negative balances expressed as a positive amount, separately displayed; credits do not reduce another invoice's outstanding amount. A legacy credit is not approval to issue a refund.

### July backup: corrected increase INR 13,325

The backup ends on 17 July and contains 483 invoices and 984 receipts. Legacy visible installment dues were **INR 2,39,867**; corrected visible dues are **INR 2,53,192**, an increase of **INR 13,325**. The superseded candidate total of INR 2,68,567 overstated dues by INR 15,375.

| Invoice / database ID | Net invoice | Receipts | Write-offs | Old visible dues | Correct dues | Correct increase | Superseded candidate increase |
|---|---:|---:|---:|---:|---:|---:|---:|
| GIT/B/257 / 7 | 22,000 | 10,000 | 12,000 | 0 | 0 | 0 | 12,000 |
| GIT/B/271 / 20 | 15,750 | 5,750 | 0 | 0 | 10,000 | 10,000 | 10,000 |
| GIT/B/453 / 453 | 15,300 | 5,000 | 7,225 | 0 | 3,075 | 3,075 | 6,450 |
| GIT/B/481 / 481 | 9,500 | 5,000 | 0 | 4,250 | 4,500 | 250 | 250 |
| **Total increase** | | | | | | **13,325** | **28,700** |

All amounts are INR. Invoice 7 has INR 34,000 scheduled against a INR 22,000 invoice: the extra INR 12,000 is not debt. Invoice 453 has INR 18,675 scheduled against INR 15,300: the extra INR 3,375 is not debt, while the genuine INR 3,075 was hidden by partial-write-off status filtering. Invoice 20 has stale fully-paid installment caches despite only INR 5,750 in receipts. Invoice 481 has a paid-status installment with INR 250 still uncovered. Nothing was posted or collected by this reporting change.

### Current snapshot: corrected increase INR 3,075

For **Global IT, institute 1 only**, old visible dues are **INR 2,23,747** and corrected visible dues are **INR 2,26,822**. The sole genuine visibility increase is invoice 453: **INR 3,075**.

- Invoice 7 remains fully covered; its oversized schedule adds zero debt.
- Invoice 20 is now fully paid; the July INR 10,000 visibility issue no longer exists.
- Invoice 481's current cache no longer hides the July INR 250.
- Invoice 588 / GIT/B/525 has INR 14,500 scheduled against a INR 7,500 invoice with INR 7,500 receipts. Its INR 7,000 excess schedule adds zero debt.

| Current control — institute 1 | Amount / count |
|---|---:|
| Invoices | 561 |
| Net posted invoice value, already after discounts | INR 46,44,710 |
| Discount, disclosed separately | INR 5,16,193 |
| Receipts | 1,184 / INR 41,65,021 |
| Write-offs | 45 / INR 2,57,442 |
| **Outstanding** | **INR 2,26,822** |
| **Credit, separately visible** | **INR 4,575** |
| Signed balance: outstanding minus credit | INR 2,22,247 |

Control identity: `46,44,710 - 41,65,021 - 2,57,442 = 2,26,822 - 4,575`. Difference: **zero**. No receipt/write-off orphan or institute mismatch was found. All 561 invoice balances agree across the Python ledger, SQL balances, capped installment dues, payment-link amounts, invoice screens and CSV exports. The 49 collectible installment rows selected by reminder queries sum to INR 2,26,822; the sender was never called. See [balance controls](../scratch/erp-accuracy-review/release-verification/balance-controls.json).

The credit belongs to GIT/B/281 / invoice 32: INR 8,075 net invoice, INR 3,500 receipts, and two INR 4,575 write-offs. Both source records remain intact, and owner review is required before treating that credit as refundable or reversing a waiver.

Institute 2 is separate: 59 invoices, INR 1,12,100 outstanding, no receipts or credits. Its schedules are missing, so the outstanding report labels due-date/age information unknown. Its dues are not added to the institute-1 numbers above. Extended checks confirm all 620 invoice headers satisfy subtotal minus discount equals total, and every receipt creator belongs to its institute. There are also 271 institute-1 invoices without schedules; none has positive current outstanding. No dates or origins were invented to fill these gaps. One pre-existing orphan pair also remains unresolved: invoice item 800 and installment 496 both reference missing invoice 449 and each carries INR 8,500. They were already excluded by invoice-parent joins before this release, create zero before/after dues change, and were preserved by the migration. Audit IDs 14975/14976 show the invoice once existed, but do not establish why its parent is absent. Do not reconstruct or delete it automatically. See [extended source checks](../scratch/erp-accuracy-review/release-verification/source-integrity-extensions.json) and [orphan evidence](../scratch/erp-accuracy-review/release-verification/orphan-invoice-449-evidence.json).

Detailed [current reconciliation](../scratch/erp-accuracy-review/release-verification/production-reconciliation-corrected.json) and [July reconciliation](../scratch/erp-accuracy-review/release-verification/july-reconciliation-corrected.json) retain each invoice, installment and superseded-candidate comparison. Source invoice and receipt amounts are unchanged.

## Creation paths and historical unknowns

| Supported path | Verified handling |
|---|---|
| Manual student registration / student CSV | Creates a student identity, not an inferred course admission. Existing/current student branch is not admission-origin evidence. |
| New invoice, explicit new purchase | Creates an admission per purchased course with explicit booking origin, creator/source and item link; DFA defaults to Basics and Tally. |
| Subsequent invoice against an existing admission | Reuses the selected admission; does not increase admission count. Mixed-course items have separate validated links. |
| Accuracy admission form/API, including reviewed import/recovery | Source reference required for imports/recovery; importer is distinct from original creator. Unknown original branch/creator remain null. Repeated purchases can create distinct admissions for one student. |
| Invoice/item/installment CSV | Validates tenant and invoice arithmetic; does not infer admission origin or identity. Review and explicit linking remain required. Posted item/schedule history cannot be overwritten by import. |
| Manual receipt / accuracy payment / advance allocation | Uses source payment and allocation services; records collection branch/channel/date/reference, creator and posting time; request/reference uniqueness and balance locks prevent duplicate/over-collection. |
| Receipt CSV / XLSX upload | Same validated service for either parsed format. Preserves `collection_branch_id`, `payment_channel`, `payment_date` or `receipt_date`, and `payment_reference`; rejects conflicting dates, foreign branches, invalid channels/methods/references and amounts. Preserves supplied receipt number. Duplicate replay is idempotent; conflicting reuse is rejected. Each row is atomic under a savepoint. |
| Staff/student Cashfree checkout, return, verification and webhook | Shares verified posting logic and attaches gateway metadata once. Physical branch stays unknown; channel is online. Timestamp is converted to IST; a missing/invalid timestamp is labelled `posting_fallback`, not claimed as a verified gateway payment date. |

CSV historical unknowns are explicit: null physical branch/reference, `payment_channel=unresolved`, unknown method where omitted, and empty payment/allocation dates with `date_source=import_unknown`. No field is inferred from invoice branch, staff branch, notes or importer identity. Current balances include undated receipts; date-filtered reports exclude them from dated totals and disclose their amount separately. Receipt exports retain the structured fields. The all-table tenant export also fails closed for global/unknown ownership tables, scopes all new accuracy tables, and requires both attendance student and batch ownership. It is a tenant export, not a platform-wide backup. A two-institute regression runs on SQLite and MySQL 8.0.45. Refunds, reversals and fee reductions remain separate dated events.

## Browser evidence

Browser checks use the actual blueprints, templates, static assets, CSRF handling and permission decorators in a loopback fixture on MySQL 8.0.45. Synthetic login sets the test institute/role; this is not a production login or hostname-resolution test. SMS/portal provisioning is disabled, gateway tests are mocked, and the permission-denial landing page is a fixture. The fixture was extended with 31 pre-existing production columns when the invoice screen required fields omitted by the minimal unit seed; no production rows were copied.

All requested browser checks passed; no second Escape interruption occurred. Actual server logs confirm foreign direct-ID access returned 404 and staff accuracy workspace/CSV requests redirected with Access denied.

| Browser check | Observed result | Screenshot |
|---|---|---|
| New and repeat course admissions | Two distinct IDs for student 1/course 1, with separate original branches and preserved creator/source | [Admission register](../scratch/erp-accuracy-review/release-verification/screenshots/09-repeat-admission-register.png) |
| Cross-branch training | Basics at Head Office and Tally at Hoskote share the original Head Office admission | [Training](../scratch/erp-accuracy-review/release-verification/screenshots/01-cross-branch-training.png) |
| Collection location | INR 4,000 at Head Office and INR 6,000 at Hoskote, total INR 10,000 | [Collections](../scratch/erp-accuracy-review/release-verification/screenshots/02-collection-locations.png) |
| Admission-origin collection | Both receipts attributed to Head Office, without duplicate sales or admission IDs | [Origin collections](../scratch/erp-accuracy-review/release-verification/screenshots/03-admission-origin-collections.png) |
| Discount once | INR 12,000 less INR 2,000 equals INR 10,000, paid INR 10,000 and due zero | [Invoice](../scratch/erp-accuracy-review/release-verification/screenshots/06-discount-once.png) |
| Partial write-off | INR 6,000 invoice less INR 2,000 write-off leaves INR 4,000 collectible; no cash expense created | [Remaining dues](../scratch/erp-accuracy-review/release-verification/screenshots/04-partial-writeoff-remaining-dues.png) |
| Write-off reversal | Original write-off retained; separate reversal restores INR 6,000 dues | [Reversal](../scratch/erp-accuracy-review/release-verification/screenshots/05-writeoff-reversal-dues.png) |
| Credit separate from dues | Dated INR 500 fee reduction against a paid invoice creates INR 500 credit, while another invoice still shows INR 6,000 due | [Separate totals](../scratch/erp-accuracy-review/release-verification/screenshots/07-credit-separate-from-dues.png) |
| Receipt reversal | Original INR 10,000 receipts remain; net cash becomes INR 9,000 against INR 9,500 adjusted charge, leaving INR 500 due | [Receipt correction](../scratch/erp-accuracy-review/release-verification/screenshots/08-receipt-reversal-remaining-dues.png) |
| Institute isolation | Institute 8 sees only invoice 8 / INR 100; institute-7 invoice ID 1 returns 404 | [Scoped report](../scratch/erp-accuracy-review/release-verification/screenshots/10-second-institute-only.png), [denied ID](../scratch/erp-accuracy-review/release-verification/screenshots/11-cross-institute-direct-id-denied.png) |
| Permissions and exports | Staff cannot open admin accuracy tools or download their CSV | [Workspace denied](../scratch/erp-accuracy-review/release-verification/screenshots/12-staff-permission-denied.png), [CSV denied](../scratch/erp-accuracy-review/release-verification/screenshots/13-staff-export-denied.png) |

The browser-generated [collections CSV](../scratch/erp-accuracy-review/release-verification/collections-browser.csv) matches the two displayed collections exactly. It was captured before the later receipt correction. After the explicit INR 1,000 reversal, the final synthetic collection total is INR 9,000; that change is fully explained by the retained dated event. See [synthetic transaction proof](../scratch/erp-accuracy-review/release-verification/browser-verification-data.json). Real gateway charges, production login/host resolution, SMS delivery and candidate image verification remain outside this browser fixture; backend gateway/tenant tests cover their changed service paths.

## Separate historical review

See [the 24-entry correction proposal](ERP_ACCURACY_DATA_CORRECTION_PROPOSAL.md). The original 24 total INR 1,50,890; all current 45 exact matches total INR 2,57,442. These are proposed cash-report classifications, not invoice reductions or actual cash movements. All 479 original registrations remain explicitly unresolved. This is the preserved original review set, not a claim that later legacy registrations have been recovered. Historical admission totals remain incomplete until reviewed admission identities/links exist; zero confirmed admission rows does not establish zero historical admissions. No approval to correct history is implied by software release readiness.

## Limitations and next release gates

Historical admission attribution, missing historical collection locations, the duplicate-looking waiver/credit, and independent bank/gateway settlement reconciliation remain review work. Financial period locking and historical teaching hours are not introduced. No real gateway charge or live SMS was sent. A final container build and zero-traffic candidate validation belong to the separately authorized deployment procedure; neither was performed in this verification. The current production snapshot must be refreshed before promotion to account for intervening business transactions.

The deployment hold is explicit. Follow the exact runbook in the handover only after separate authorization; do not use the repository's stock Cloud Build deployment step, which replaces environment/secrets configuration, as an unreviewed shortcut.


## Recommendation

**READY for the controlled software release process and review. No local code, migration, reconciliation or requested browser-test blocker remains. Deployment remains on hold.**

Before production traffic promotion, obtain explicit deployment authorization, run the documented container checks and zero-traffic candidate smoke tests, refresh the production snapshot, and review the complete cash-reporting impact. These production gates were not bypassed or claimed as completed. Historical reclassification, the credit/duplicate waiver, orphan invoice 449 and the 479 unresolved registrations remain separate data-review items; no historical correction is part of this release.
