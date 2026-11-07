# Global IT ERP

Flask ERP for student registration, billing, attendance, classroom teaching,
certificates and student notifications, with live Cashfree payments.

## Project layout

| Path | Purpose |
| --- | --- |
| `app.py`, `config.py`, `db.py` | Application setup, environment configuration and database access |
| `modules/` | Flask blueprints and application routes |
| `services/` | Shared business logic, payment verification and tenant helpers |
| `templates/`, `static/` | Jinja templates and frontend assets |
| `migrations/` | Versioned MySQL schema changes |
| `tests/`, `scripts/` | Regression checks and operational entry points |
| `deploy/releases/` | Archived build configurations for individual releases |
| `ops/` | Deployment and operations helpers |

## Local setup and testing

Use Python 3.12 and install the dependencies from `requirements.txt` in a virtual
environment. Keep local credentials in ignored `.env` files. The Angular Smart
Counselling frontend has its own package files under `frontend/smart-counselling/`.

See [local Cloud SQL testing](CLOUD_SQL_LOCAL_TESTING.md) and the Docker Compose
files for the project's database and container setup. Regression tests use
synthetic data; the opt-in MySQL payment tests create a disposable database server.

```powershell
python -m pytest tests/test_cashfree_payments.py tests/test_student_payment_links.py -q
node --test tests/cashfree_checkout.test.cjs
```

## Deployment

The root `Dockerfile`, `cloudbuild.yaml` and `cloudbuild.staging.yaml` are the full
application build entry points. Follow [the deployment runbook](STAGING_DEPLOYMENT.md)
and [the Cashfree release notes](docs/CASHFREE_PRODUCTION_RELEASE.md) for candidate
verification, migrations and production settings. MySQL migrations run separately
from a Cloud Run deployment.

Individual release build files are retained under
[`deploy/releases/`](deploy/releases/README.md) for reproducibility. Their build
context remains the repository root.

## Local files and credentials

Environment files, service-account credentials, database dumps, generated student
files, caches, disposable test databases and local release worktrees are excluded
from commits or deployment uploads as appropriate. SQL migrations remain tracked.
Private release evidence in `scratch/cashfree-production-release/` stays local.
