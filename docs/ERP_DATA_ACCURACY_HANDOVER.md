# ERP data accuracy handover — 7 November 2026

Owner decision package: [ERP-ACCURACY-20261107-R1](ERP_ACCURACY_OWNER_RELEASE_PACKAGE.md), with all 45 exclusions, monthly/period/lifetime cash-report impact, staff instructions and exact conditional approval scope. Preparing the package grants no approval.

Development changes only. No deployment, production migration, historical correction or production row mutation was performed.

## Implemented behavior

- Tenant-scoped detailed student/lead exports, daily CSV and related table exports. Daily branch selection is checked against the active institute.
- One signed invoice balance definition and derived installment balances in `services/finance_ledger.py`. Installment caches and stale paid/write-off statuses cannot suppress remaining collectible dues.
- Noncash write-offs no longer create cash expenses. Existing precisely linked write-off expenses are excluded from dashboard cash expense calculations without changing the stored entries. Unmatched older expenses remain review items.
- Cancelled invoices are excluded from current sales/dues. Actual cash receipts remain cash movements; cancellations and refunds appear as separate events in accuracy reports.
- Null invoice branches have a separate Unresolved choice and are never included in every selected branch.
- Separate course admissions preserve student, course snapshot/version, admission date, origin branch, original creator, source/importer and status. Native new DFA purchases create one admission with Basics and Tally modules.
- Invoice creation requires an explicit booking branch and new-purchase/existing-admission choice; it does not infer new admission origin from the student training branch. Multiple invoices may share an admission; each multi-course invoice item has its own link. Historical invoices are not converted into admissions automatically.
- Dated module/batch assignments snapshot training branch and trainer. Transfers and completion retain assignment episodes and the original legacy joined date. Legacy enrollment/move/status operations redirect linked admissions to the dated workflow rather than bypassing it.
- Source payments record collection branch, channel, method, reference, payment date, posting timestamp and creator. Receipts remain invoice allocations. Unallocated amounts are advances; allocation retries and advance refunds have durable records.
- Advance allocations have their own effective dates; later allocations do not reduce an earlier outstanding cutoff or erase earlier unallocated money.
- Manual payment requests are serialized at invoice/payment level and protected by request keys and structured reference uniqueness. Gateway verification retains existing protections, adds collection metadata and uses the gateway timestamp when an offset-qualified timestamp is available. Otherwise its date is explicitly labelled posting_fallback; online location stays unresolved.
- Posted invoice/receipt edits redirect to the correction workspace instead of overwriting values. Fee reductions, cancellations, receipt corrections, write-off reversals, refunds and adjustment reversals retain original records and audit events.
- Refund payout branch/channel/reference are supplied separately; absent details are unresolved rather than inferred from the original receipt.
- Installment date corrections require a reason and preserve earlier due dates for historical aging. Single-installment editing cannot silently change the fee.
- Refunds are ledger records; this release does not send money through Cashfree or a bank.

## Screens and interfaces

Admin workspace: `/accuracy/`. The existing Reports dashboard links here.

`POST /accuracy/action` supports admission, correct_admission, link_item, assignment, close_assignment, payment, allocate, return_advance and adjustment operations. HTML forms and JSON requests share the same transactional services. The normal application CSRF and subscription checks still apply. This workspace and its correction/report endpoints are admin-only; the existing manual receipt screen remains available to authorized staff.

Reports: `/accuracy/reports/<kind>`, with `start`, `end`, `cutoff`, `branch` (including unresolved), and `format=json|csv`:
- admissions
- sales
- collections
- origin-collections
- outstanding
- training
- writeoffs-posted
- writeoffs-cohort

All show date range, effective-date cutoff, branch/tax/cancellation basis and incomplete-month status. Money in JSON is integer paise; HTML and CSV show INR. Allocations use the existing largest-remainder algorithm, so multi-course totals reconcile without multiplying child joins.

Sales show original invoice amounts after discounts plus separately dated charge adjustments. Do not subtract discount_amount from total_amount again. Posted write-offs and admission-cohort lifetime write-offs are separate reports. Equal timestamps are ordered by a durable per-entity event sequence. Unlinked admission cohorts are explicitly unresolved, with an invoice-date fallback labelled as such.

