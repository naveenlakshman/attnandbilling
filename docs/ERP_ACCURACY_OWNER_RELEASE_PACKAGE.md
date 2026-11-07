# Owner release package — ERP-ACCURACY-20261107-R1

**Decision requested: conditional approval of the tested software and its reporting rules. Nothing is deployed or changed in production by preparing this package.**

This is one release decision covering the reviewed source, additive schema, guarded candidate process and explicit reporting effect below. Historical data remediation remains outside that decision.

## Review basis and exact source

- Tested working-tree fingerprint: **`8f47a0f8b3325e4dcc23db1c29239cbadfa22da0962be64d37b3dfcab50b2a20`**.
- Base Git HEAD: `87fe7cb42230b16aa3bbf63a0b66b4129faddb0e`. The release changes are still uncommitted; this HEAD alone is not the tested release. The fingerprint is SHA-256 of the sorted per-file hash map for changed/new Python, HTML and SQL files in the [tested manifest](../scratch/erp-accuracy-review/release-verification/final-code-manifest.json). Unchanged application files come from that base HEAD.
- Final verification: **416 full-suite, 223 affected, 57 focused ERP and 17 JavaScript tests passed**. MySQL integration fixtures enforce **8.0.45**; production reports **8.0.45-google**. The suite includes SQLite-specific tests and real disposable MySQL tests; not every unit test was converted to MySQL.
- Migration: `migrations/20261107_erp_data_accuracy.sql`; 12 new tables, 111 columns and 29 indexes match the fresh expected schema. Repeated execution preserved all 23 existing snapshot tables. These tables remain absent in the last read-only production schema inspection.
- Financial basis: Global IT / **institute 1 only**, frozen consistent snapshot at **7 November 2026, 19:05:13 IST (13:35:13 UTC)**. The original 24 and additional 21 are revalidated directly from that same snapshot. No live balance refresh was substituted.
- Snapshot file SHA-256: `65e8ab6ccd025950b0ac457b897cf239f4005b94909d392062f808b1a29f661b`. Private snapshot/evidence stays under ignored local scratch paths; do not upload it into the application image.
- Before build: commit the approved content, record its commit and immutable image digest, and recheck the tested file hashes. Any source change requires refreshed tests/evidence. No image or candidate revision has yet been built/deployed.

## Software covered by this release decision

The fingerprinted software includes admission identity/origin and separate training assignments; collection location/channel/date/reference capture including validated CSV imports with explicit historical unknowns; source payments, advances and allocations; dated financial corrections and separately visible credits; capped installment dues and shared balance logic across invoices, reminders and exports; and institute/export isolation fixes. Approval makes those workflows available. It does not itself execute a reversal, refund, origin correction or other financial correction. Each such transaction remains a separate authorized case.

## What promotion changes immediately

**Yes: the new software activates all 45 matching expense exclusions in affected cash reports immediately after the additive schema exists and the new revision serves those reports. There is no per-entry switch or separate apply step.** A zero-traffic candidate already displays the revised calculations when its reports are inspected; promotion exposes them to normal traffic.

The predicate excludes an expense when a write-off has the same institute, nonempty reference and amount, and the expense title begins `Bad Debt Write-off`. It affects the core dashboard and billing cash-position/expense calculations that use this predicate. Historical months are restated using the original expense date; INR 2,57,442 is not charged to the deployment month. Stored expense rows, raw expense exports, invoices, receipts and write-off records are retained. Invoice sales, actual bank cash and the existing credit do not change because of this exclusion.
The extra E checks below validated these 45 for review. Runtime does not enforce their date/timestamp/actor confidence checks or a per-record approval status; it enforces the predicate just stated. The rule operates within each institute. The other institute has no matching expense/write-off rows in this snapshot, so its current exclusion impact is zero.

**This is a general rule, not a static allowlist of 45 IDs.** Matching rows added or changed before/after release also qualify. The current snapshot has exactly these 45. Refresh the match list before promotion; a changed list/amount must return to owner review. Approval of only the original 24 is insufficient to promote this source unchanged. Restricting the rule to a fixed list would require a separately tested code change and a new fingerprint.

## All 45 proposed exclusions — one table

