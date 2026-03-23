# Invoice Import - Missing Details Analysis

## Current Excel Import Template (6 columns)
From the first screenshot, the current invoice import file has:
1. invoice_number
2. student_id
3. amount
4. due_date
5. status
6. notes

## Actual Database Invoice Schema (19 columns)
From the database (db.py), invoices table requires:
1. **id** - Auto-generated, no need in import
2. **invoice_no** ✓ (mapped from invoice_number)
3. **student_id** ✓ 
4. **invoice_date** ❌ **MISSING** - When invoice was created (NOT same as due_date)
5. **subtotal** ❌ **MISSING** - Base amount before discounts
6. **discount_type** ❌ **MISSING** - Type: 'none', 'fixed', or 'percentage'
7. **discount_value** ❌ **MISSING** - Discount amount or percentage value
8. **discount_amount** ❌ **MISSING** - Calculated discount amount
9. **total_amount** ✓ (currently as "amount")
10. **installment_type** ❌ **MISSING** - Type: 'full' or 'custom'
11. **notes** ✓
12. **status** ✓ - Must be: 'unpaid', 'partially_paid', 'paid', 'cancelled'
13. **created_by** ❌ **MISSING** - User ID who created the invoice
14. **branch_id** ❌ **MISSING** - Which branch created the invoice
15. **created_at** - Auto-generated
16. **updated_at** - Can be auto-generated
17. Foreign keys and related tables

## Related Tables That May Be Missing
The invoice system also includes:

### invoice_items table:
- invoice_id (foreign key)
- course_id
- description (line item description)
- quantity
- unit_price
- line_total
- created_at

### installment_plans table:
- invoice_id (foreign key)
- installment_no
- due_date (individual installment due date)
- amount_due
- amount_paid
- status

## Recommended CSV/Import Template Format

```
invoice_number,student_id,invoice_date,subtotal,discount_type,discount_value,discount_amount,total_amount,installment_type,notes,status,created_by,branch_id
INV001,1,2026-04-21,5000,none,0,0,5000,full,Course Fee,pending,1,1
INV002,2,2026-04-15,4000,percentage,5,200,3800,full,,paid,1,1
```

## Key Issues:
1. **invoice_date vs due_date**: They're different fields - invoice_date is when created, due_date is for payment
2. **Subtotal and Discounts**: Currently importing "amount" directly without breakdown
3. **Missing Discount Details**: Can't track what kind of discount or why
4. **Installment Type**: Not specifying if full payment or custom installment plan
5. **Audit Trail**: Missing created_by and branch_id for proper record tracking
6. **Line Items**: No way to import invoice_items (course details per invoice)
7. **Installments**: No way to import the actual installment_plans linked to invoices

## Action Items:
- [ ] Update CSV template documentation with all required columns
- [ ] Create example CSV template file
- [ ] Update import route to handle all required fields
- [ ] Add validation for discount_type and installment_type
- [ ] Add validation for date formats
- [ ] Add validation for created_by (must be valid user ID)
- [ ] Add validation for branch_id (must be valid branch)
- [ ] Consider supporting invoice_items import as well
- [ ] Consider supporting installment_plans import as well