Cash-position dashboards include advances, refunds and receipt corrections once, using collection location; historical locations stay unresolved. Current invoice dashboard views are labelled separately from historical accuracy reports. Backdated entries can restate an effective-date report; recorded timestamps and audit history preserve when the entry was made. The system cannot reconstruct edits made before this release from data that no longer exists. Full financial period closing is not introduced.

Training workload reports measure topic events and assigned calendar days, not invented teaching hours. Existing LMS progress records are reused. Historical progress deleted before this release cannot be reconstructed.

## Current release verification

The earlier 381-test/MySQL-9.4 handover and INR 28,700 dues claim are superseded by [the completed release verification](ERP_DATA_ACCURACY_RELEASE_VERIFICATION.md). The required engine is now verified locally as MySQL **8.0.45**, matching production's 8.0.45-google patch level and SQL modes.

Final results: **416 passed, no skips** in the full Python suite; **223 passed** in the affected suite; **17 passed** in checkout JavaScript. MySQL integration fixtures enforce the exact version. The source fingerprint and JUnit evidence are linked in the verification report. SQLite-specific tests remain SQLite tests; critical financial cases also run on disposable MySQL 8.0.45.

The migration was repeated on the isolated current production clone. All 23 existing tables retained their row counts and hashes. The **12 new tables, 111 column definitions and 29 indexes** were compared with a fresh database created by the shipped SQL: types, nullability, defaults, collations, engines, keys and index definitions match. Integration tests retain newly written history after repetition. IF NOT EXISTS cannot repair a malformed existing table or make DDL transactional. Fresh read-only production metadata inspection confirms all 12 accuracy tables remain absent.

| Dataset / definition — institute 1 | Verified amount |
|---|---:|
| July backup visible dues | INR 2,39,867 to INR 2,53,192; **increase INR 13,325** |
| Current snapshot visible dues | INR 2,23,747 to INR 2,26,822; **increase INR 3,075** |
| Current positive outstanding | **INR 2,26,822** |
| Current credit, separately visible | **INR 4,575** |

The superseded INR 28,700 candidate increase included INR 15,375 of phantom dues from oversized installment schedules. The capped calculation removes them. The verification report explains each invoice. All 561 current Global IT invoice balances reconcile across ledger, installment SQL, payment links, reminder selections, invoice screens and exports. Credit is never netted against another invoice's debt. There are no unexplained monetary differences on the fixed snapshot.

CSV receipt imports preserve and validate collection branch, channel, payment date and structured reference. Identical replay is idempotent; failed rows roll back atomically. Historical unknowns stay unknown. Undated receipt money remains in current balances and is disclosed separately from dated collection totals. The verification report includes the admission/receipt creation-path matrix, gateway timestamp/fallback behavior and import provenance. The tenant all-table export now excludes global/unknown ownership tables and validates both attendance ownership paths.

## Historical corrections: separate review

[The correction proposal](ERP_ACCURACY_DATA_CORRECTION_PROPOSAL.md) reviews all 24 original expense IDs. They total INR 1,50,890; the April-onward portion is INR 1,46,315. Current data has 45 exact matches totalling INR 2,57,442, so the complete read-only cash-report filter changes lifetime expense inclusion from INR 10,68,934 to INR 8,11,492. This reporting effect is separate from stored-record correction, actual cash and invoice dues. Review the extra 21 matches and total effect before promotion.

GIT/B/281 has two distinct INR 4,575 write-offs and an existing INR 4,575 credit. Retain both pending original approval/source-document review; do not automatically reverse one or issue a refund. Every one of the **479 original registrations remains unresolved**, with proposed=null and apply=false. No admission origins or historical collection branches were inferred. Invoice item 800 and installment 496, each INR 8,500, reference missing invoice 449; this pre-existing orphan pair is preserved and left for separate source review, with zero reporting delta.

## Browser verification

