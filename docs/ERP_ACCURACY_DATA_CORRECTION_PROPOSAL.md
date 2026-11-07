# ERP historical data correction proposal

Owner decision package: [ERP-ACCURACY-20261107-R1](ERP_ACCURACY_OWNER_RELEASE_PACKAGE.md), with all 45 exclusions, monthly/period/lifetime cash-report impact, staff instructions and exact conditional approval scope. Preparing the package grants no approval.

Status: review only. `apply=false` for every proposal. No production records were changed. This document is separate from the software release verification.

## Evidence and proposed treatment

The 24 originally flagged expense IDs each have one matching current write-off reference. Every pair matches institute, invoice title, amount, business date, creation timestamp and expense creator/write-off authorizer. Current data was captured read-only on 7 November 2026 and reviewed in an isolated MySQL 8.0.45 clone. Source code also identifies these expense rows as generated alongside write-offs. This is strong database evidence of a noncash posting; independent bank statements and signed vouchers were not supplied.

Proposed treatment for each row: retain both original records and their audit history; classify the expense as a noncash write-off for cash reporting. Do not delete an expense, reduce the invoice again, reverse a write-off, or post a refund through this proposal. Stored `payment_mode=cash` is legacy metadata and does not establish that cash was paid out.

| Expense ID | Write-off ID | Invoice | Reference | Date | Amount / cash-expense exclusion (INR) | Conflict |
|---:|---:|---|---|---|---:|---|
| 7 | 3 | GIT/B/281 (ID 32) | GIT/B/WO/001 | 2026-03-31 | 4,575.00 | Duplicate-waiver review below |
| 11 | 5 | GIT/B/281 (ID 32) | GIT/B/WO/002 | 2026-04-04 | 4,575.00 | Duplicate-waiver review below |
| 13 | 6 | GIT/B/187 (ID 27) | GIT/B/WO/003 | 2026-04-08 | 5,422.00 | None in database linkage |
| 14 | 7 | GIT/B/190 (ID 28) | GIT/B/WO/004 | 2026-04-08 | 5,422.00 | None in database linkage |
| 15 | 8 | GIT/B/287 (ID 19) | GIT/B/WO/005 | 2026-04-08 | 10,000.00 | None in database linkage |
| 16 | 9 | GIT/B/261 (ID 25) | GIT/B/WO/006 | 2026-04-08 | 5,600.00 | None in database linkage |
| 17 | 10 | GIT/B/249 (ID 15) | GIT/B/WO/007 | 2026-04-08 | 10,250.00 | None in database linkage |
| 18 | 11 | GIT/B/309 (ID 43) | GIT/B/WO/008 | 2026-04-08 | 3,500.00 | None in database linkage |
| 19 | 12 | GIT/B/186 (ID 26) | GIT/B/WO/009 | 2026-04-08 | 2,900.00 | None in database linkage |
| 20 | 13 | GIT/B/283 (ID 2) | GIT/B/WO/010 | 2026-04-08 | 14,000.00 | None in database linkage |
| 21 | 14 | GIT/B/274 (ID 44) | GIT/B/WO/011 | 2026-04-08 | 3,500.00 | None in database linkage |
| 33 | 15 | GIT/B/354 (ID 354) | GIT/B/WO/012 | 2026-04-30 | 3,000.00 | None in database linkage |
| 34 | 16 | GIT/B/344 (ID 344) | GIT/B/WO/013 | 2026-05-05 | 7,500.00 | None in database linkage |
| 35 | 17 | GIT/B/318 (ID 318) | GIT/B/WO/014 | 2026-05-09 | 9,000.00 | None in database linkage |
| 36 | 18 | GIT/B/333 (ID 333) | GIT/B/WO/015 | 2026-05-09 | 4,500.00 | None in database linkage |
| 37 | 19 | GIT/B/322 (ID 322) | GIT/B/WO/016 | 2026-05-09 | 4,750.00 | None in database linkage |
| 38 | 20 | GIT/B/323 (ID 323) | GIT/B/WO/017 | 2026-05-09 | 671.00 | None in database linkage |
| 39 | 21 | GIT/B/257 (ID 7) | GIT/B/WO/018 | 2026-05-09 | 12,000.00 | None in database linkage |
| 47 | 22 | GIT/B/370 (ID 370) | GIT/B/WO/019 | 2026-05-13 | 2,850.00 | None in database linkage |
| 55 | 24 | GIT/B/324 (ID 324) | GIT/B/WO/020 | 2026-06-03 | 7,500.00 | None in database linkage |
| 56 | 25 | GIT/B/378 (ID 378) | GIT/B/WO/021 | 2026-06-05 | 4,550.00 | None in database linkage |
| 60 | 26 | GIT/B/423 (ID 423) | GIT/B/WO/022 | 2026-06-10 | 10,000.00 | None in database linkage |
| 70 | 27 | GIT/B/453 (ID 453) | GIT/B/WO/023 | 2026-07-08 | 7,225.00 | None in database linkage |
| 71 | 28 | GIT/B/448 (ID 448) | GIT/B/WO/024 | 2026-07-09 | 7,600.00 | None in database linkage |

