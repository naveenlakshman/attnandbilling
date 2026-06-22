# SaaS Multi-Tenant Architecture Blueprint

This document outlines the architectural blueprint for upgrading the ERP system into a multi-tenant SaaS platform, specifically answering the 10 critical architectural questions before development begins.

---

## 1. Single Database Multi-Tenant vs. Multi-Database vs. Hybrid

### Selected Model: Single Database Multi-Tenant (Shared Database, Shared Schema)
All institutions share a single codebase, a single MySQL database instance, and a single database schema. Individual tenant data is isolated logically using an `institution_id` column.

```text
                             [ Central MySQL Database ]
                                         │
    ┌────────────────────────────────────┼────────────────────────────────────┐
    ▼                                    ▼                                    ▼
[ saas_institutions ]            [ users ]                            [ invoices ]
 id: 1 (Global IT)                id: 101, institution_id: 1           id: 5001, institution_id: 1
 id: 2 (Tech Academy)             id: 102, institution_id: 2           id: 5002, institution_id: 2
```

### Architectural Rationale:
* **Cost Efficiency**: Running 100+ small-to-medium institutes (such as computer centers or coaching classes) on isolated MySQL instances would result in high infrastructure costs. A shared database allows maximum utilization of system resources under a single Cloud SQL/RDS database instance.
* **Low Maintenance Overhead**: Running database migrations across 100+ separate schemas or databases requires complex orchestration, introduces downtime, and risks schema drift. In a single database, migrations are run once.
* **Rapid Onboarding**: Creating a new tenant is as simple as inserting a row in the `Institution` table. No database provisioning or schema bootstrap is required.
* **Central Analytics & Operations**: Platform Owners can run analytics queries (e.g. active users, collection trends, exam performance) across all institutions using simple aggregate queries.

---

## 2. Why Institution is Built as a Model

Instead of database-level schemas or isolated databases, the **Institution is designed as a Django Database Model**.

### Architectural Rationale:
* **Target Database Constraints**: The project is migrating to **MySQL**. MySQL does not support schema namespaces in the same way PostgreSQL does (in MySQL, a "schema" is synonymous with a separate "database"). Thus, using schemas would be equivalent to running separate databases, increasing configuration and connection pooling overhead.
* **Query Performance**: The MySQL InnoDB engine optimizes indices efficiently. Compound indices starting with `institution_id` (e.g., `(institution_id, code)`) resolve query filtering instantly.
* **Django ORM Support**: Implementing multi-tenancy at the model layer maps natively to standard Django components, allowing developers to utilize Django's built-in administration panels and third-party packages.

---

## 3. Enforcing Tenant Isolation (Filtering Strategy)

Data isolation is enforced at the framework level using a middleware-driven thread-local context and a custom Django QuerySet/Manager.

### A. Tenant Context Holder
A thread-safe utility class manages the active tenant context for the duration of the request lifecycle:

```python
# apps/tenants/utils.py
import contextvars

# Thread-safe context variable
_active_tenant_id = contextvars.ContextVar('active_tenant_id', default=None)

def get_current_tenant_id():
    return _active_tenant_id.get()

def set_current_tenant_id(tenant_id):
    _active_tenant_id.set(tenant_id)

def clear_current_tenant_id():
    _active_tenant_id.set(None)
```

### B. Base Tenant Model and Manager
All tenant-scoped models inherit from a base `TenantModel`, which overrides Django's default query execution:

```python
# apps/core/models/base.py
from django.db import models
from django.core.exceptions import ValidationError
from tenants.utils import get_current_tenant_id

class TenantQuerySet(models.QuerySet):
    def delete(self):
        # Prevent bulk-delete bypasses of tenant checks
        return super().delete()

class TenantManager(models.Manager):
    def get_queryset(self):
        # Automatically append tenant filter to every SELECT query
        tenant_id = get_current_tenant_id()
        queryset = TenantQuerySet(self.model, using=self._db)
        if tenant_id is not None:
            return queryset.filter(institution_id=tenant_id)
        return queryset

class TenantModel(models.Model):
    institution = models.ForeignKey(
        'tenants.Institution', 
        on_index=True, 
        on_delete=models.CASCADE,
        related_name="%(class)ss"
    )

    objects = TenantManager()
    global_objects = models.Manager()  # Bypass manager for global queries

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Enforce write checks before database commit
        tenant_id = get_current_tenant_id()
        if tenant_id is not None:
            self.institution_id = tenant_id
        if not self.institution_id:
            raise ValidationError("Tenant context must be established to save this record.")
        super().save(*args, **kwargs)
```

### C. Resolution Middleware
The middleware intercepts requests, extracts the hostname, binds the tenant context, and checks subscription validity:

