# Performance Review V2: Multi-Tenant Database Optimization

This document outlines optimization strategies to maintain low-latency query performance on a shared MySQL database as the system scales to serve 100+ institutions and 50,000+ students.

---

## 1. Compound Database Indices for Multi-Tenancy

In a single-database multi-tenant platform, every query filters on the tenant's identifier (`institution_id`). To ensure indices are utilized, secondary lookup keys must be restructured into **compound indices** where `institution_id` is the leftmost column:

| Target Table | Column(s) to Index | Query Pattern / Use Case | Rationale |
| :--- | :--- | :--- | :--- |
| **`leads`** | `(institution_id, assigned_to_id, stage)` | Lead dashboards, pipeline Kanban boards. | Speeds up retrieval of a counselor's active leads. |
| **`invoices`** | `(institution_id, student_id, status)` | Financial audits, portal collections rendering. | Speeds up unpaid invoice lookups. |
| **`installment_plans`**| `(institution_id, status, due_date)` | Receivables reports, payment alerts. | Essential for date range scans on collections. |
| **`attendance_records`**| `(institution_id, attendance_date, batch_id)`| Attendance mark checks, daily trends. | Optimizes batch roll-call lookups. |
| **`users`** | `(institution_id, username)` | Login and routing resolution. | Speeds up user credential validations on login. |

---

## 2. Optimizing Django QuerySets (Avoiding N+1 Query Scopes)

When iterating through datasets, avoid issuing database lookups inside loops. Ensure all multi-tenant views leverage eager loading:

### A. Eager Loading (Joins)
* **`select_related`**: Use for single relationships (ForeignKey, OneToOne) to fetch related tenant objects in a single SQL query:
  ```python
  # Optimized Invoice List
  invoices = Invoice.objects.select_related('student', 'branch').filter(institution=current_tenant)
  ```
* **`prefetch_related`**: Use for reverse relations (ManyToMany, reverse ForeignKey) where separate lookup queries are merged in Python:
  ```python
  # Optimized Batch Detail
  batches = Batch.objects.select_related('trainer').prefetch_related('student_batches__student').filter(institution=current_tenant)
  ```

### B. Database-Level Aggregations
Avoid counting or summing objects in Python memory. Push calculations to MySQL using Django `annotate` and `aggregate`:
```python
# Django aggregate query for collections summary
from django.db.models import Sum

totals = Invoice.objects.filter(institution=current_tenant).aggregate(
    total_receivable=Sum('total_amount')
)
```

---

## 3. Database Connection Pooling

Because MySQL operates over TCP sockets, initializing connection handshakes on every request degrades server latency. Enable persistent database connection pools:

```python
# settings/production.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'global_erp_db',
        'USER': 'erp_db_user',
        'PASSWORD': 'SecureDbPassword123!',
        'HOST': 'mysql-primary.internal',
        'PORT': '3306',
        'CONN_MAX_AGE': 600,  # Maintain connection channels open for 10 minutes
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    }
}
```

---

## 4. Redis Multi-Tenant Cache Architecture

A Redis instance serves as the shared cache, using tenant-prefixed keys to isolate cached records.

### A. Tenant Branding & Configurations Caching
White-label configurations (logos, theme colors, business prefixes) change rarely but are loaded on every page load. We cache these settings for 1 hour:
```python
from django.core.cache import cache

def get_tenant_branding(institution_id):
    cache_key = f"tenant_{institution_id}_branding"
    branding = cache.get(cache_key)
    if not branding:
        institution = Institution.objects.get(id=institution_id)
        branding = {
            'name': institution.name,
            'logo': institution.logo_url,
            'primary_color': institution.primary_color,
            'invoice_prefix': institution.invoice_prefix,
        }
        cache.set(cache_key, branding, 3600)  # Cache for 1 hour
    return branding
```

### B. Tenant Dashboard Metrics Cache
Cache CRM conversions and financial collections for 15 minutes, invalidating only when new conversions occur or receipts are posted:
* Cache Key: `tenant_<institution_id>_crm_dashboard_stats`
* Invalidation: Triggers via Django database `post_save` signals on `Lead` or `Receipt` models.
