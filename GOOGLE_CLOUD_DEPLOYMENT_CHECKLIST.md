# Google Cloud production deployment checklist

Target project: `global-it-edu-app`  
Target region: `asia-south1`  
Cloud Run service: `attn-billing-testing`  
Public domain: `https://www.globaliterp.com`

## Application and data compatibility

- [x] Fix and test the MySQL `DISTINCT` / `ORDER BY` submissions query.
- [ ] Build the production container locally.
- [ ] Verify `/healthz`, public pages, login pages, security headers, and secure cookies.
- [ ] Confirm GCS-backed upload paths do not rely on Cloud Run's ephemeral filesystem.

## Networking and shared rate limiting

- [ ] Inspect the current VPC and external HTTPS load balancer path.
- [x] Create a regional Memorystore Redis instance.
- [x] Configure Cloud Run Direct VPC egress to the Redis network.
- [x] Set `RATELIMIT_STORAGE_URI` and verify Redis connectivity from Cloud Run.

## Secrets and identity

- [x] Enable the Secret Manager API.
- [x] Migrate `SECRET_KEY`, database credentials, and third-party API credentials.
- [x] Pin Cloud Run secret environment references to explicit secret versions.
- [x] Create a dedicated Cloud Run runtime service account.
- [x] Grant only Cloud SQL Client, required GCS access, and secret access.
- [x] Remove runtime dependence on the default Compute Engine service account.

## Database protection

- [ ] Enable automated Cloud SQL backups (blocked: Free Trial instance rejects backup configuration).
- [ ] Configure a backup window and point-in-time recovery (blocked: Free Trial instance).
- [x] Enable Cloud SQL deletion protection.
- [x] Confirm the application database login still works from the dedicated runtime identity.

## Edge security and reproducibility

- [x] Restrict Cloud Run ingress to the existing external load balancer path.
- [x] Confirm `www.globaliterp.com` remains healthy through Cloudflare/load balancing.
- [x] Confirm the direct `run.app` URL is no longer an unintended bypass.
- [x] Add a versioned Cloud Build deployment workflow.

## Safe rollout

- [x] Build and push an immutable image tag.
- [x] Deploy a named revision with zero traffic.
- [x] Smoke-test the tagged revision without changing public traffic.
- [x] Shift a small traffic percentage and monitor errors/latency.
- [x] Gradually increase traffic to 100% only if checks remain healthy.
- [x] Retain the previous ready revision for immediate rollback.
