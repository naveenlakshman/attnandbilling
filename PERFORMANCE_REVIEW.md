# Database Performance & Query Optimization Review

This document analyzes the database performance vulnerabilities of the Flask + SQLite system and provides a detailed strategy for index design, Django QuerySet optimization, connection pooling, and caching in MySQL.

---

## 1. Database Index Strategy (MySQL / InnoDB)

MySQL automatically indexes primary key columns and foreign key parameters (`FOREIGN KEY` constraints). However, secondary indexes are required for non-key fields frequently filtered or sorted in dashboards and reports.

We recommend creating the following secondary indexes in the MySQL schema:

| Target Table | Column(s) to Index | Query Pattern / Use Case | Rationale |
| :--- | :--- | :--- | :--- |
| **`leads`** | `(assigned_to_id, status, stage)` | Lead list filtering, CRM dashboards, pipeline kanban rendering. | Prevents full-table scans when counselors view their active leads. |
| **`leads`** | `next_followup_date` | Follow-ups dashboard ("Due Today" / "Overdue"). | Speeds up date range queries on lead activities. |
| **`invoices`** | `(student_id, status)` | Financial audits, student portal invoice rendering. | Speeds up lookup of unpaid invoices per student. |
| **`receipts`** | `receipt_date` | Daily collection reports, ledger sheets. | Speeds up daily revenue aggregations. |
| **`installment_plans`**| `(status, due_date)` | Ageing receivables report, fee reminder generation. | Essential for date range filters on outstanding payments. |
| **`attendance_records`**| `(attendance_date, batch_id)`| Daily batch roll call, attendance sheet rendering. | Optimizes attendance trend analysis. |
| **`activity_logs`** | `created_at` | Chronological audit logs viewing. | Speeds up ordering operations (`ORDER BY created_at DESC`). |

---

## 2. Django QuerySet Optimization (Avoiding N+1 Queries)

The current Flask application makes extensive use of database cursors inside loops to render lists. For example, rendering the batch list queries the database for each batch to count enrolled students, trainer names, and courses.

In Django, developers must adhere to the following optimization patterns:

### A. Eager Loading with `select_related` and `prefetch_related`
* **`select_related`**: Use for single-valued relationships (ForeignKey, OneToOne) where Django can perform a SQL `JOIN` in a single query:
  ```python
  # Optimized Invoice List View
  invoices = Invoice.objects.select_related('student', 'branch', 'created_by').all()
  ```
* **`prefetch_related`**: Use for multi-valued or reverse relationships (ManyToMany, reverse ForeignKey) where Django performs a separate lookup query and aggregates in Python:
  ```python
  # Optimized Batch Detail View
  batches = Batch.objects.select_related('course', 'trainer').prefetch_related('student_batches__student').all()
  ```

### B. Database-Tier Aggregations with `annotate` and `aggregate`
Never fetch lists to iterate and sum records in Python. Leverage MySQL aggregations:
```python
# Unoptimized (Python-level aggregation):
# fee_sum = sum(invoice.total_amount for invoice in Student.invoices.all())

# Optimized (MySQL-level aggregation):
from django.db.models import Sum

student = Student.objects.annotate(total_billed=Sum('invoices__total_amount')).get(pk=student_id)
```

---

## 3. Database Connection Pooling

Unlike SQLite, where establishing a local connection is inexpensive, MySQL operates over TCP sockets. Initiating a new database handshake for every HTTP request is highly inefficient.

* **Django Implementation**: Enable persistent connections in Django configurations:
  ```python
  # settings/production.py
  DATABASES = {
      'default': {
          'ENGINE': 'django.db.backends.mysql',
          'NAME': 'global_erp_db',
          'USER': 'erp_db_user',
          'PASSWORD': 'SecureDbPassword123!',
          'HOST': '127.0.0.1',
          'PORT': '3306',
          'CONN_MAX_AGE': 600,  # Persist connections for 10 minutes (600 seconds)
      }
  }
  ```
* For high-concurrency environments, deploy a database proxy layer such as **ProxySQL** or use specialized connection poolers on the server tier.

---

## 4. Cache Architecture Plan

A Redis instance will serve as the shared cache backend for Django.

### A. Dashboard Metrics Caching
Billing statistics and CRM conversion metrics change slowly but require expensive joins across multiple tables. We will cache these metrics for 15 minutes:
```python
from django.core.cache import cache

def get_billing_dashboard_stats():
    stats = cache.get('billing_dashboard_stats')
    if not stats:
        # Compute expensive database queries
        stats = compute_revenue_metrics()
        cache.set('billing_dashboard_stats', stats, 900)  # Cache for 15 minutes
    return stats
```

### B. View-Level and Fragment Caching
* **Public Course Catalog**: The homepage `/` and courses pages `/courses/<slug>` change infrequently. View-level caching will be enabled on these routes for 1 hour:
  ```python
  from django.views.decorators.cache import cache_page

  @cache_page(3600)  # Cache public views for 1 hour
  def public_course_catalog(request):
      # Renders course listing
      pass
  ```
* **ERP Sidebars / Sidebar Badges**: Sidebar badge counts (e.g. pending leave counts, today's followups) can be cached for 5 minutes using template fragment caching.