## Cash-report impact

- Original 24 entries: lifetime cash expenses would fall by INR 150,890.00; calculated cash position would rise by the same amount. Actual bank/cash balances and receipts do not change.
- April through the snapshot date: INR 146,315.00. The INR 4,575 expense dated 31 March is outside this period.
- The current snapshot contains 45 exact matches, including 21 beyond the original 24. The complete proposed read-only reporting filter changes lifetime expense inclusion from INR 10,68,934 to INR 8,11,492: a reduction of INR 2,57,442. The extra 21 total INR 1,06,552 and are listed separately in the evidence artifact; they are not silently included in approval of the original 24.
- The July backup lacks durable write-off references, so its unreviewed cash-expense comparison remains INR 5,45,889 before/after automatic matching. This does not contradict the later current-snapshot evidence.

The release uses a read-only exclusion requiring the same institute, nonempty reference, matching amount and write-off title. It does not update historical rows. Owner review of the complete INR 2,57,442 reporting impact is required before traffic promotion. Any later data reclassification is a separate authorized operation with a before/after dry run and audit record.

## Existing credit requiring separate review

GIT/B/281 (invoice ID 32) has net invoice INR 8,075, receipts INR 3,500 and two write-offs of INR 4,575 (IDs 3 and 5; references WO/001 and WO/002). The resulting INR 4,575 credit is preserved and shown separately from outstanding dues. The records have different dates and references, so they cannot simply be treated as one transaction. Obtain the original approvals to decide whether one waiver was duplicated. This proposal does not authorize reversing either write-off or paying out the credit.

## Unresolved registrations

All 479 original registration candidates remain `proposed=null`, `confidence=unresolved`, `apply=false`. No course admissions, original creators, admission branches or historical collection locations were manufactured. Current branch, invoice creator, receipt creator and importer identity are insufficient evidence of original admission origin. The Chaithra mapping is usable only after the original course-admission creator and bundle/repeat identity are independently established.

## Review artifacts

- [Per-entry proposal and cash impact](../scratch/erp-accuracy-review/release-verification/expense-correction-proposal.json)
- [Source rows and candidate evidence](../scratch/erp-accuracy-review/release-verification/expense-review-evidence.json)
- [479 unresolved candidates](../scratch/erp-accuracy-review/release-verification/unresolved-479-registrations.json)

Artifacts contain private ERP data, remain local under ignored scratch paths, and are excluded from Cloud Build upload and container context.


## Additional source exception, preserved for review

Invoice item 800 and installment 496 each carry INR 8,500 against missing invoice 449. Existing invoice joins already excluded this pair, so it creates zero July/current before-after reporting change. Audit IDs 14975 and 14976 show that the invoice once existed; no evidence in this snapshot establishes why the header is missing. Proposed treatment: retain both rows unresolved, obtain the original invoice/void approval, and do not create a replacement debt or delete either row automatically. This is separate from the 24 noncash-expense classifications and from the 479 registration candidates.

The additional 21 current cash-report matches were also checked against invoice title, date, timestamp and actor, as well as exact reference/amount/institute. Their detailed evidence is retained under `additional_21_evidence` in the proposal artifact. They still require separate owner review of the full reporting effect; review of the original 24 is not authorization for all 45.
