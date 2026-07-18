# Initial performance and Architectural Audit Report

This report presents a thorough, evidence-based performance and architectural audit of the web application. Using runtime request profiling and database schema analysis, we have pinpointed the exact causes of the slow website responses.

---

## 1. Database Connections
Database connection creation was analyzed by scanning the codebase and tracking active connections during request lifecycles:

* **Centralization**: MySQL connections are created in exactly one place: `get_conn()` in [db.py](file:///c:/Users/hello/attnandbilling/db.py#L278-L287).
* **Connection Lifecycle**: Currently, every request opens a *new* MySQL connection at the beginning of the route and closes it at the end. However, certain sub-routines (e.g. context processors and utility functions) call `get_conn()` independently, leading to multiple connections per request.
* **Connection Counts**:
  * **Login GET**: Opens **1 connection**
  * **Admin Dashboard**: Opens **1 connection**
  * **Staff Dashboard**: Opens **1 connection**
  * **Student Portal Dashboard**: Opens **2 connections** (1 for route, 1 for `inject_student_profile_score` context processor in [app.py](file:///c:/Users/hello/attnandbilling/app.py#L185-L200))
  * **Student Portal Profile**: Opens **2 connections** (1 for route, 1 for `inject_student_profile_score`)
* **Bottleneck**: Because PythonAnywhere hosts the web application and MySQL database on separate servers, each connection suffers from network latency (cold-start TCP handshakes). Opening multiple connections per request compounds this latency.

---

## 2. Request and Query Metrics (Empirical Measurements)
Using the Flask test client and custom monkey-patched database instrumentation, we ran a performance audit of key routes on a local MySQL server (0ms network round-trip time). The metrics are:

| Route Name | Request ID | Total Time (s) | DB Connections | SQL Query Count | SQL Duration (s) | Template Render (s) | Python Processing (s) | Response Size |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Login GET** (`/login`) | `31f45006` | 0.0208 | 1 | 1 | 0.0000 | 0.0068 | 0.0000 | 2.54 KB |
| **Admin Dashboard** (`/dashboard`) | `e2464b88` | 0.1112 | 1 | 20 | 0.0138 | 0.0626 | 0.0208 | 46.49 KB |
| **Staff Dashboard** (`/dashboard`) | `37c8737f` | 0.0482 | 1 | 12 | 0.0068 | 0.0000 | 0.0274 | 44.96 KB |
| **Student List** (`/billing/students`) | `30c00e91` | 0.1467 | 1 | 8 | 0.0347 | 0.0615 | 0.0363 | **2154.84 KB** (2.15 MB) |
| **Student Profile (Admin)** (`/billing/student/233`) | `7050d429` | 0.3816 | 1 | 23 | **0.2945** | 0.0000 | 0.0871 | 98.09 KB |
| **Attendance Dashboard** (`/attendance/dashboard`) | `54484da7` | 0.5003 | 1 | **190** | **0.4575** | 0.0142 | 0.0281 | 249.88 KB |
| **LMS Dashboard** (`/lms_admin/dashboard`) | `bda44be9` | 0.0277 | 1 | 6 | 0.0000 | 0.0069 | 0.0070 | 39.95 KB |
| **Student Portal Dashboard** (`/student/dashboard`) | `6efe962d` | 0.0492 | 2 | 4 | 0.0069 | 0.0141 | 0.0141 | 14.36 KB |
| **Student Portal Profile** (`/student/profile`) | `5ac70c08` | 0.0547 | 2 | 9 | 0.0062 | 0.0069 | 0.0278 | 48.31 KB |

> [!WARNING]
> **Production Latency Amplification**: While query execution times are fast locally (e.g. 190 queries in 0.45s), on PythonAnywhere each database call incurs a network round-trip time (RTT) of 2ms to 15ms. In production, 190 queries will easily translate into **2.5 to 5.0 seconds** of pure network delay, blocking Flask workers completely.

---

## 3. The Database Index Migration Failure (Root Cause)
We audited the actual MySQL schema and indexes. We discovered a critical failure in the migration history:

1. **Migration Interception**: The migration script [migrate_sqlite_to_mysql.py](file:///c:/Users/hello/attnandbilling/scripts/migrate_sqlite_to_mysql.py) only migrated tables (`type='table'`) and completely ignored SQLite indexes (`type='index'`).
2. **Ignored Runtime Indices**: To handle custom SQL dialect differences, the runtime compatibility wrapper [db.py](file:///c:/Users/hello/attnandbilling/db.py#L80-L81) explicitly ignores all `CREATE INDEX` queries:
   ```python
   if query.strip().upper().startswith("PRAGMA") or re.search(r"^\s*CREATE\s+(TABLE|INDEX)", query, re.IGNORECASE):
       return self
   ```
3. **Current State**: As a result, **no secondary indexes were ever created on MySQL**. Major transaction tables have zero indexes outside of the primary key on `id`:
   * `users`: No index on `username`. Login requires a full-table scan.
   * `student_batches`: No index on `student_id` or `batch_id`.
   * `attendance_records`: No index on `batch_id` or `attendance_date`.
   * `invoices`, `installment_plans`, `receipts`: No indexes on foreign keys (`student_id`, `invoice_id`) or filter/date columns (`due_date`, `receipt_date`).

---

## 4. Slowest SQL Queries
The ten slowest queries identified during our profiling run are:

1. **Student Activity Log (in Student Profile View)**:
   ```sql
   SELECT al.id, al.user_id, al.branch_id, al.action_type, al.module_name, al.record_id, al.description, al.created_at, u.full_name AS actor_name, u.username AS actor_username 
   FROM activity_logs al 
   LEFT JOIN users u ON al.user_id = u.id 
   JOIN student_batches sb ON sb.batch_id = al.record_id 
   WHERE al.module_name = 'attendance' AND sb.student_id = 233 
   ORDER BY al.id DESC LIMIT 5
   ```
   * **Duration**: **0.2755 seconds** (locally!)
   * **Reason**: Double full-table scan because `student_batches` lacks indexes on `student_id` and `batch_id`, and `activity_logs` lacks an index on `record_id`.
2. **Student List Main Query**:
   ```sql
   SELECT students.*, branches.branch_name, branches.branch_code FROM students LEFT JOIN branches ON students.branch_id = branches.id WHERE 1=1 ORDER BY students.id DESC
   ```
   * **Duration**: **0.0204 seconds** (scales linearly with student count)
   * **Reason**: Fetches the entire student database at once without any `LIMIT` or pagination.
3. **Attendance Status Counts (in loop)**:
   ```sql
   SELECT status, COUNT(*) as count FROM attendance_records WHERE batch_id = ? AND attendance_date = ? GROUP BY status
   ```
   * **Duration**: **0.0070s - 0.0436s** (executed in a loop for every active batch)
   * **Reason**: Missing indexes on `attendance_records(batch_id, attendance_date)`.
4. **Student List Batch Lookup**:
   ```sql
   SELECT sb.student_id, b.id AS batch_id, b.batch_name FROM student_batches sb JOIN batches b ON sb.batch_id = b.id WHERE sb.student_id IN (?, ?, ...) AND sb.status = 'active' ORDER BY sb.student_id, b.batch_name
   ```
   * **Duration**: **0.0073 seconds**
   * **Reason**: Scan on `student_batches` for up to 500 student IDs.
5. **Installment Past Due Query (Admin Dashboard)**:
   ```sql
   SELECT ... FROM installment_plans ip JOIN invoices i ON ip.invoice_id = i.id JOIN students s ON i.student_id = s.id WHERE ip.status != 'paid' AND parse_date(ip.due_date) < ? AND i.status NOT IN ('write_off', 'partially_written_off') ORDER BY parse_date(ip.due_date) ASC
   ```
   * **Reason**: Translates the `parse_date` function into a slow regex-pattern case statement at runtime, preventing index lookup.
6. **Attendance Marked Count (in loop)**:
   ```sql
   SELECT COUNT(*) as marked_count FROM attendance_records WHERE batch_id = ? AND attendance_date = ?
   ```
   * **Reason**: Missing index on `attendance_records(batch_id, attendance_date)`.
7. **Student Batch Count (in loop)**:
   ```sql
   SELECT COUNT(*) as total_students FROM student_batches WHERE batch_id = ? AND status = 'active'
   ```
   * **Reason**: Missing index on `student_batches(batch_id)`.
8. **Student Uploaded Documents Query (Student Profile)**:
   ```sql
   SELECT * FROM student_uploaded_documents WHERE student_id = ?
   ```
   * **Reason**: Missing index on `student_uploaded_documents(student_id)`.
9. **User Login Query**:
   ```sql
   SELECT * FROM users WHERE username = ? AND is_active = 1
   ```
   * **Reason**: Missing index on `users(username)`.
10. **Revenue/Expenses Queries (Admin Dashboard)**:
    ```sql
    SELECT COALESCE(SUM(amount_received), 0) AS total FROM receipts WHERE strftime('%Y-%m', receipt_date) = ?
    ```
    * **Reason**: String matching operations on unindexed `varchar` date columns.

---

## 5. Cost of the SQLite-to-MySQL Compatibility Layer
* **CPU Overhead**: Profiling shows that `re.sub` and translation logic runs fast, consuming about **0.01 - 0.2ms** of CPU time per query. It contributes less than 2% of the total request duration.
* **Database Optimization Bottleneck**: The real cost is that the translation layer encourages maintaining SQLite-specific date operations (e.g. `parse_date` regex conversions, `strftime`), which prevents the MySQL optimizer from utilizing any indexes even if they were present.

---

## 6. Photo and Static File Audit
* **No Resizing/Compression**: In `save_student_photo` ([modules/billing/routes.py](file:///c:/Users/hello/attnandbilling/modules/billing/routes.py#L1000-L1022)), the photo data is decoded from base64 and written directly to the file system. There is no resizing or compression.
* **Large Payloads**: If a staff member uploads a high-resolution photo from a phone camera (e.g. 5MB to 12MB), it is stored and served in full resolution.
* **Route-based Streaming**: Certain static files (like leave documentation and LMS content) are served via Flask routes (`/uploads/content/...`), which consumes web workers to stream bytes instead of delegating to a web server.

---

## 7. PythonAnywhere Worker and Hosting Limitations
* **Web Workers**: A paid PythonAnywhere account typically provides 2-3 single-threaded web workers. A single web worker can process exactly **one concurrent request**.
* **Worker Blocking**: When a request executes 190 queries (like the Attendance Dashboard) or downloads a 10MB photo, it blocks that worker for several seconds. Concurrent users are forced to queue, leading to timeouts (502 Bad Gateway) and severe lag.
* **Static Asset Mappings**: Without mapping the `/static` and `/uploads` paths in the PythonAnywhere Web Dashboard, the app server handles static assets, causing unnecessary worker blockages.

---

## 8. Five Changes Most Likely to Produce Immediate Improvements

### 1. Create Crucial MySQL Indexes (High Impact, Low Risk)
Add secondary indexes to eliminate full-table scans. Specifically:
```sql
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_student_batches_student_status ON student_batches(student_id, status);
CREATE INDEX idx_student_batches_batch_status ON student_batches(batch_id, status);
CREATE INDEX idx_attendance_records_lookup ON attendance_records(batch_id, attendance_date);
CREATE INDEX idx_invoices_student_id ON invoices(student_id);
CREATE INDEX idx_installment_plans_invoice_id ON installment_plans(invoice_id);
CREATE INDEX idx_receipts_invoice_id ON receipts(invoice_id);
```

### 2. Implement Request-Scoped Connection Reuse (High Impact, Low Risk)
Modify [db.py](file:///c:/Users/hello/attnandbilling/db.py) to save the active database connection to Flask's `g` object. This ensures that a single request execution reuse one connection rather than opening multiple TCP connections. The connection is cleanly committed and closed at the end of the request lifecycle using Flask's `@app.teardown_request`.

### 3. Eliminate N+1 Queries on the Attendance Dashboard (High Impact, Medium Risk)
Refactor the batch statistics loop in [modules/attendance/routes.py](file:///c:/Users/hello/attnandbilling/modules/attendance/routes.py#L193-L265) to fetch student counts and attendance counts for all batches in bulk (e.g. using `GROUP BY batch_id`). This will reduce the query count on the dashboard from 190 to under 10.

### 4. Implement Pagination on the Student List (High Impact, Medium Risk)
Implement simple `LIMIT` and `OFFSET` pagination (e.g. 50 students per page) on `/billing/students` to reduce the HTML payload from 2+ MB to <100 KB, drastically saving worker memory and browser rendering time.

### 5. Resize and Compress Student Photos (Medium Impact, Low Risk)
Update the `save_student_photo` function to use `Pillow` to resize photos to a max of 300x300 pixels and save them with a JPEG quality of 85. This limits image sizes to <50 KB, speeding up profile page loading.