Amounts are INR. **E** means the snapshot proves a unique write-off reference plus matching institute, amount, full invoice title, business date, creation timestamp and creator/authorizer. The evidence column gives the stable write-off ID and complete reference. This proves database linkage, not independent bank settlement or the validity of the underlying waiver. **†** flags GIT/B/281 for separate source-document review.

For each row, expense inclusion decreases by its amount and the calculated cash position increases by the same amount **in the listed month**. Actual cash/bank balances do not increase. All proposals remain `apply=false`; the software calculation change is the distinct release scope described above.

| Review group | Expense ID | Date | Invoice | Amount | Evidence: write-off ID / reference | Monthly calculated-position increase |
|---|---:|---|---|---:|---|---:|
| Original 24 | 7 | 2026-03-31 | GIT/B/281 † | ₹4,575.00 | E: W3 / GIT/B/WO/001 | 2026-03: +₹4,575.00 |
| Original 24 | 11 | 2026-04-04 | GIT/B/281 † | ₹4,575.00 | E: W5 / GIT/B/WO/002 | 2026-04: +₹4,575.00 |
| Original 24 | 13 | 2026-04-08 | GIT/B/187 | ₹5,422.00 | E: W6 / GIT/B/WO/003 | 2026-04: +₹5,422.00 |
| Original 24 | 14 | 2026-04-08 | GIT/B/190 | ₹5,422.00 | E: W7 / GIT/B/WO/004 | 2026-04: +₹5,422.00 |
| Original 24 | 15 | 2026-04-08 | GIT/B/287 | ₹10,000.00 | E: W8 / GIT/B/WO/005 | 2026-04: +₹10,000.00 |
| Original 24 | 16 | 2026-04-08 | GIT/B/261 | ₹5,600.00 | E: W9 / GIT/B/WO/006 | 2026-04: +₹5,600.00 |
| Original 24 | 17 | 2026-04-08 | GIT/B/249 | ₹10,250.00 | E: W10 / GIT/B/WO/007 | 2026-04: +₹10,250.00 |
| Original 24 | 18 | 2026-04-08 | GIT/B/309 | ₹3,500.00 | E: W11 / GIT/B/WO/008 | 2026-04: +₹3,500.00 |
| Original 24 | 19 | 2026-04-08 | GIT/B/186 | ₹2,900.00 | E: W12 / GIT/B/WO/009 | 2026-04: +₹2,900.00 |
| Original 24 | 20 | 2026-04-08 | GIT/B/283 | ₹14,000.00 | E: W13 / GIT/B/WO/010 | 2026-04: +₹14,000.00 |
| Original 24 | 21 | 2026-04-08 | GIT/B/274 | ₹3,500.00 | E: W14 / GIT/B/WO/011 | 2026-04: +₹3,500.00 |
| Original 24 | 33 | 2026-04-30 | GIT/B/354 | ₹3,000.00 | E: W15 / GIT/B/WO/012 | 2026-04: +₹3,000.00 |
| Original 24 | 34 | 2026-05-05 | GIT/B/344 | ₹7,500.00 | E: W16 / GIT/B/WO/013 | 2026-05: +₹7,500.00 |
| Original 24 | 35 | 2026-05-09 | GIT/B/318 | ₹9,000.00 | E: W17 / GIT/B/WO/014 | 2026-05: +₹9,000.00 |
| Original 24 | 36 | 2026-05-09 | GIT/B/333 | ₹4,500.00 | E: W18 / GIT/B/WO/015 | 2026-05: +₹4,500.00 |
| Original 24 | 37 | 2026-05-09 | GIT/B/322 | ₹4,750.00 | E: W19 / GIT/B/WO/016 | 2026-05: +₹4,750.00 |
| Original 24 | 38 | 2026-05-09 | GIT/B/323 | ₹671.00 | E: W20 / GIT/B/WO/017 | 2026-05: +₹671.00 |
| Original 24 | 39 | 2026-05-09 | GIT/B/257 | ₹12,000.00 | E: W21 / GIT/B/WO/018 | 2026-05: +₹12,000.00 |
| Original 24 | 47 | 2026-05-13 | GIT/B/370 | ₹2,850.00 | E: W22 / GIT/B/WO/019 | 2026-05: +₹2,850.00 |
| Original 24 | 55 | 2026-06-03 | GIT/B/324 | ₹7,500.00 | E: W24 / GIT/B/WO/020 | 2026-06: +₹7,500.00 |
| Original 24 | 56 | 2026-06-05 | GIT/B/378 | ₹4,550.00 | E: W25 / GIT/B/WO/021 | 2026-06: +₹4,550.00 |
| Original 24 | 60 | 2026-06-10 | GIT/B/423 | ₹10,000.00 | E: W26 / GIT/B/WO/022 | 2026-06: +₹10,000.00 |
| Original 24 | 70 | 2026-07-08 | GIT/B/453 | ₹7,225.00 | E: W27 / GIT/B/WO/023 | 2026-07: +₹7,225.00 |
| Original 24 | 71 | 2026-07-09 | GIT/B/448 | ₹7,600.00 | E: W28 / GIT/B/WO/024 | 2026-07: +₹7,600.00 |
| **Original 24 subtotal** | **24 rows** | March–July | | **₹1,50,890.00** | Includes ₹4,575 dated 31 March | **Apr–Nov portion: +₹1,46,315.00** |
| Additional 21 | 83 | 2026-07-31 | GIT/B/392 | ₹3,050.00 | E: W29 / GIT/B/WO/025 | 2026-07: +₹3,050.00 |
| Additional 21 | 84 | 2026-07-31 | GIT/B/400 | ₹3,000.00 | E: W30 / GIT/B/WO/026 | 2026-07: +₹3,000.00 |
| Additional 21 | 85 | 2026-07-31 | GIT/B/489 | ₹500.00 | E: W31 / GIT/B/WO/027 | 2026-07: +₹500.00 |
| Additional 21 | 86 | 2026-08-01 | GIT/B/404 | ₹3,000.00 | E: W32 / GIT/B/WO/028 | 2026-08: +₹3,000.00 |
| Additional 21 | 88 | 2026-08-03 | GIT/B/460 | ₹6,501.00 | E: W33 / GIT/B/WO/029 | 2026-08: +₹6,501.00 |
| Additional 21 | 92 | 2026-08-24 | GIT/B/442 | ₹4,500.00 | E: W34 / GIT/B/WO/030 | 2026-08: +₹4,500.00 |
| Additional 21 | 96 | 2026-08-28 | GIT/B/475 | ₹4,500.00 | E: W35 / GIT/B/WO/031 | 2026-08: +₹4,500.00 |
| Additional 21 | 97 | 2026-08-29 | GIT/B/444 | ₹5,000.00 | E: W36 / GIT/B/WO/032 | 2026-08: +₹5,000.00 |
| Additional 21 | 98 | 2026-09-01 | GIT/B/493 | ₹1,300.00 | E: W37 / GIT/B/WO/033 | 2026-09: +₹1,300.00 |
| Additional 21 | 99 | 2026-09-01 | GIT/B/494 | ₹5,300.00 | E: W38 / GIT/B/WO/034 | 2026-09: +₹5,300.00 |
| Additional 21 | 100 | 2026-09-01 | GIT/B/495 | ₹3,300.00 | E: W39 / GIT/B/WO/035 | 2026-09: +₹3,300.00 |
| Additional 21 | 102 | 2026-09-10 | GIT/B/502 | ₹8,625.00 | E: W41 / GIT/B/WO/037 | 2026-09: +₹8,625.00 |
| Additional 21 | 103 | 2026-09-10 | GIT/B/458 | ₹3,000.00 | E: W42 / GIT/B/WO/038 | 2026-09: +₹3,000.00 |
| Additional 21 | 104 | 2026-09-18 | GIT/B/459 | ₹1,000.00 | E: W43 / GIT/B/WO/039 | 2026-09: +₹1,000.00 |
| Additional 21 | 111 | 2026-09-28 | GIT/B/511 | ₹3,500.00 | E: W44 / GIT/B/WO/040 | 2026-09: +₹3,500.00 |
| Additional 21 | 112 | 2026-10-16 | GIT/B/526 | ₹8,332.00 | E: W45 / GIT/B/WO/041 | 2026-10: +₹8,332.00 |
| Additional 21 | 120 | 2026-10-22 | GIT/B/480 | ₹2,250.00 | E: W46 / GIT/B/WO/042 | 2026-10: +₹2,250.00 |
| Additional 21 | 127 | 2026-11-07 | GIT/B/538 | ₹12,000.00 | E: W47 / GIT/B/WO/043 | 2026-11: +₹12,000.00 |
| Additional 21 | 128 | 2026-11-07 | GIT/B/548 | ₹11,375.00 | E: W48 / GIT/B/WO/044 | 2026-11: +₹11,375.00 |
| Additional 21 | 129 | 2026-11-07 | GIT/B/520 | ₹4,050.00 | E: W49 / GIT/B/WO/045 | 2026-11: +₹4,050.00 |
| Additional 21 | 130 | 2026-11-07 | GIT/B/320 | ₹12,469.00 | E: W50 / GIT/B/WO/046 | 2026-11: +₹12,469.00 |
| **Additional 21 subtotal** | **21 rows** | | | **₹1,06,552.00** | Separately listed, same E validation | **Apr–Nov: +₹1,06,552.00** |
| **All matches** | **45 rows** | | | **₹2,57,442.00** | Full as-shipped reporting scope | **Apr–Nov: +₹2,52,867.00** |