All requested browser checks passed. The 13 screenshots and scenario results are in [the verification matrix](ERP_DATA_ACCURACY_RELEASE_VERIFICATION.md#browser-evidence). Browser checks use synthetic institutes 7 and 8 in a loopback MySQL database, actual templates/blueprints/CSRF, fixture login identities and a fixture permission-denial landing page. SMS and portal provisioning are blocked; no real payment is made. The production clone is only used for read-only offline reconciliation.

## Exact deployment procedure — not executed

Deployment and production data changes remain **on hold**. The commands below are a future runbook for a separately authorized release. They do not authorize historical corrections.

1. Review the final source diff, separate correction proposal, complete cash-report effect and unresolved credit. Create the approved Git commit and record it alongside the tested source manifest. Changes to application code invalidate the test fingerprint and require renewed affected/full tests. Keep snapshots and screenshots in ignored scratch paths; upload-list preflight verified their exclusion.
2. Refresh the read-only snapshot and same-dataset reconciliation immediately before release. Verify a successful Cloud SQL backup/PITR restore point, engine version and prerequisites: finance tenant ownership, write-off references and document numbering. Compare any existing accuracy tables with the expected manifest.
3. Capture the actual active traffic split and current runtime configuration privately. Latest-ready revision alone does not identify active traffic:

```powershell
$erpProject = 'global-it-edu-app'
$erpRegion = 'asia-south1'
$erpService = 'global-it-erp-production'
$erpReleaseDir = Join-Path (Get-Location) 'scratch/erp-accuracy-review/release-verification'
$erpServiceBefore = gcloud run services describe $erpService --project=$erpProject --region=$erpRegion --format=json | ConvertFrom-Json
$erpTrafficBefore = @($erpServiceBefore.status.traffic | Where-Object { $_.percent -gt 0 })
$erpTrafficBefore | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $erpReleaseDir 'traffic-before.json')
gcloud sql backups list --project=$erpProject --instance=global-it-erp-production-db --limit=5
```

4. Build and run the established container checks **without deploying**. Stock `cloudbuild.yaml` replaces environment/secrets settings in its deployment step. Use a build-only copy and later update only the image, preserving current payment, tenant, network and secret-reference configuration:

```powershell
if (git status --porcelain) { throw 'Commit the reviewed release before building' }
$erpApprovedCommit = (git rev-parse HEAD).Trim()
$erpTag = 'accuracy-' + $erpApprovedCommit.Substring(0,12)
$erpBuildOnly = [regex]::Replace((Get-Content cloudbuild.yaml -Raw),'(?s)\r?\n  - id: deploy-zero-traffic.*?(?=\r?\nimages:)','')
if ($erpBuildOnly -match 'deploy-zero-traffic') { throw 'Build-only config still contains deployment' }
$erpBuildFile = Join-Path $erpReleaseDir 'cloudbuild-accuracy-build-only.yaml'
[IO.File]::WriteAllText($erpBuildFile,$erpBuildOnly,[Text.UTF8Encoding]::new($false))
gcloud builds submit --project=$erpProject --config=$erpBuildFile --substitutions="_IMAGE_TAG=$erpTag"
$erpImage = 'asia-south1-docker.pkg.dev/global-it-edu-app/cloud-run-source-deploy/global-it-erp-production:' + $erpTag
$erpDigest = (gcloud artifacts docker images describe $erpImage --project=$erpProject --format='value(image_summary.digest)').Trim()
if (-not $erpDigest.StartsWith('sha256:')) { throw 'Resolve the immutable image digest before deploy' }
$erpImmutableImage = 'asia-south1-docker.pkg.dev/global-it-edu-app/cloud-run-source-deploy/global-it-erp-production@' + $erpDigest
```

Do not continue after a failed container check. The build and candidate steps have not run during local verification.

5. Apply `migrations/20261107_erp_data_accuracy.sql` once through the existing authenticated Cloud SQL proxy connection, with explicit database/version guards. Cloud Run does not apply MySQL migrations. Run the following **only in the separately authorized migration window**. It creates additive tables and performs no historical DML:

```powershell
@'
from pathlib import Path
import json
from ops.cashfree_production_release import database_connection
from db import MySQLConnectionWrapper
from scripts.verify_erp_accuracy_release import required_schema
expected=json.loads(Path('scratch/erp-accuracy-review/release-verification/final-schema-verification.json').read_text())['required_schema']
with database_connection() as raw:
    with raw.cursor() as cur:
        cur.execute('SELECT DATABASE() db,VERSION() version')
        info=cur.fetchone()
        assert info['db']=='global_it_erp_production' and info['version'].startswith('8.0.45')
        for statement in Path('migrations/20261107_erp_data_accuracy.sql').read_text().split(';'):
            if statement.strip():cur.execute(statement)
    raw.commit()
    assert required_schema(MySQLConnectionWrapper(raw))==expected
print('Required accuracy schema verified')
'@ | .\.venv\Scripts\python.exe -
```

Stop and review any table/column/index mismatch. MySQL DDL auto-commits; failure can leave a partial additive schema. Resolve forward rather than dropping tables. Reconcile fresh pre/post data, explaining legitimate intervening transactions by stable IDs.

6. Deploy a tagged zero-traffic candidate using only image/revision/tag flags so the current runtime configuration is retained:

```powershell
gcloud run deploy $erpService --project=$erpProject --region=$erpRegion --image=$erpImmutableImage --revision-suffix=$erpTag --tag=$erpTag --no-traffic
$erpServiceAfter = gcloud run services describe $erpService --project=$erpProject --region=$erpRegion --format=json | ConvertFrom-Json
$erpCandidate = $erpServiceAfter.status.traffic | Where-Object { $_.tag -eq $erpTag }
if (-not $erpCandidate.url) { throw 'Tagged candidate URL missing' }
Invoke-WebRequest ($erpCandidate.url + '/healthz') -UseBasicParsing
```

Compare environment names/values, secret versions, service account, Cloud SQL attachment, network/egress and traffic split with the baseline without printing secrets. Check authentication, permissions, two institutes, reports, exports, old invoices, remaining dues, separate credits and logs. Production candidate smoke checks are read-only; write scenarios belong in the isolated fixture. Reconcile a fresh snapshot and identify intervening real invoice/receipt IDs. Do not backfill history.

7. Promote only after candidate verification, the complete cash-report effect and deployment have been reviewed and authorized:

```powershell
gcloud run services update-traffic $erpService --project=$erpProject --region=$erpRegion --to-revisions="$($erpCandidate.revisionName)=100"
```

Monitor errors, callback duplicates/reviews, balances, unknown locations and receipt counts. Retain the previous image and traffic split. Historical reclassification remains a separate operation.

## Rollback limitations

Before accuracy writes occur, restore the recorded traffic split while leaving additive tables intact:

```powershell
$erpPriorWeights = ($erpTrafficBefore | ForEach-Object { "$($_.revisionName)=$($_.percent)" }) -join ','
gcloud run services update-traffic $erpService --project=$erpProject --region=$erpRegion --to-revisions=$erpPriorWeights
```

After adjustments, reversals, advances or allocation events exist, an older app cannot interpret the complete ledger. An image-only rollback followed by resumed billing can misstate debt or cash. Pause financial posting with coordinated gateway retry handling; preserve all event/audit tables and use a forward fix or reviewed compatibility reader. A compatibility reader is not delivered here. Do not delete tables, bulk-reverse records, or restore a backup without reconciling/replaying subsequent receipts and gateway orders. DDL is not transactionally reversible. Rollback does not authorize historical corrections.

## Reproduction

Use an isolated Oracle MySQL 8.0.45 installation. Fixtures create their own databases/servers and verify the version; they never use configured ERP credentials:

```powershell
$env:PATH=(Resolve-Path 'scratch/erp-accuracy-review/release-verification/runtime/mysql-8.0.45-winx64/bin').Path+';'+$env:PATH
$env:APP_ENV='testing'
$env:SECRET_KEY='release-verification-only'
$env:DB_TYPE='sqlite'
$env:ERP_RUN_MYSQL_TESTS='1'
$env:CASHFREE_RUN_MYSQL_TESTS='1'
$env:ERP_MYSQL_EXPECTED_VERSION='8.0.45'
$erpTestDir=Join-Path (Get-Location) ('scratch/accuracy-tests-'+[guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest tests scripts/test_bad_debt_installment_reversal.py -q -p no:cacheprovider --basetemp $erpTestDir --disable-warnings
node --test tests/cashfree_checkout.test.cjs
```

The SQLite setting serves SQLite-specific unit tests. MySQL-backed release cases explicitly choose disposable MySQL connections.

## Recommendation

**READY for the controlled software release process and review**, with no remaining local development/test blockers. Production promotion remains gated on explicit authorization, container/candidate checks, a refreshed reconciliation and review of the complete cash-report effect. Deployment and historical corrections remain on hold.