```python
# apps/tenants/middleware.py
from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from tenants.models import Institution
from tenants.utils import set_current_tenant_id, clear_current_tenant_id
from django.core.cache import cache

class TenantResolutionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0]
        
        # 1. Resolve tenant details from subdomain
        subdomain = host.split('.')[0]
        cache_key = f"subdomain_{subdomain}_tenant_id"
        tenant_id = cache.get(cache_key)
        
        if not tenant_id:
            try:
                tenant = Institution.objects.get(subdomain=subdomain)
                tenant_id = tenant.id
                cache.set(cache_key, tenant_id, 3600)  # Cache mapping for 1 hour
            except Institution.DoesNotExist:
                return HttpResponseForbidden("This domain is not registered on this platform.")
        
        # 2. Bind tenant to thread-safe request context
        set_current_tenant_id(tenant_id)
        request.tenant_id = tenant_id
        
        # 3. Check subscription suspension status
        # (Exclude login and subscription pages from block redirects)
        if not request.path.startswith('/tenants/billing/'):
            tenant_status = cache.get(f"tenant_{tenant_id}_status")
            if not tenant_status:
                tenant_status = Institution.objects.get(id=tenant_id).status
                cache.set(f"tenant_{tenant_id}_status", tenant_status, 600)
                
            if tenant_status == 'suspended':
                return redirect('/tenants/billing/suspended/')

        response = self.get_response(request)
        
        # 4. Clear context at the end of the request
        clear_current_tenant_id()
        return response
```

---

## 4. White-Label Branding System

Institutions customize their user interface, templates, and receipts without affecting other tenants:

### A. Branding Model Schema
The `Institution` model stores white-label parameters:
```python
# apps/tenants/models.py
class Institution(models.Model):
    name = models.CharField(max_length=255)
    subdomain = models.CharField(max_length=100, unique=True)
    custom_domain = models.CharField(max_length=255, unique=True, null=True)
    logo = models.ImageField(upload_to='logos/')
    primary_color = models.CharField(max_length=7, default='#1E3A8A')  # HEX Color
    secondary_color = models.CharField(max_length=7, default='#10B981')
    invoice_prefix = models.CharField(max_length=10, default='INV')
    receipt_prefix = models.CharField(max_length=10, default='RCP')
    status = models.CharField(max_length=20, default='active')  # active/suspended
```

### B. Jinja / HTML Stylesheet Injections
A Django Context Processor retrieves branding variables dynamically on page renders:

```python
# apps/tenants/context_processors.py
def tenant_branding(request):
    if hasattr(request, 'tenant_id'):
        from tenants.models import Institution
        tenant = Institution.objects.get(id=request.tenant_id)
        return {
            'tenant_name': tenant.name,
            'tenant_logo': tenant.logo.url,
            'tenant_primary': tenant.primary_color,
            'tenant_secondary': tenant.secondary_color,
            'invoice_prefix': tenant.invoice_prefix,
            'receipt_prefix': tenant.receipt_prefix,
        }
    return {}
```

In the main layout template `base.html`, inject colors into CSS custom properties:
```html
<head>
    <style>
        :root {
            --primary-color: {{ tenant_primary }};
            --secondary-color: {{ tenant_secondary }};
        }
        .btn-primary {
            background-color: var(--primary-color) !important;
            border-color: var(--primary-color) !important;
        }
        .sidebar {
            background-color: var(--primary-color);
        }
    </style>
</head>
```

---

## 5. Hierarchical Permissions & Multi-Tenant Access Control

The platform enforces permissions based on a user's role hierarchy and their parent institution assignment.

### A. Custom User Model Role Structure
```python
# apps/core/models/user.py
class User(AbstractUser):
    ROLE_CHOICES = (
        ('platform_owner', 'Platform Owner'),
        ('inst_admin', 'Institution Admin'),
        ('branch_manager', 'Branch Manager'),
        ('counselor', 'Counselor'),
        ('trainer', 'Trainer'),
        ('accountant', 'Accountant'),
        ('student', 'Student'),
    )
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    institution = models.ForeignKey(
        'tenants.Institution', 
        on_delete=models.CASCADE,
        null=True,  # Platform Owners are not bound to a tenant
        blank=True
    )
    branch = models.ForeignKey(
        'core.Branch', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
```

### B. Multi-Tenant Permission Guard
A custom Django class mixin checks credentials and verifies database bounds:

```python
# apps/core/mixins.py
from django.core.exceptions import PermissionDenied

class TenantRoleRequiredMixin:
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        # 1. Enforce user is authenticated
        if not request.user.is_authenticated:
            return self.handle_no_permission()
            
        # 2. Platform Owner bypasses tenant bounds checks
        if request.user.role == 'platform_owner':
            return super().dispatch(request, *args, **kwargs)
            
        # 3. Verify user belongs to the active tenant context
        if request.user.institution_id != request.tenant_id:
            raise PermissionDenied("You are not authorized to access this tenant's resources.")
            
        # 4. Verify role meets minimum permission requirements
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied("Your account role lacks permissions for this action.")
            
        return super().dispatch(request, *args, **kwargs)
```

