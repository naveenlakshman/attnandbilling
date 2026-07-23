# Global IT ERP staging environment

This environment is test-only and must remain isolated from production.

- Project: `global-it-erp-staging`
- Region: `asia-south1`
- Cloud Run: `attn-billing-staging`
- Cloud SQL: `attn-billing-staging-db`
- Database: `attn_billing_staging`
- Domain: `staging.globaliterp.com`
- Temporary Cloud Run URL: `https://attn-billing-staging-nuls5dpt4a-el.a.run.app`
- Staging load-balancer IP: `34.110.175.66`
- Runtime identity: `attn-billing-staging-runtime@global-it-erp-staging.iam.gserviceaccount.com`
- Build identity: `attn-billing-staging-build@global-it-erp-staging.iam.gserviceaccount.com`
- Storage: `gs://global-it-erp-staging-storage`
- Redis: `attn-billing-staging-redis`

## Safety boundary

Never substitute `global-it-edu-app`, production service accounts, production
Cloud SQL instances, production buckets, or production secrets into the
staging deployment.

## Deploy a no-traffic candidate

Use a unique image tag and revision suffix:

```powershell
gcloud builds submit `
  --project=global-it-erp-staging `
  --region=asia-south1 `
  --service-account=projects/global-it-erp-staging/serviceAccounts/attn-billing-staging-build@global-it-erp-staging.iam.gserviceaccount.com `
  --config=cloudbuild.staging.yaml `
  --substitutions=_IMAGE_TAG=<commit-or-build-tag>,_REVISION_SUFFIX=<short-suffix>
```

The build deploys with `--no-traffic`. Verify `/healthz`, database access,
tenant resolution, login, Redis, and Cloud Storage before changing traffic.

## Retrieve the staging administrator password

The username is `staging_admin`. Authorized project administrators can retrieve
the generated password without storing it in source control:

```powershell
gcloud secrets versions access latest `
  --project=global-it-erp-staging `
  --secret=attn-billing-staging-admin-password
```

Do not reuse this account or password in production.

## Domain activation

Create this DNS record with the DNS provider authoritative for
`globaliterp.com`:

```text
Type: A
Name/Host: staging
Value: 34.110.175.66
TTL: 300
```

The Google-managed certificate remains in `PROVISIONING` until public DNS
resolves `staging.globaliterp.com` to that address. The staging-only load
balancer already has listeners for HTTPS and HTTP-to-HTTPS redirection.

## Cloud SQL free-trial limitation

The staging Cloud SQL instance is a Google Cloud free-trial instance. Google
rejects automated backup/PITR configuration for this instance type. Encrypted
connections and deletion protection are enabled. Upgrade the instance before
using automated backups; staging must never be treated as a source of durable
production data.
