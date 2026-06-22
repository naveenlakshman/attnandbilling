# Security Review V2: Multi-Tenant SaaS Security

This document evaluates the security architecture of the SaaS multi-tenant ERP platform, detailing strategies to prevent cross-tenant data leaks, enforce role hierarchies, isolate file access, and secure user sessions.

---

## 1. Preventing Cross-Tenant Data Leakage (IDOR Mitigation)

In a shared-database multi-tenant platform, the greatest security threat is **Cross-Tenant Data Exposure**. If a user alters a database primary key parameter in an HTTP query (e.g., `/finance/invoice/583/` changed to `/finance/invoice/584/`), they must be blocked unless the target record belongs to their active tenant context.

```text
Attacker (Tenant A) ────► GET /finance/invoice/584/ ────► Django Tenant Middleware
                                                                │
                                                                ▼
                                                        [ Resolve Active Tenant ]
                                                        - Request resolved to Tenant A
                                                                │
                                                                ▼
                                                        [ Custom Tenant Manager ]
                                                        - Appends filter: WHERE institution_id = Tenant_A_ID
                                                                │
                                                                ▼
                                                        [ Database Query Result ]
                                                        - Record 584 belongs to Tenant B
                                                        - Query returns EMPTY (DoesNotExist / 404)
                                                                │
                                                                ▼
Attacker (Tenant A) ◄─── Renders 404 Page (Not Found) ──────────┘
```

### Mitigation Safeguards
1. **Framework-Level Query Isolation**: All tenant models inherit from an abstract `TenantModel` class, which overrides Django's default Manager to ensure that every query is implicitly scoped:
   `SELECT * FROM invoices WHERE id = 584 AND institution_id = <current_tenant_id>;`
   If the record exists but belongs to a different tenant, Django returns a standard `DoesNotExist` exception, raising an HTTP 404 error rather than a 403, preventing primary key sniffing.
2. **Database Router Fail-Safe**: A custom database router intercepts queries and raises an exception if a query is executed on a tenant-specific table without an active `institution_id` filter in the SQL compilation pipeline.
3. **Data Mutation Guards**: The base model class overrides the `save()` method. If a user attempts to update a record (e.g. changing an invoice's student mapping), the system verifies that the target student and the invoice share the exact same `institution_id` value, rejecting the write if a mismatch is found.

---

## 2. Dynamic SaaS Role Hierarchy (RBAC)

The system implements a hierarchical Role-Based Access Control (RBAC) structure. Permissions are checked using Django permissions or custom view mixins:

```text
Level 1: Platform Owner  ──► Full access to all tenants, billing plans, and global analytics.
  Level 2: Inst Admin   ──► Full CRUD access to their institution only.
    Level 3: Branch Mgr ──► Access to branch resources, trainers, and local billing logs.
      Level 4: Counselor ──► CRM access, follow-up scheduler, conversions.
      Level 5: Trainer   ──► Batch management, attendance sheets, LMS assignments reviews.
      Level 6: Accountant ──► Fee collection, receipt generation, write-offs.
        Level 7: Student ──► Portal dashboard, syllabus slides, mock tests, mock application.
```

* **Staff vs Student Roles**: Staff accounts have the flag `is_staff = True` and access the admin dashboard. Student accounts have `is_staff = False` and are restricted to the student portal.
* **View decorators**: Every view is wrapped in a decorator or mixin that evaluates the user's role hierarchy and checks that `request.user.institution == current_tenant`.

---

## 3. Scoped Media File & LMS Private Storage Security

Files uploaded by users (e.g., student signatures, ID card photos, leave documents, assignment submissions) are isolated at the storage level:

1. **Storage Path Partitioning**: The storage engine prefixes files with the tenant identifier:
   `media/tenants/tenant_<institution_id>/lms_private/`
2. **Access Control (Private Buckets)**: Confidential files (such as leave certificates and assignment submissions) are uploaded to a private partition.
3. **Short-Lived Presigned URLs**: Access to private files is never served via direct static links. Requests are routed through a Django controller that:
   * Validates that the requester belongs to the matching tenant.
   * Checks that the student is registered or the user has staff roles.
   * Generates and redirects to a temporary pre-signed URL (e.g., valid for 5 minutes).

---

## 4. Central Session & Rate Limiting Hardening

* **Redis Shared Cache**: Rate limiting state (managed via `django-ratelimit`) is stored in a central Redis instance, preventing process-level rate bypasses on `/login` endpoints.
* **Immediate Session Termination**: If an Institution Admin suspends an institution or deactivates a user's account, a middleware checks the active session cache and deletes the session keys, instantly forcing the user out of active web portals.
