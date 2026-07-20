# Cloud SQL IAM authentication and local clone workflow

## 1. Production/application connector settings

The application supports an in-process Cloud SQL Python Connector mode. Configure
the deployed service with:

```text
DB_TYPE=mysql
DB_CONNECTION_MODE=cloud-sql-connector
CLOUD_SQL_CONNECTION_NAME=global-it-edu-app:asia-south1:attn-billing-testing-db
CLOUD_SQL_ENABLE_IAM_AUTH=true
CLOUD_SQL_IAM_PRINCIPAL=644631083795-compute@developer.gserviceaccount.com
CLOUD_SQL_IP_TYPE=PUBLIC
MYSQL_DB=attn_billing_testing
```

Use `CLOUD_SQL_IP_TYPE=PRIVATE` when the runtime has VPC access to the instance's
private address. `MYSQL_PASSWORD`, `MYSQL_HOST`, and `MYSQL_PORT` are not used in
connector mode. The code explicitly calls the connector with
`enable_iam_auth=True` and derives the MySQL login `644631083795-compute` from the
full IAM principal. Cloud SQL registers the full email, but MySQL accepts the
truncated database username.

## 2. Clone the testing instance

Select the project and inspect the source before making the copy:

```powershell
gcloud config set project global-it-edu-app
gcloud sql instances describe attn-billing-testing-db --format="yaml(name,region,databaseVersion,settings.tier,settings.databaseFlags)"
gcloud sql instances clone attn-billing-testing-db attn-billing-local-test-db
gcloud sql operations list --instance=attn-billing-local-test-db --limit=5
```

The clone is a separate billable Cloud SQL instance. Delete it when testing is
finished:

```powershell
gcloud sql instances delete attn-billing-local-test-db
```

If clone is unavailable for the source configuration, use backup/restore:

```powershell
gcloud sql backups create --instance=attn-billing-testing-db --description="local IAM test copy"
gcloud sql backups list --instance=attn-billing-testing-db --limit=5
# Create a compatible empty target instance using the source's version/tier/region,
# then substitute BACKUP_ID below.
gcloud sql backups restore BACKUP_ID --restore-instance=attn-billing-local-test-db --backup-instance=attn-billing-testing-db
```

## 3. IAM and database prerequisites

```powershell
gcloud services enable sqladmin.googleapis.com
gcloud projects add-iam-policy-binding global-it-edu-app --member="serviceAccount:644631083795-compute@developer.gserviceaccount.com" --role="roles/cloudsql.client"
gcloud projects add-iam-policy-binding global-it-edu-app --member="serviceAccount:644631083795-compute@developer.gserviceaccount.com" --role="roles/cloudsql.instanceUser"
gcloud sql users create 644631083795-compute@developer.gserviceaccount.com --instance=attn-billing-local-test-db --type=cloud_iam_service_account
```

Check the instance flag separately:

```powershell
gcloud sql instances describe attn-billing-local-test-db --format="yaml(settings.databaseFlags)"
```

If `cloudsql_iam_authentication=on` is absent, enable it in **Cloud SQL > Edit >
Flags**. Alternatively use `gcloud sql instances patch --database-flags=...`, but
include every existing flag shown by the preceding command: that option replaces
the complete flag list rather than merging one flag and can restart the instance.

Adding the IAM database user does not grant table access. Connect once as an
existing administrator and grant only the privileges the application needs:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE
ON attn_billing_testing.* TO '644631083795-compute'@'%';
```

Confirm the source and clone both have `cloudsql_iam_authentication=on`; flags and
IAM database users should be checked after every clone/restore. Also ensure the
runtime principal is exactly the principal configured as the database user and
that outbound TCP 443 and 3307 are allowed. A private-IP-only instance additionally
requires a local/VPN/VPC network path; the Auth Proxy does not create one.

## 4. Run the application locally through the Auth Proxy

Create ADC for the same service account used as the IAM database identity:

```powershell
gcloud auth application-default login --impersonate-service-account=644631083795-compute@developer.gserviceaccount.com
Copy-Item .env.cloudsql.example .env.cloudsql
docker compose --profile cloudsql -f docker-compose.yml -f docker-compose.cloudsql.yml up --build
```

The web container connects to `cloud-sql-proxy:3306`. The proxy is also published
as `localhost:3307` for desktop clients. The `--auto-iam-authn` flag supplies and
refreshes IAM login tokens, so `MYSQL_PASSWORD` stays empty.

If Docker Desktop does not expand `%APPDATA%` as expected, set the mount explicitly:

```powershell
$env:GCLOUD_CONFIG_DIR = "$env:APPDATA\gcloud"
docker compose --profile cloudsql -f docker-compose.yml -f docker-compose.cloudsql.yml up --build
```

For a JSON key instead of ADC, mount it read-only into the proxy container and add
`--credentials-file=/secrets/key.json` to its command. ADC with service-account
impersonation is preferred because it avoids a long-lived key.
