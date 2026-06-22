# Migration Risk Register V2: SaaS Multi-Tenancy Risks

This document catalogs technical, operational, and business risks associated with migrating the ERP to a multi-tenant SaaS platform, evaluating severity scores and setting mitigation strategies.

---

## 1. Multi-Tenant Risk Matrix Overview

Risk Severity is calculated as:
$$\text{Risk Score (1-25)} = \text{Probability (1-5)} \times \text{Impact (1-5)}$$

| ID | Risk Description | Probability (1-5) | Impact (1-5) | Risk Score (1-25) | Severity Class |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R11**| **Cross-Tenant Data Exposure (IDOR)** | 2 | 5 | **10** | Medium |
| **R12**| **Database Row Lock Contention (Resource Starvation)** | 3 | 4 | **12** | Medium |
| **R13**| **Complex Tenant-Scoped Data Recovery** | 3 | 4 | **12** | Medium |
| **R14**| **Payment Gateway Webhook Failures (Suspension Glitches)**| 3 | 3 | **9** | Medium |
| **R15**| **Dynamic Subdomain SSL / Domain Configuration Errors**| 3 | 3 | **9** | Medium |
| **R16**| **Floating-Point Discrepancies in Legacy Balances** | 3 | 4 | **12** | Medium |
| **R17**| **Unauthenticated File Downloads per Tenant** | 2 | 4 | **8** | Medium |

---

## 2. Risk Detail & Mitigation Plans

### R11: Cross-Tenant Data Exposure (IDOR)
* **Why it exists**: All tenant data is stored within a single database. If the application filters fail (e.g. inside direct SQL or custom view overrides), one institution's users could access or mutate another institution's invoices or students.
* **Impact**: Violations of confidentiality, data leaks, and loss of business trust.
* **Mitigation**:
  * Implement an abstract `TenantModel` base class that overrides Django's default Manager (`objects`) to automatically enforce `filter(institution=...)` on all database operations.
  * Override the base model `save()` method to ensure that all foreign keys (e.g. saving an invoice linking to a student) check that both parent and child belong to the active tenant.
  * Implement a failsafe database router that raises an exception if a query is compiled on a tenant table without an `institution_id` parameter.

### R12: Database Row Lock Contention (Resource Starvation)
* **Why it exists**: Under high loads (e.g., thousands of students from 100+ institutions completing exams or marking attendance simultaneously), the shared MySQL server can hit connection limits or experience InnoDB row locks on hot tables.
* **Impact**: System timeouts, connection errors, and platform-wide downtime.
* **Mitigation**:
  * Set up connection pooling in Django (`CONN_MAX_AGE`).
  * Distribute expensive read operations (reports, analytics) to a database read replica.
  * Implement query timeouts at the database driver level and enable Redis caching for slow-changing dashboards.

### R13: Complex Tenant-Scoped Data Recovery
* **Why it exists**: Traditional database backups snapshot the entire MySQL database. If Tenant A accidentally deletes their data and requests a restore, restoring a global database backup would overwrite the active data of Tenants B through Z.
* **Impact**: Inability to restore individual tenant data without complex data surgical procedures.
* **Mitigation**:
  * Create a custom background exporter task (Celery) that structures a tenant's entire database scope into an encrypted JSON/ZIP dump.
  * Develop a companion import CLI utility that processes this JSON/ZIP dump, recreates records with new primary keys, resolves foreign key relationships, and writes them to the database under the target `institution_id`.

### R14: Payment Gateway Webhook Failures
* **Why it exists**: Subscriptions rely on external gateways (Stripe/Razorpay) to process payments and trigger updates via webhooks. If webhooks fail, active paying institutions might be suspended, or cancelled accounts might continue to access the platform.
* **Impact**: Interrupted client business operations or lost subscription revenues.
* **Mitigation**:
  * Build a robust webhook handler that records raw payloads to an audit log table before processing, enabling redelivery/re-processing.
  * Integrate a grace period (e.g., 3 days) for renewal failures before restricting access, sending automated warnings to administrators.

### R15: Dynamic Subdomain SSL Routing Errors
* **Why it exists**: Scaling to 100+ institutions requires dynamic resolution of custom domains (e.g. `learn.institute.com`) and subdomains. Misconfigured wildcards or SSL limits can block user access.
* **Impact**: DNS resolution errors and browser certificate warnings.
* **Mitigation**:
  * Configure wildcard DNS routing (`*.platform.com`) on the load balancer level.
  * Use automated Let's Encrypt certificate managers (e.g., Caddy server proxy or AWS Certificate Manager API) to dynamically provision and renew SSL certificates for custom domains.
