# Global IT ERP Google Cloud deployment runbook

This is the standard release process for future Global IT ERP development. It
covers local verification, Git, staging, production, database migrations,
traffic promotion, monitoring, and rollback.

The default rule is:

> Commit and test first, deploy to a zero-traffic revision, verify that exact
> revision, and only then move customer traffic.

Never deploy an unreviewed working directory directly to production.

## 1. Environment inventory

| Purpose | Staging | Production |
|---|---|---|
| Google Cloud project | `global-it-erp-staging` | `global-it-edu-app` |
| Region | `asia-south1` | `asia-south1` |
| Cloud Run service | `global-it-erp-staging` | `global-it-erp-production` |
| Artifact Registry repository | `cloud-run-source-deploy` | `cloud-run-source-deploy` |
| Cloud SQL instance | `global-it-erp-staging-db` | `global-it-erp-production-db` |
| Database | `global_it_erp_staging` | `global_it_erp_production` |
| Runtime service account | `attn-billing-staging-runtime@global-it-erp-staging.iam.gserviceaccount.com` | `attn-billing-runtime@global-it-edu-app.iam.gserviceaccount.com` |
| Public domain | `https://staging.globaliterp.com` | `https://www.globaliterp.com` |
| Platform-control domain | Staging Cloud Run/control host | `https://admin.globaliteducation.com` |
| Cloud Storage | `gs://global-it-erp-staging-storage` | `gs://global-it-erp-storage` |

Current Cloud Run sizing is 1 CPU, 1 GiB memory, concurrency 10, and a
120-second request timeout. A normal application deployment must preserve the
existing runtime configuration unless the change request explicitly includes
infrastructure changes.

## 2. Important repository warnings

### 2.1 Do not run the production YAML without reviewing it

The current `cloudbuild.yaml` still defaults to the historical service
`attn-billing-testing`. The live service is `global-it-erp-production`. Running
that file without correct substitutions can deploy the wrong service or apply
stale environment variables.

For production, use the explicit image-build and Cloud Run commands in this
runbook until `cloudbuild.yaml` is formally reconciled and reviewed.

### 2.2 Cloud Build source is controlled by `.gcloudignore`

The repository excludes credentials, local environment files, database dumps,
the local LMS static tree, and `scratch/`. The current Cloud Build YAML files
reference some tests under `scratch/`, so a config-driven build may fail unless
those tests are moved to an included test directory or the ignore rules are
deliberately updated.

Before every build, inspect the source set:

```powershell
gcloud meta list-files-for-upload
```

Never weaken `.gcloudignore` to upload `.env`, `gcp-key.json`, private keys,
database dumps, or local student files.

## 3. Required access and workstation setup

Each release engineer needs:

- Git access to the project repository.
- Google Cloud CLI installed and authenticated.
- Access to the staging project.
- Production access only for approved release engineers.
- Docker Desktop for local MySQL/Redis/application testing.
- Permission to use Cloud Build, Artifact Registry, Cloud Run, Logging, and
  Secret Manager.
- Cloud SQL access only when a reviewed migration is part of the release.

Authenticate and select the correct account:

```powershell
gcloud auth login
gcloud auth list
```

Do not rely on a permanently configured default project. Every release command
in this runbook includes `--project` and `--region` explicitly.

Confirm the CLI identity before a production action:

```powershell
gcloud config list account
```

## 4. Development and Git requirements

Create changes on the team development branch or a feature branch. Do not make
unrelated edits part of the same release.

Before committing:

```powershell
git status --short
git diff --check
git diff --stat
git diff
```

Review every modified and untracked file. Existing unrelated changes belong to
their author and must not be staged, reverted, or deployed accidentally.

Stage only the intended files:

```powershell
git add -- path/to/file1.py path/to/file2.html scripts/test_feature.py
git commit -m "fix: concise description of the change"
git push origin feature/multi-institute-phase2
```

Record the commit ID used for the release:

```powershell
$commit = git rev-parse --short HEAD
$commit
```

The image tag and revision suffix must contain this commit ID. This makes every
running revision traceable to source code.

## 5. Mandatory local verification