---

## 6. Subscription Model Architecture

Subscriptions regulate tenant access, managing plans, payment terms, and user limits.

```text
[ Institution ] 1 ─── 1 [ Subscription ] n ─── 1 [ SubscriptionPlan ]
                              │
                              ▼
                       [ SubscriptionLimit ] (max_branches, max_students)
```

### A. Subscription Schema
```python
# apps/tenants/models.py
class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100)  # e.g., Starter, Growth, Enterprise
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2)
    max_branches = models.IntegerField()
    max_students = models.IntegerField()
    features_enabled = models.JSONField()  # e.g., {"lms": true, "exams": false}

class Subscription(models.Model):
    institution = models.OneToOneField(Institution, on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default='active')  # active/suspended/grace
    start_date = models.DateField()
    end_date = models.DateField()
    next_billing_date = models.DateField()
```

### B. Dynamic Feature Limit Enforcement
Before executing creation calls (e.g. creating a new branch or enrolling a student), system checks limits:
```python
# apps/core/services.py
def can_create_branch(institution_id):
    subscription = Subscription.objects.get(institution_id=institution_id)
    active_branches = Branch.objects.filter(institution_id=institution_id).count()
    if active_branches >= subscription.plan.max_branches:
        return False
    return True
```

---

## 7. Billing Plans & Webhook Processing

* **Recurring Cycles**: Subscriptions run on monthly or annual billing cycles.
* **Gateway Integration**: Payments are processed through external payment gateways (Stripe or Razorpay).
* **Asynchronous Webhook Processing**: Gateway transaction state changes (e.g., successful renewals, charge failures) are received via secure webhook endpoints and processed using a queue (Celery + Redis) to prevent HTTP blocking.

```python
# apps/tenants/tasks.py
from celery import shared_task
from tenants.models import Subscription, Institution

@shared_task
def process_failed_payment_webhook(stripe_customer_id):
    # Retrieve tenant bound to the stripe customer ID
    institution = Institution.objects.get(stripe_customer_id=stripe_customer_id)
    subscription = Subscription.objects.get(institution=institution)
    
    # Trigger account suspension state
    subscription.status = 'suspended'
    subscription.save()
    
    institution.status = 'suspended'
    institution.save()
    
    # Invalidate cache to enforce immediate block redirects across active sessions
    cache.set(f"tenant_{institution.id}_status", 'suspended', 600)
```

---

## 8. Asynchronous Tenant Data Exports

Admins can download a backup of their data. Because compiling data takes time and memory, it is run in the background:

1. **Celery Exporter Task**: A background worker compiles all database records matching `institution_id = target_tenant_id` into a structured JSON payload.
2. **Media Asset Gathering**: Reads the tenant's media partition (`media/tenants/tenant_<id>/`) and bundles it.
3. **ZIP Packaging**: Compresses the JSON files and media directory into a single encrypted ZIP file.
4. **Secure S3 Delivery**: Uploads the file to private S3 storage under a temporary prefix and emails a pre-signed download link (valid for 24 hours) to the Institution Admin.

---

## 9. Backups and Logical Tenant Restoration

Because all tenants reside in a single database, restoring an individual tenant from a global database snapshot would overwrite other tenants' active transactions.

### Multi-Tenant Recovery Strategy:
1. **Physical Backups**: Managed MySQL service runs automated daily snapshots with point-in-time recovery (PITR) enabled.
2. **Logical Tenant Restoration**:
   * Restore the physical database snapshot onto an isolated staging database.
   * Run a custom Django management script that reads data from the staging database, filters by target `institution_id`, and exports it as a logical JSON dump.
   * Run the import script on the production database. The import script updates primary keys, maps dependencies, and writes the recovered tables under the matching `institution_id`.

---

## 10. Architectural Decisions to Change BEFORE Coding Begins

To avoid expensive rewrites, implement these changes before writing application code:

1. **Define the Base Tenant Model & Abstract Class**: Scaffold `TenantModel` first. Every model designed subsequently (e.g., Lead, Invoice, Batch) must inherit from this class.
2. **Scaffold custom User authentication**: Introduce the custom user model (extending `AbstractUser` with `role` and `institution` FKs) in migrations.
3. **wildcard Subdomain Configs**: Ensure local development settings support dynamic subdomains (e.g. using `django-hosts` or custom configurations).
4. **Static and Media Private Serving**: Split settings into public local paths and private S3 storage backends. Do not use direct URL matching templates for LMS resources.
5. **Background Task Scaffolding**: Setup Celery and Redis in Docker configurations to handle background tasks from Day 1.
