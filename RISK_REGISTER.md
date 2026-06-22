# Migration Risk Register

This document catalogs the technical, operational, and business risks associated with the Flask + SQLite to Django + MySQL ERP migration, defining severity scores and mitigation protocols.

---

## 1. Risk Matrix Overview

Risk Severity is calculated as:
$$\text{Risk Score (1-25)} = \text{Probability (1-5)} \times \text{Impact (1-5)}$$

| ID | Risk Description | Probability (1-5) | Impact (1-5) | Risk Score (1-25) | Severity Class |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R1** | Financial Inaccuracy (Floating-Point Issues) | 3 | 5 | **15** | High |
| **R2** | Date Conversion Errors (TEXT to DATETIME) | 4 | 4 | **16** | High |
| **R3** | CRM Lead Modification Authorization Bypass (IDOR) | 4 | 4 | **16** | High |
| **R4** | Unauthenticated Document/LMS Downloads | 3 | 4 | **12** | Medium |
| **R5** | Concurrent Database Transaction Locks | 3 | 4 | **12** | Medium |
| **R6** | Production Cutover Downtime | 3 | 4 | **12** | Medium |
| **R7** | Rate Limiter Session Isolation | 3 | 3 | **9** | Medium |
| **R8** | Student/Staff Session Mismatch | 2 | 4 | **8** | Medium |
| **R9** | Broken Legacy LMS Content Links (Bookmarking) | 4 | 2 | **8** | Medium |
| **R10**| Computational Lag on Report Generation | 3 | 3 | **9** | Medium |

---

## 2. Risk Detail & Mitigation Plans

### R1: Financial Inaccuracy during Data Import
* **Why it exists**: SQLite represents invoice totals, discounts, receipts, and write-offs using dynamic float-affinity values. MySQL strictly evaluates decimal values. Floating-point types introduce rounding errors (e.g. `10.99` represented as `10.989999...`).
* **Impact**: Discrepancies in billing statements, auditing warnings, and loss of cash ledger integrity.
* **Mitigation**: The ETL migration script must read financial strings, cast them to Python `decimal.Decimal` types, and write them into MySQL database columns configured as `DECIMAL(12, 2)`.

### R2: Date Conversion Failures from TEXT to DATETIME
* **Why it exists**: SQLite stores all timestamps as variable-format TEXT (e.g., `2026-06-21 13:15:12` or `2026/06/21`). MySQL requires valid ISO datetime sequences.
* **Impact**: Crashing database inserts, missing dates in invoices/attendance, and broken analytics.
* **Mitigation**: Write custom parser wrappers inside the ETL script using Python's `dateutil.parser`. Handle null or malformed date fields by substituting default epoch bounds or mapping them to an audit review log.

### R3: CRM Lead Modification Authorization Bypass (IDOR)
* **Why it exists**: Flask lead mutation views do not verify counselor ownership. If this authorization gap is cloned to Django, the risk persists.
* **Impact**: Counselors can modify, delete, or reassign leads assigned to other users, leading to database-wide data pollution.
* **Mitigation**: Override Django generic update views to check ownership via a helper mixin, raising a 403 Forbidden error if staff attempt to modify unauthorized leads.

### R4: Unauthenticated Document/LMS Downloads
* **Why it exists**: Files uploaded to local directories can be accessed directly via static paths without permission verification.
* **Impact**: Intellectual property leakage, exposure of medical leaves, and data privacy compliance issues.
* **Mitigation**: Relocate LMS documents to a private AWS S3 bucket. Access requests will pass through a Django authorization view that generates short-lived presigned URLs.

### R5: Concurrent Database Transaction Locks
* **Why it exists**: SQLite writes lock the entire database file. While MySQL uses row-level locking (InnoDB), high concurrent updates on single tables (e.g., batch attendance marked by 10 trainers simultaneously) can trigger lock wait timeouts.
* **Impact**: User session timeouts and transaction write failures.
* **Mitigation**: Deploy connection pooling, index lookup query parameters to reduce lock durations, and ensure views use atomic, short-lived database transactions.

### R6: Production Cutover Downtime
* **Why it exists**: Performing migrations on live databases takes time, and DNS changes can propagate slowly.
* **Impact**: Loss of business operations during class hours, missing leads, and billing interruptions.
* **Mitigation**: Schedule the cutover window during off-peak hours (e.g., Sunday 1:00 AM - 5:00 AM). Put the Flask app in read-only maintenance mode during database syncing.

### R7: Rate Limiter Session Isolation
* **Why it exists**: Flask's rate limiter uses isolated in-memory stores, which are not synchronized across workers.
* **Impact**: Vulnerability to distributed dictionary attacks on authentication endpoints.
* **Mitigation**: Use a central Redis instance for Django rate limiting, ensuring rate limit state is synchronized across all web server processes.

### R8: Student/Staff Session Mismatch
* **Why it exists**: The system supports both administrative staff sessions and student portal sessions.
* **Impact**: Students escalating privileges to access administrative dashboards.
* **Mitigation**: Use a custom user role system, and implement custom middleware to enforce strict URL route authorization checks.

### R9: Broken Legacy LMS Content Links (Bookmarking)
* **Why it exists**: Routing URLs change when moving from Flask blueprints to Django apps.
* **Impact**: Broken bookmarks for students, leading to increased support requests.
* **Mitigation**: Implement automatic URL pattern redirects (301 Permanent Redirects) for high-traffic student entry points.

### R10: Computational Lag on Report Generation
* **Why it exists**: Generating reports requires running heavy aggregation queries across multiple databases.
* **Impact**: High CPU utilization on the MySQL server, slow dashboard load times, and timeouts.
* **Mitigation**: Add indexes on lookup parameters, configure Redis caching for reporting dashboards, and run reports on a read replica if concurrency grows.