### 5.1 Compile changed Python modules

```powershell
python -m py_compile modules/path/routes.py services/path.py
```

### 5.2 Run targeted regression tests

Every bug fix or core feature must include or identify a regression test:

```powershell
python scripts/test_feature_name.py
```

For tenant-sensitive code, the test must cover at least:

- The intended institute can read and update its own record.
- Another institute cannot read, update, grade, or delete it.
- Direct object-ID requests do not bypass tenant scope.
- Filter dropdowns contain only current-institute users, branches, batches,
  courses, and programs.
- Admin and staff authorization paths are both tested when applicable.

### 5.3 Build and run the local Docker stack

```powershell
docker compose build web
docker compose up -d web
docker compose ps
```

The `web`, `local-db`, and `redis` containers must be running, and `web` and
`local-db` must become healthy.

Check the local login endpoint and recent errors:

```powershell
curl.exe -sS -o NUL -w "HTTP=%{http_code}`n" http://localhost:8080/login
docker compose logs web --since 10m | Select-String -Pattern "Traceback|ERROR|Exception" -Context 0,3
```

Use a browser to verify the changed workflow, responsive layout, permissions,
and form submission. A successful build alone does not verify business logic.

### 5.4 Release gate

Do not continue if any of these are true:

- A test fails.
- Python compilation fails.
- Docker is unhealthy.
- The change has no tenant-scope analysis.
- The worktree contains unclear changes.
- A migration has not been reviewed and backed up.
- The rollback revision is unknown.

## 6. Database migration policy

Application deployment and database migration are separate release actions.
Do not assume Cloud Run automatically applies files under `migrations/`.

Every migration must:

- Be committed under `migrations/`.
- Have a date-prefixed, descriptive filename.
- Be tenant-safe.
- Be idempotent when practical.
- Preserve data and avoid destructive table rebuilds without explicit approval.
- Be tested against local MySQL, not only SQLite.
- Include a compatibility and rollback assessment.
- Avoid printing database passwords in terminals or logs.

Example filename:

```text
migrations/20260804_feature_description.sql
```

### 6.1 Test a migration locally

Run it against the Docker MySQL instance using credentials already injected
into the database container. Do not copy passwords into the command history:

```powershell
Get-Content -Raw migrations/20260804_feature_description.sql |
  docker compose exec -T local-db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

Run the migration twice when it is intended to be idempotent.

### 6.2 Production migration sequence

For production data changes:

1. Identify the current production revision and rollback revision.
2. Take or verify an appropriate Cloud SQL backup/export.
3. Record backup location and size.
4. Apply the migration using an approved, authenticated connection.
5. Verify schema and row counts with read-only queries.
6. Deploy a compatible zero-traffic application revision.
7. Promote traffic only after migration and candidate verification succeed.

If the new schema is not backward-compatible, a normal application rollback
may not be safe. Document the database rollback procedure before deployment.

## 7. Deploy to staging first

Staging must use staging data, secrets, Cloud SQL, Redis, storage, service
accounts, and domains. Never substitute production resources into staging.

Set release variables in PowerShell:

```powershell
$stagingProject = "global-it-erp-staging"
$region = "asia-south1"
$stagingService = "attn-billing-staging"
$repository = "cloud-run-source-deploy"
$commit = git rev-parse --short HEAD
$releaseName = "feature-$commit"
$stagingImage = "$region-docker.pkg.dev/$stagingProject/$repository/$stagingService`:$releaseName"
```

Build and publish the exact working tree:

```powershell
gcloud builds submit `
  --project=$stagingProject `
  --tag=$stagingImage `
  .
```

Create a zero-traffic staging revision while preserving the service's existing
configuration:

```powershell
gcloud run deploy $stagingService `
  --project=$stagingProject `
  --region=$region `
  --platform=managed `
  --image=$stagingImage `
  --revision-suffix=$releaseName `
  --no-traffic
```

Confirm it is ready:

```powershell
gcloud run revisions describe "$stagingService-$releaseName" `
  --project=$stagingProject `
  --region=$region `
  --format="value(status.conditions)"