## Monthly cash-report impact: April–November 2026

Requested window is April–November 2026. This snapshot only supports **1 April–7 November**; November below is **1–7 November, month to date**. There is no estimate or assertion about 8–30 November. March has one original exclusion of INR 4,575, included only in lifetime totals. No additional matching exclusion falls before April.

| Expense month | Original 24 effect | Additional 21 effect | Expense inclusion before | Expense inclusion after | Calculated-position increase |
|---|---:|---:|---:|---:|---:|
| 2026-04 | ₹68,169.00 (11 rows) | ₹0.00 (0 rows) | ₹1,44,882.00 | ₹76,713.00 | +₹68,169.00 |
| 2026-05 | ₹41,271.00 (7 rows) | ₹0.00 (0 rows) | ₹1,25,735.00 | ₹84,464.00 | +₹41,271.00 |
| 2026-06 | ₹22,050.00 (3 rows) | ₹0.00 (0 rows) | ₹1,41,107.00 | ₹1,19,057.00 | +₹22,050.00 |
| 2026-07 | ₹14,825.00 (2 rows) | ₹6,550.00 (3 rows) | ₹1,98,574.00 | ₹1,77,199.00 | +₹21,375.00 |
| 2026-08 | ₹0.00 (0 rows) | ₹23,501.00 (5 rows) | ₹1,08,466.00 | ₹84,965.00 | +₹23,501.00 |
| 2026-09 | ₹0.00 (0 rows) | ₹26,025.00 (7 rows) | ₹1,35,675.00 | ₹1,09,650.00 | +₹26,025.00 |
| 2026-10 | ₹0.00 (0 rows) | ₹10,582.00 (2 rows) | ₹1,62,955.00 | ₹1,52,373.00 | +₹10,582.00 |
| 2026-11 (1–7 Nov MTD) | ₹0.00 (0 rows) | ₹39,894.00 (4 rows) | ₹44,506.00 | ₹4,612.00 | +₹39,894.00 |

