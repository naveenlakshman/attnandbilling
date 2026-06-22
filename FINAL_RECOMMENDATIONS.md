# Strategic & Operational Recommendations

This document outlines the final production deployment architecture, CI/CD pipeline structures, validation protocols, disaster recovery procedures, and system monitoring strategies for the migrated Django + MySQL ERP system.

---

## 1. Target Production Infrastructure Architecture

To ensure high availability, data security, and seamless scaling, we recommend a Dockerized cloud deployment layout:

```text
               Public Traffic (HTTPS)
                         │
                         ▼
             [ Cloud Load Balancer ]
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
[ Gunicorn / Django ]             [ Gunicorn / Django ]
(App Server Node 1)               (App Server Node 2)
        │                                 │
        └────────────────┬────────────────┘
                         ├──────────────────────────┐
                         ▼                          ▼
               [ MySQL Managed DB ]         [ Redis Cache Store ]
                (Primary Node)               (Rate Limiting & Session)
                         │
                         ▼
               [ Managed Replica ]
               (Reporting & Backup)
```

### Infrastructure Components:
1. **Application Servers**: Dockerized Django containers running behind **Gunicorn** app servers, managed by an orchestrator (e.g., AWS ECS, Google Cloud Run, or Kubernetes).
2. **Reverse Proxy & Load Balancer**: Cloud Load Balancer handles SSL termination and distributes traffic. Nginx serves static assets and routes application requests.
3. **Managed Database**: **MySQL Managed DB** (e.g. AWS RDS or GCP Cloud SQL) using **InnoDB** storage engine. Deploy a read replica to handle heavy reporting and backup operations without impacting live transactions.
4. **Cache & Session Store**: Managed **Redis** instance to handle shared sessions, rate limiting, and dashboard metrics cache.
5. **Private Media Storage**: Cloud Object Storage (e.g. AWS S3) configured with private access policies for sensitive LMS documents and leave attachments.

---

## 2. CI/CD Deployment Pipeline

Deploying updates to a live production ERP requires automated pipeline validations. We recommend a **GitHub Actions** CI/CD structure:

```yaml
# Conceptual CI/CD Pipeline
name: Deploy ERP System

on:
  push:
    branches: [ main, staging ]

jobs:
  validate_and_test:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: root
          MYSQL_DATABASE: test_db
        ports:
          - 3306:3306
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install flake8 pytest pytest-django
      - name: Run Linter
        run: flake8 apps/
      - name: Run Django Security Check
        run: python manage.py check --deploy
      - name: Run Test Suite
        run: pytest
        env:
          DATABASE_URL: mysql://root:root@127.0.0.1:3306/test_db
```

### Pipeline Progression:
1. **Linter & Formatters**: Run quality checks on the code style using `flake8` or `black`.
2. **Security Inspections**: Execute `python manage.py check --deploy` to verify production settings, and run dependency audits using `pip-audit`.
3. **Test Suite Execution**: Launch automated unit tests using `pytest-django`.
4. **Docker Image Build**: Build a production Docker image and push it to a private container registry.
5. **Auto-Deploy**: Deploy to the staging cluster. Once validated, trigger deployment to production using a rolling release pattern (zero-downtime deployment).

---

## 3. Testing & Staging Validation Strategy

Before switching DNS to the new Django server, validate data integrity on a staging cluster:

1. **Database Sandbox Testing**:
   * Restore a copy of the production SQLite database onto a secure staging machine.
   * Run the ETL migration management command on staging.
   * Verify row counts, financial sums, and foreign keys.
2. **Anonymized Data Clone**:
   * For privacy compliance, student demographic fields (emails, phones, parent names) must be masked in the staging database before developers run manual validation.
3. **User Acceptance Testing (UAT)**:
   * Provide access to core administrators (counselors, trainers, billing staff) to verify workflows: creating invoices, marking mock tests, and downloading files.
   * Verify that layout views adjust cleanly on mobile devices (dashboard navigation, student timelines).

---

## 4. System Monitoring & Error Tracking (APM)

* **Error Tracking (Sentry)**: Integrate **Sentry** with Django to monitor production exceptions in real-time. Sentry alerts will capture traceback details and user context (without logging passwords or sensitive billing data).
* **Application Metrics (Prometheus + Grafana)**: Export operational statistics (HTTP request response times, active database connections, Redis hits) and view trends on live Grafana dashboards.
* **Database Performance Profiling**: Enable MySQL's **Slow Query Log** to detect queries exceeding 1 second. Leverage Django's logging configuration to log query performance on staging:
  ```python
  LOGGING = {
      'version': 1,
      'handlers': {
          'console': {
              'class': 'logging.StreamHandler',
          },
      },
      'loggers': {
          'django.db.backends': {
              'level': 'DEBUG',
              'handlers': ['console'],
          },
      },
  }
  ```

---

## 5. Backup & Disaster Recovery Policies

A data recovery strategy is critical to ensure business continuity:

1. **Database Snapshots**:
   * Configure managed MySQL automated daily backups with a **30-day retention policy**.
   * Run transaction log backups every 15 minutes, enabling Point-in-Time Recovery (PITR) to minimize potential data loss.
2. **Offsite Replica Backups**:
   * Export encrypted database dumps nightly and upload them to a secure cloud bucket in a separate region.
3. **Media Asset Resilience**:
   * Enable object versioning on the private AWS S3 bucket to protect against accidental file deletions.
4. **Disaster Recovery Testing**:
   * Every quarter, the engineering team must test restoring the database from a snapshot onto an isolated database instance to verify backup validity.

---

## 6. Post-Live Guidelines

Once the system goes live, follow these monitoring protocols for the first 14 days:

* **Session Validation**: Monitor logs for session validation failures, ensuring that deactivated student or staff users are successfully redirected to the login screen.
* **Database Connections**: Monitor active database connection counts to verify that connection pooling is configured correctly and not hitting database server limits.
* **Storage Allocation Trends**: Monitor disk space growth on the MySQL instance to track disk allocation requirements as the student body and system activity log history grows.