```

Assign a temporary candidate tag:

```powershell
gcloud run services update-traffic $stagingService `
  --project=$stagingProject `
  --region=$region `
  --set-tags="candidate=$stagingService-$releaseName" `
  --quiet
```

The command prints a tagged candidate URL. Test login, changed pages, database
operations, Redis-dependent functions, uploads/downloads, authorization, and
tenant isolation. Because tenant routing depends on the hostname, test both the
candidate URL and the actual staging domain after promotion.

Promote staging when verification passes:

```powershell
gcloud run services update-traffic $stagingService `
  --project=$stagingProject `
  --region=$region `
  --to-revisions="$stagingService-$releaseName=100" `
  --quiet
```

After testing `https://staging.globaliterp.com`, remove the temporary tag:

```powershell
gcloud run services update-traffic $stagingService `
  --project=$stagingProject `
  --region=$region `
  --remove-tags=candidate `
  --quiet
```

Production promotion requires staging sign-off from the feature owner or
release reviewer.

## 8. Production deployment

### 8.1 Capture the rollback revision

```powershell
$prodProject = "global-it-edu-app"
$region = "asia-south1"
$prodService = "global-it-erp-production"
$repository = "cloud-run-source-deploy"

gcloud run services describe $prodService `
  --project=$prodProject `
  --region=$region `
  --format="table(status.traffic.revisionName,status.traffic.percent,status.traffic.tag)"
```

Copy the revision currently receiving 100% traffic into the release record.

### 8.2 Build an immutable production image

```powershell
$commit = git rev-parse --short HEAD
$releaseName = "feature-$commit"
$prodImage = "$region-docker.pkg.dev/$prodProject/$repository/$prodService`:$releaseName"

gcloud builds submit `
  --project=$prodProject `
  --tag=$prodImage `
  .
```

Save the Cloud Build ID and image digest from the output.

### 8.3 Deploy with zero traffic

```powershell
gcloud run deploy $prodService `
  --project=$prodProject `
  --region=$region `
  --platform=managed `
  --image=$prodImage `
  --revision-suffix=$releaseName `
  --no-traffic
```

This command updates only the image and revision while retaining the service's
current environment, secrets, network, Cloud SQL attachment, scaling, service
account, CPU, and memory settings.

Do not add `--set-env-vars`, `--set-secrets`, scaling, networking, or service
account flags to a normal application release. Those flags replace or change
runtime configuration and require a separate infrastructure review.

### 8.4 Verify the candidate revision

```powershell
$revision = "$prodService-$releaseName"

gcloud run revisions describe $revision `
  --project=$prodProject `
  --region=$region `
  --format="value(status.conditions)"
```

All readiness, container health, and resource conditions must be successful.

Create a temporary candidate tag:

```powershell
gcloud run services update-traffic $prodService `
  --project=$prodProject `
  --region=$region `
  --set-tags="candidate=$revision" `
  --quiet
```

For tenant-aware smoke tests, use the tagged URL with forwarded production host
headers. Replace the URL with the one printed by Google Cloud:

```powershell
$candidateUrl = "https://candidate---global-it-erp-production-m2nph2u57q-el.a.run.app"

curl.exe -sS -o NUL -w "LOGIN=%{http_code}`n" `
  -H "X-Forwarded-Host: www.globaliterp.com" `
  -H "X-Forwarded-Proto: https" `
  "$candidateUrl/login"

curl.exe -sS -o NUL -w "PROTECTED=%{http_code}`n" `
  -H "X-Forwarded-Host: www.globaliterp.com" `
  -H "X-Forwarded-Proto: https" `
  "$candidateUrl/dashboard"
```

Expected unauthenticated results are normally HTTP 200 for login and HTTP 302
to login for protected pages. A 200 response alone is insufficient: perform an
authenticated browser test of the changed workflow on staging and, when safe,
on the tagged production candidate.

Check candidate errors:

```powershell
gcloud logging read `
  "resource.type=\"cloud_run_revision\" AND resource.labels.revision_name=\"$revision\" AND severity>=ERROR" `
  --project=$prodProject `
  --freshness=30m `
  --limit=50 `
  --format="value(timestamp,textPayload,jsonPayload.message)"
```