| Month | Recorded collections, unchanged | Calculated position before | Calculated position after |
|---|---:|---:|---:|
| 2026-04 | ₹3,31,451.50 | ₹1,86,569.50 | ₹2,54,738.50 |
| 2026-05 | ₹2,67,295.50 | ₹1,41,560.50 | ₹1,82,831.50 |
| 2026-06 | ₹2,55,866.00 | ₹1,14,759.00 | ₹1,36,809.00 |
| 2026-07 | ₹3,93,781.00 | ₹1,95,207.00 | ₹2,16,582.00 |
| 2026-08 | ₹2,17,017.00 | ₹1,08,551.00 | ₹1,32,052.00 |
| 2026-09 | ₹2,29,809.00 | ₹94,134.00 | ₹1,20,159.00 |
| 2026-10 | ₹1,76,595.00 | ₹13,640.00 | ₹24,222.00 |
| 2026-11 (1–7 Nov MTD) | ₹45,501.00 | ₹995.00 | ₹40,889.00 |

### Period and lifetime before/after totals

For this frozen pre-release snapshot, no new accuracy events exist. Calculated position here is **recorded receipt collections minus included expenses**. After release it must also reflect dated refunds, reversals, advances and returns through the tested cash-movement logic, counted once. The table isolates the exclusion effect on the same source rows.

