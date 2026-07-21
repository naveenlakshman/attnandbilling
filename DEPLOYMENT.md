# Local and production environments

The application uses `APP_ENV=development`, `testing`, or `production`. Production
starts only when its security requirements pass validation.

## Local Docker

1. Copy `.env.docker.example` to `.env.docker` and `.env.mysql.example` to
   `.env.mysql`, then replace every placeholder. Keep the application database
   password identical in both files.
2. Start Docker Desktop.
3. Run `docker compose up --build -d`.
4. Open <http://localhost:8080> and check
   `docker compose ps`.

The local web container connects to `local-db:3306`; MySQL is also exposed to the
host on `127.0.0.1:3308`. Local HTTP deliberately uses a non-secure cookie and does
not trust forwarded headers.

To stop the stack, run `docker compose down`. Adding `-v`
also deletes the local MySQL volume and must only be used when a full database reset
is intended. The separate MySQL environment file prevents unrelated application
secrets from being exposed to the database container.

## Production

Production is `https://www.globaliterp.com`, currently behind Cloudflare and Google.
Store production values in the deployment platform's secret manager; do not upload
an `.env` file or service-account JSON key. Use `.env.production.example` only as a
list of required settings.

Before deploying:

- use a random `SECRET_KEY` of at least 32 characters;
- set `APP_ENV=production`, `DEBUG_MODE=false`, and `SESSION_COOKIE_SECURE=true`;
- use Cloud SQL IAM authentication and a least-privilege service account;
- use a private GCS bucket and workload identity rather than `gcp-key.json`;
- configure a shared Redis-compatible `RATELIMIT_STORAGE_URI`;
- provide optional integration credentials only through secret storage;
- test the image and database migrations against staging first;
- retain the previous image revision for rollback.

Production startup fails closed if debug mode is enabled, secure cookies are disabled,
the secret key is weak, SQLite/local storage is selected, or rate limiting uses local
process memory.

## Credential rotation required

Credentials were previously present directly in source configuration. Rotate the
MySQL, SMS gateway, Google service-account, and third-party API credentials before the
next production deployment, even if the files are currently ignored by Git.