Do not promote if logs contain HTTP 500 errors, tracebacks, database errors,
tenant-access violations, startup failures, or repeated timeouts.

### 8.5 Promote production traffic

For a low-risk fix with a fully verified candidate:

```powershell
gcloud run services update-traffic $prodService `
  --project=$prodProject `
  --region=$region `
  --to-revisions="$revision=100" `
  --quiet
```

For high-risk core changes, use a gradual rollout. Replace `$rollbackRevision`
with the previously active revision:

```powershell
$rollbackRevision = "previous-production-revision"

gcloud run services update-traffic $prodService `
  --project=$prodProject --region=$region `
  --to-revisions="$revision=5,$rollbackRevision=95" --quiet

gcloud run services update-traffic $prodService `
  --project=$prodProject --region=$region `
  --to-revisions="$revision=25,$rollbackRevision=75" --quiet

gcloud run services update-traffic $prodService `
  --project=$prodProject --region=$region `
  --to-revisions="$revision=50,$rollbackRevision=50" --quiet

gcloud run services update-traffic $prodService `
  --project=$prodProject --region=$region `
  --to-revisions="$revision=100" --quiet
```

At every stage, check functional behavior, latency, HTTP 5xx responses, database
errors, and logs before increasing traffic.

### 8.6 Verify the real domains

```powershell
curl.exe -sS -o NUL -w "LOGIN=%{http_code} TLS=%{ssl_verify_result}`n" `
  https://www.globaliterp.com/login

curl.exe -sS -o NUL -w "ADMIN=%{http_code} TLS=%{ssl_verify_result}`n" `
  https://admin.globaliteducation.com/login
```

`TLS=0` means certificate verification succeeded. Also verify the exact changed
page while authenticated with the correct role and institute.

Confirm final traffic and retained sizing:

```powershell
gcloud run services describe $prodService `
  --project=$prodProject `
  --region=$region `
  --format="table(status.traffic.revisionName,status.traffic.percent,status.traffic.tag,spec.template.spec.containerConcurrency,spec.template.spec.containers[0].resources.limits)"
```

Remove the temporary candidate tag:

```powershell
gcloud run services update-traffic $prodService `
  --project=$prodProject `
  --region=$region `
  --remove-tags=candidate `
  --quiet
```

## 9. Rollback procedure

Rollback is a traffic operation; rebuilding an old image is normally
unnecessary.

```powershell
gcloud run services update-traffic global-it-erp-production `
  --project=global-it-edu-app `
  --region=asia-south1 `
  --to-revisions="PREVIOUS_GOOD_REVISION=100" `
  --quiet
```

After rollback:

1. Confirm the previous revision has 100% traffic.
2. Test both production login domains.
3. Check logs for the restored revision.
4. Record the incident and failed revision.
5. Do not delete the failed revision until investigation is complete.

If a database migration was involved, follow its documented compatibility and
rollback plan. Do not reverse a migration by guessing SQL in production.

## 10. Log investigation commands

Recent revision errors:

```powershell
gcloud logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="global-it-erp-production" AND severity>=ERROR' `
  --project=global-it-edu-app `
  --freshness=1h `
  --limit=50 `
  --order=desc `
  --format="value(timestamp,resource.labels.revision_name,textPayload,jsonPayload.message)"
```

Requests for one path:

```powershell
gcloud logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="global-it-erp-production" AND httpRequest.requestUrl:"/path/to/page"' `
  --project=global-it-edu-app `
  --freshness=1h `
  --limit=30 `
  --order=desc `
  --format="table(timestamp,httpRequest.requestMethod,httpRequest.status,httpRequest.latency,trace)"
```

Use the trace ID from a failing request to correlate its application exception.
Never paste secrets, passwords, session cookies, or full personal records into
release notes or public issue trackers.

## 11. Secrets and credentials

- Secrets belong in Google Secret Manager.
- Never commit `.env`, `gcp-key.json`, service-account keys, passwords, or API
  keys.
- Never place a secret directly in `cloudbuild.yaml` or a deployment document.
- Refer to Secret Manager versions from Cloud Run configuration.
- Retrieve a secret only when required and remove temporary environment
  variables immediately afterward.
- Production and staging must use different secrets.
- Do not reuse staging administrator credentials in production.

The staging administrator password is available only to authorized staging
administrators:

```powershell
gcloud secrets versions access latest `
  --project=global-it-erp-staging `
  --secret=attn-billing-staging-admin-password