| Measure | 1 Apr–7 Nov 2026: before | 1 Apr–7 Nov 2026: after | Lifetime through snapshot: before | Lifetime through snapshot: after |
|---|---:|---:|---:|---:|
| Recorded collections — unchanged | ₹19,17,316.00 | ₹19,17,316.00 | ₹41,65,021.00 | ₹41,65,021.00 |
| Included expense amounts | ₹10,61,900.00 | ₹8,09,033.00 | ₹10,68,934.00 | ₹8,11,492.00 |
| **Calculated cash position** | **₹8,55,416.00** | **₹11,08,283.00** | **₹30,96,087.00** | **₹33,53,529.00** |
| **Reporting increase, no money received** | — | **+₹2,52,867.00** | — | **+₹2,57,442.00** |
| Independently reconciled till/bank balance | **Not established** | **Not established** | **Not established** | **Not established** |

**These calculated positions are not reconciled cash or bank balances, available funds, or profit.** No physical cash counts, bank statements, opening balances or gateway settlement reconciliation were supplied. Bank transfers, settlement timing, unrecorded movements and other reconciling items have not been independently proven. Exclusion does not receive money, repair a bank balance, or validate a write-off. Lifetime means all recorded history in this snapshot, with receipts starting 2 April 2025 and expenses starting 25 March 2026; it is not a complete opening-to-closing cash reconciliation.

The invoice ledger reconciliation remains separate: net invoices INR 46,44,710 less receipts INR 41,65,021 less write-offs INR 2,57,442 equals signed balance INR 2,22,247 = outstanding INR 2,26,822 minus separately visible credit INR 4,575. The cash-report exclusion changes none of those posted amounts. The July visible-dues increase is INR 13,325; the current-snapshot increase is INR 3,075. Neither is new cash or a newly posted debt.

## GIT/B/281 — preserve pending source-document review

Invoice database ID 32 is reviewed separately from the reporting exclusions:

| Source record | Date | Amount | Required treatment now |
|---|---|---:|---|
| Net invoice GIT/B/281 | Existing posted invoice | ₹8,075.00 | Preserve |
| Receipts, total | Existing posted receipts | ₹3,500.00 | Preserve; no automatic refund |
| Write-off ID 3 / GIT/B/WO/001; expense ID 7 | 31 Mar 2026 | ₹4,575.00 | Preserve both source records |
| Write-off ID 5 / GIT/B/WO/002; expense ID 11 | 4 Apr 2026 | ₹4,575.00 | Preserve both source records |
| **Signed balance** | 8,075 − 3,500 − 4,575 − 4,575 | **−₹4,575.00** | Do not offset another invoice |
| **Separately visible credit** | Current ledger result | **₹4,575.00** | Source review required; not refund approval |

The references/dates are distinct; database evidence does not establish whether one waiver was duplicated, superseded or otherwise authorized. Obtain the original invoice, both waiver approvals and receipt/payment evidence. Release approval may authorize exclusion of both linked noncash expense representations from cash calculations; it does **not** endorse both waivers, reverse either, refund the credit or change stored records. No such action is automatic.

## Remaining container and candidate gates

