-- Add performance indexes for test_attn_billing
-- Safe migration script containing only approved indexes

-- 1. Users Table (for fast login lookup)
CREATE UNIQUE INDEX idx_users_username ON users(username);

-- 2. Students Table (for branch filtering and status lookups)
CREATE INDEX idx_students_branch_status ON students(branch_id, status);
CREATE INDEX idx_students_status ON students(status);

-- 3. Student Batches Table (for counting students in batches and checking active courses)
CREATE INDEX idx_student_batches_student_status ON student_batches(student_id, status);
CREATE INDEX idx_student_batches_batch_status ON student_batches(batch_id, status);

-- 4. Attendance Records Table (for fast daily dashboard counts and status aggregations)
CREATE INDEX idx_attendance_records_batch_date_status ON attendance_records(batch_id, attendance_date, status);

-- 5. Invoices Table (for fast lookup of student invoices and status)
CREATE INDEX idx_invoices_student_status ON invoices(student_id, status);

-- 6. Invoice Items Table (for fast retrieval of item details per invoice)
CREATE INDEX idx_invoice_items_invoice_id ON invoice_items(invoice_id);

-- 7. Installment Plans Table (for dashboard due lists and status filtering)
CREATE INDEX idx_installment_plans_invoice_status ON installment_plans(invoice_id, status);
CREATE INDEX idx_installment_plans_status_due ON installment_plans(status, due_date);

-- 8. Receipts Table (for revenue summaries and client payments lookups)
CREATE INDEX idx_receipts_invoice_id ON receipts(invoice_id);
CREATE INDEX idx_receipts_receipt_date ON receipts(receipt_date);

-- 9. Activity Logs Table (for student profile activity view)
CREATE INDEX idx_activity_logs_module_record ON activity_logs(module_name, record_id);