```

Do not copy the returned value into chat, source code, screenshots, or logs.

## 12. Post-deployment release record

Create or update a deployment record containing:

```text
Date and time (IST):
Feature/fix:
Git branch:
Git commit:
Reviewer/approver:
Staging revision:
Staging verification result:
Production project:
Production service:
Production revision:
Image URI and digest:
Cloud Build ID:
Previous/rollback revision:
Database migration(s):
Backup/export location:
Local tests:
Staging tests:
Production smoke tests:
Error-log result:
Traffic rollout stages:
Final traffic state:
Known follow-ups:
```

The release is complete only when the record is written, traffic is verified,
temporary tags are removed, and the worktree contains no unexplained changes.

## 13. Common failures

### Wrong service is being deployed

Stop immediately and inspect project, service, image URI, and substitutions.
Remember that the live production service is `global-it-erp-production`, not
the historical `attn-billing-testing` name.

### Candidate returns 404 on `/healthz`

Tenant/control-host middleware may reject an unfamiliar tagged hostname before
the health endpoint is reached. Check Cloud Run revision health and test with
the correct forwarded tenant host. Do not add temporary candidate domains to
production host allowlists as a routine release step.

### Protected page returns 302

For an unauthenticated smoke test, a redirect to `/login` is expected. Verify
the `Location` header. Use an authorized browser session for workflow testing.

### HTTP 403

Determine whether the response comes from application authorization, CSRF,
Cloud Armor, or tenant resolution. Do not disable security controls globally.

### HTTP 500

Find the exact request timestamp and trace, then query Cloud Run errors. The
browser's generic Internal Server Error page does not identify the root cause.

### Build context is unexpectedly large or slow

Inspect `.gcloudignore`, Docker build context, large untracked files, and local
assets. Do not upload `static/lms/`, dumps, virtual environments, or caches.

### Revision suffix already exists

Use a unique suffix containing the short commit and, when necessary, a short
sequence or timestamp. Cloud Run revision suffixes must remain concise.

## 14. Release checklist

### Before staging

- [ ] Scope and acceptance criteria are documented.
- [ ] Tenant isolation and role authorization were reviewed.
- [ ] Targeted regression test exists and passes.
- [ ] Changed Python files compile.
- [ ] Docker stack is healthy.
- [ ] Changed workflow was tested in a browser.
- [ ] `git diff --check` passes.
- [ ] Only intended files are committed.
- [ ] Commit is pushed to the remote branch.
- [ ] Migration and backup plans are ready, if applicable.

### Before production

- [ ] Staging passed and was approved.
- [ ] Production project/service names were rechecked.
- [ ] Current rollback revision was recorded.
- [ ] Image tag and revision contain the Git commit.
- [ ] Candidate revision is ready and container-healthy.
- [ ] Candidate workflow and permissions were verified.
- [ ] Candidate error logs are clean.
- [ ] Database migration verification passed, if applicable.

### After production

- [ ] Production domains and TLS pass.
- [ ] Authenticated changed workflow passes.
- [ ] HTTP 5xx/database/traceback logs are clean.
- [ ] Correct revision receives 100% traffic.
- [ ] CPU, memory, concurrency, service account, and secrets remain correct.
- [ ] Temporary candidate tag was removed.
- [ ] Release record was completed.
- [ ] Team was informed of the result and rollback revision.

## 15. Safety rules

- Never deploy directly to 100% traffic without a verified candidate.
- Never use production data in staging.
- Never change DNS, certificates, Cloud Armor, scaling, networking, secrets, or
  service accounts as an incidental part of an application release.
- Never delete old revisions as part of the deployment itself.
- Never apply unreviewed SQL to production.
- Never expose credentials in Git, build output, logs, documents, or chat.
- Never claim success until the real domain and new revision logs are verified.