These checks are still unperformed and are mandatory before promotion. The [deployment runbook](ERP_DATA_ACCURACY_HANDOVER.md#exact-deployment-procedure--not-executed) contains parameterized commands; do not run its production steps during this owner-review task.

1. Freeze the approved source into a commit and verify equivalence to the tested manifest. Build the Linux/Python 3.12 image using the build-only Cloud Build configuration, without the stock deployment step. Pass every existing container check; verify accuracy module/templates/static assets, dependency loading and no private snapshot/test-login fixture/secret files in the image. Record the immutable image digest.
2. Refresh production read-only evidence and this 45-match list. Account for every intervening real transaction. Recheck MySQL 8.0.45 patch level/modes, base-schema prerequisites, backup/PITR restore point and all required new schema definitions. Apply the additive schema only after explicit authorization; Cloud Run does not apply it automatically.
3. Create a tagged zero-traffic candidate using only the approved immutable image. Preserve current environment values, secret versions, service account, network/egress, Cloud SQL attachment and baseline traffic split. Check health/readiness, TLS, real login, CSRF, authorized tenant-host resolution and two-institute isolation. Production smoke checks stay read-only; write scenarios run against an isolated/staging database.
4. Verify candidate reports/exports against the refreshed calculations, including all 45 exclusions, monthly figures, separate credit, remaining partial-write-off dues and unknown historical origins/locations. Verify gateway/SDK/CSP configuration, idempotent posting and recovery in isolation without a real charge or production test record. Review logs for schema/permission errors.
5. Prove a way to fence **all** financial writes and reconcile gateway payments during recovery. No native finance-maintenance switch or compatibility reader was delivered. Rehearse the post-event recovery below on a clone; do not promote if safe containment/reconciliation cannot be demonstrated.
6. Only after these gates and owner authorization may traffic be promoted. Verify the final source/image/candidate identity and retain baseline and ledger-aware recovery images. If source or material match totals change, return to review instead of treating this package as approval for an amended release.

## Practical recovery after new financial events exist

An older pre-accuracy image cannot correctly read new reductions, reversals, advances or allocations. **Do not route live financial writes back to that image after new events exist.** No drop-table/down-migration or automatic historical repair is included.

1. **Contain and record the cutoff.** The release operator declares the incident, stops staff/import posting and new checkout creation, and uses a tested deployment/database-layer write fence covering web routes, background jobs and gateway posting. Merely asking staff to stop is not enough for callbacks. Do not acknowledge an unprocessed payment as posted. Retain provider order/payment identifiers securely; use a durable holding/reconciliation path and verify actual provider retry behavior rather than assume a callback will return.
2. **Preserve the complete current state before repair.** Take a full Cloud SQL backup/PITR checkpoint or full consistent export covering original invoices/receipts/write-offs and every accuracy, admission/training, allocation/advance, audit, numbering and gateway-order table. Record the current image/config, incident cutoff, pending order IDs and per-institute counts/sums/event IDs. The masked 23-table verification snapshot is **not a disaster-recovery backup**: it redacts authentication/payment tokens and does not capture post-release accuracy events. Never restore it into production.
3. **Fix forward with a ledger-aware reader.** Clone the complete incident state and reproduce the fault. Build a small repaired revision that still reads all new events. For a reporting-only exclusion dispute, narrow/remove the cash-report predicate in a forward patch while retaining ledger readers; do not undo source records or roll back to old balance code. For a configuration/container fault, retain a verified ledger-aware image and restore only the reviewed configuration. Record and test the new fingerprint/image; this review does not pre-approve an arbitrary hotfix.
4. **Reconcile all post-cutoff payments.** Compare provider-confirmed payments/settlements with local Cashfree orders, unique payment IDs and receipt IDs. Existing PAID orders/receipts must not be posted again. Verify known unposted orders through the normal idempotent verification/posting service in the repaired environment; changed-balance or REVIEW cases stay for operator/source review. Do not force REVIEW to PAID, insert manual duplicate receipts or initiate refunds/reversals as a recovery shortcut.
5. **Prove balances before reopening.** For every institute/invoice, compare charges, receipts/net cash, write-offs, dated adjustments, positive outstanding and separate credits. Count a source payment once; allocation is not additional cash. Reconcile advances/returns, receipt mappings, gateway reviews, audit ordering and document numbers. Compare safe-mode and repaired cash-report totals and retain any unresolved bank/cash differences explicitly. Require zero unexplained application-ledger differences.
6. **Resume deliberately.** Deploy the tested ledger-aware repair as a zero-traffic candidate, perform read-only checks, obtain incident-owner approval, then reopen verified posting paths and monitor duplicates/reviews. An older baseline image is an option only when evidence proves no new accuracy events requiring those readers exist. A full backup restore, if unavoidable, is a separately authorized incident action with explicit reconciliation/replay of every subsequent receipt/order; it is not permission to lose or silently reconstruct financial history.

## Brief staff instructions

- **Admission origin:** choose the branch where the course admission originated and the correct admission date. A later separately purchased course/repeat purchase gets a new admission ID. Additional invoices for the same purchase reuse its admission; link mixed-course items individually. DFA Basics and Tally are one admission unless separately purchased. Never apply the old Chaithra rule to future admissions or infer history from invoice creator/importer/current staff branch.
- **Cross-branch training:** use module/batch/trainer assignments with actual branch and start/end dates. Close the previous assignment for a transfer and enter the reason. Keep the original admission origin and old financial transactions intact. An origin correction is an authorized correction with evidence, not a training-transfer action.
- **Receipt collection:** record where payment was actually collected, its channel/method, actual payment date and structured reference. Keep gateway physical branch unknown with channel online; do not use invoice origin as collection location. Wait for gateway verification rather than manually duplicating a pending receipt. Imported unknown metadata stays unknown, never defaulted to the invoice/staff branch or today.
- **Financial corrections:** ask an authorized admin to use a dated correction with a reason. Fee reduction/cancellation, uncollectible write-off, erroneous-receipt reversal and actual refund are different actions. Preserve original invoices/receipts and inspect remaining dues/credit after the event. A write-off is not cash paid out. Do not edit/delete history to make a report agree, or treat the calculated cash-position increase as spendable bank cash.
- **Daily control:** compare recorded collections, advances, refunds and reversals with the physical till, bank entries and gateway settlements. Report discrepancies; a mathematically balanced invoice ledger alone does not reconcile the bank.

Raw expense exports still contain the 45 original rows. Their unadjusted sum is not cash outflow under the new reporting rule; reconcile the listed noncash adjustments when using a raw export.

## Explicitly outside release approval

- All **479** original registration candidates stay `proposed=null`, `confidence=unresolved`, `apply=false`. This is the preserved review set, not a claim that later legacy registrations have been recovered. No original creator/branch, admission identity or historical collection location is assigned by promotion. Historical admission totals remain incomplete until supported links are reviewed.
- Missing invoice **449** stays unresolved. Invoice item **800** and installment **496** each show INR 8,500 against that missing header; they are two representations of one missing invoice reference, not two extra debts. Their pre-existing exclusion creates zero before/after due change. Keep them intact pending invoice/void/source review; do not reconstruct a charge or delete rows automatically.
- GIT/B/281 waiver/credit resolution, any historical backfill, write-off reversal, refund, cancellation or stored-record correction needs its own evidence, proposed before/after values and authorization. None is bundled into approving these reporting exclusions.

## Exact approval statement for this one package

Record the owner name/date and package-manifest checksum with the decision. This authorizes feature availability and normal verified forward posting only; an individual financial correction still needs its own evidence, reason and authorization.

> I approve **ERP-ACCURACY-20261107-R1**, limited to the tested source fingerprint **`8f47a0f8b3325e4dcc23db1c29239cbadfa22da0962be64d37b3dfcab50b2a20`** and its reviewed additive migration. Subject to the mandatory container, refreshed-reconciliation, backup, recovery-containment and zero-traffic candidate gates above, I authorize the release operator to build the equivalent committed source, apply the additive schema, deploy and promote the verified immutable image, and enable normal authorized forward transaction processing. I explicitly accept immediate restatement of historical cash reports under the general matched-noncash-expense rule: the reviewed snapshot contains **45 exclusions**, reducing lifetime included expenses by **INR 2,57,442** and observed April–November included expenses by **INR 2,52,867**. I understand that the same amounts increase only the calculated cash position and are not verified money received or bank/till balances. I do **not** authorize historical backfills, origin assignments, resolution of missing invoice 449, write-off reversals, refunds or stored-record corrections through this release approval.

**This statement is proposed wording, not an approval already given.** Until the owner explicitly approves, deployment/schema changes/promotion and production data changes remain on hold. Before initial promotion, a changed source fingerprint or materially changed reviewed match set requires an amended package. After go-live the approved general rule also operates on future valid matches; that still does not authorize underlying waivers, reversals, refunds or stored-record corrections.

Supporting records: [release verification and 13 screenshots](ERP_DATA_ACCURACY_RELEASE_VERIFICATION.md), [exact rollout/rollback runbook](ERP_DATA_ACCURACY_HANDOVER.md), [separate historical proposal](ERP_ACCURACY_DATA_CORRECTION_PROPOSAL.md), [machine-readable 45-entry/monthly controls](../scratch/erp-accuracy-review/release-verification/owner-release-review-data.json), [review-package checksum manifest](../scratch/erp-accuracy-review/release-verification/owner-release-package-manifest.json).
