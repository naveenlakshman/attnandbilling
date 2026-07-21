# Phase 10 deployment record

Date: 2026-07-21  
Project: `global-it-edu-app`  
Region: `asia-south1`  
Service: `attn-billing-testing`  
Domain: `https://www.globaliterp.com`

## Deployed release

- Revision: `attn-billing-testing-phase10-0721-2006`
- Image: `asia-south1-docker.pkg.dev/global-it-edu-app/cloud-run-source-deploy/attn-billing-testing:phase10-20260721-2006`
- Digest: `sha256:9feec4615e74c7a03ef2914202af94aa58b991936fd92137d154fa5fa84f1275`
- Cloud Build: `d0e07401-a791-4f5e-b212-3e72d2608718`
- Traffic rollout: 0% → 5% → 25% → 50% → 100%
- Rollback revision: `attn-billing-testing-desc-07211645`

## Database

- Instance: `attn-billing-testing-db`
- Database: `attn_billing_testing`
- Applied migrations:
  - `20260721_lms_assignment_latest_review_index.sql`
  - `20260721_lms_assignment_grading_rules.sql`
- Private logical backup: `gs://global-it-erp-db-backups/phase10-post-migration-20260721.sql`
- Verified backup size: 17,188,102 bytes

## Verification

- Phase 0–9 Docker/MySQL suites: passed
- `/healthz`: HTTP 200
- `/login`: HTTP 200
- Unauthenticated `/lms_admin/master/reviews`: HTTP 302 to login
- Authenticated sidebar API observed on candidate: HTTP 200
- Candidate HTTP 5xx, traceback, PyMySQL, and severity-error logs during rollout: none found

## Rollback

```powershell
gcloud run services update-traffic attn-billing-testing `
  --project=global-it-edu-app `
  --region=asia-south1 `
  --to-revisions="attn-billing-testing-desc-07211645=100"
```

The Phase 9 migration is additive, so the previous application revision remains compatible with the migrated schema.

## Remaining release follow-ups

- Complete manual tablet/mobile viewport QA.
- Replace public GCS delivery for student/assignment files with private signed or authenticated delivery, then remove `allUsers: roles/storage.objectViewer` from `global-it-erp-storage`.
