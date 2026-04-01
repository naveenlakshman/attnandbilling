# Invoice Creation Feature - Complete Analysis

## 1. ROUTE HANDLER - `/billing/invoice/new`

**File:** `modules/billing/routes.py` (lines 1702-2028)

### Route Behavior
- **Method:** GET (displays form) and POST (creates invoice)
- **Authentication:** `@login_required`
- **Authorization:** `@admin_required`
- **URL:** `/billing/invoice/new`

### POST Request Flow

#### Step 1: Input Validation & Data Extraction
```python
student_id = request.form["student_id"]
invoice_date = request.form["invoice_date"]
installment_type = request.form["installment_type"]  # "full" or "custom"
notes = request.form.get("notes", "").strip()

# Multiple item arrays (per row in the items table)
item_course_ids = request.form.getlist("item_course_id[]")
item_descriptions = request.form.getlist("item_description[]")
item_qtys = request.form.getlist("item_qty[]")
item_rates = request.form.getlist("item_rate[]")
item_discounts = request.form.getlist("item_discount[]")  # Line-level discount
```

#### Step 2: Item Processing & Calculation
- Iterates through all item rows
- Skips rows where all values are empty (quantity=0, rate=0)
- For each valid item:
  - Converts Qty × Rate to gross amount
  - Applies line-level discount (capped at gross amount)
  - Calculates `line_total = gross - row_discount`
  - Accumulates: subtotal, discount_amount, total_amount

**Key Validations:**
- Description is required
- Quantity must be > 0
- Rate cannot be negative
- Discount cannot exceed gross amount

#### Step 3: Invoice Creation
```sql
INSERT INTO invoices (
    invoice_no,           -- Set to "TEMP" initially
    student_id,
    branch_id,            -- Copied from student's branch
    invoice_date,
    subtotal,             -- Sum of (qty × rate) for all items
    discount_type,        -- Always "none" (system doesn't support invoice-level discount)
    discount_value,       -- Always 0
    discount_amount,      -- Sum of per-item discounts
    total_amount,         -- Final net total
    installment_type,     -- "full" or "custom"
    notes,
    status,               -- "unpaid"
    created_by,
    created_at,
    updated_at
)
```

#### Step 4: Auto-Generate Invoice Number
- Queries for last invoice number that doesn't match "INV-%" or "TEMP"
- Parses format: `GIT/B/{number}` or custom format
- Increments the numeric part
- Updates the temporary invoice with real invoice_no

#### Step 5: Insert Invoice Items
```sql
INSERT INTO invoice_items (
    invoice_id,
    course_id,           -- Optional (can be NULL for custom items)
    description,
    quantity,
    unit_price,
    line_total,          -- Note: discount is NOT stored per item separately; only line_total
    created_at
)
```

#### Step 6: Create Installment Plan
Two paths based on `installment_type`:

**Option A: Full Payment (`installment_type = "full"`)**
```sql
INSERT INTO installment_plans (
    invoice_id,
    installment_no = 1,
    due_date,            -- From "full_due_date" form field
    amount_due = total_amount,
    amount_paid = 0,
    status = "pending",
    comments = "Full payment"
)
```

**Option B: Custom Installments (`installment_type = "custom"`)**
- Gets `installment_count` from form
- For each installment i (1 to count):
  - Gets `due_date_{i}`, `amount_due_{i}`, `remarks_{i}` from form
  - Validates: due_date required, amount_due > 0
  - **Critical:** Sum of all `amount_due` values MUST exactly match `total_amount`
  - Creates separate installment_plans record for each

#### Step 7: Success Response
- Commits transaction
- Logs activity
- Redirects to `invoice_view` with invoice_id

---

## 2. DATABASE SCHEMA

### **invoices Table**
```sql
CREATE TABLE invoices (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no          TEXT NOT NULL UNIQUE,     -- e.g., "GIT/B/123"
    student_id          INTEGER NOT NULL,          -- FK to students.id
    invoice_date        TEXT NOT NULL,              -- YYYY-MM-DD format
    subtotal            REAL NOT NULL DEFAULT 0,   -- Sum of qty × rate
    discount_type       TEXT DEFAULT 'none',       -- CHECK: none|fixed|percentage
                                                    -- Currently always "none"
    discount_value      REAL NOT NULL DEFAULT 0,   -- Always 0 (not used)
    discount_amount     REAL NOT NULL DEFAULT 0,   -- Sum of line-level discounts
    total_amount        REAL NOT NULL DEFAULT 0,   -- NET: subtotal - discount_amount
    installment_type    TEXT DEFAULT 'full',       -- CHECK: full|custom
    notes               TEXT,
    status              TEXT DEFAULT 'unpaid',     -- CHECK: unpaid|partially_paid|paid|cancelled|write_off|partially_written_off
    created_by          INTEGER NOT NULL,          -- FK to users.id
    branch_id           INTEGER,                   -- FK to branches.id
    created_at          TEXT NOT NULL,             -- ISO timestamp
    updated_at          TEXT
)
```

### **invoice_items Table**
```sql
CREATE TABLE invoice_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL,              -- FK to invoices.id (CASCADE DELETE)
    course_id       INTEGER,                       -- FK to courses.id (Optional)
    description     TEXT NOT NULL,                 -- Fee head or custom description
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price      REAL NOT NULL DEFAULT 0,       -- Rate per unit
    discount        REAL NOT NULL DEFAULT 0,       -- Line-level discount (NOT currently used in creation)
    line_total      REAL NOT NULL DEFAULT 0,       -- quantity × unit_price - discount
    created_at      TEXT NOT NULL
)

-- NOTE: The "discount" column exists but is NOT populated during invoice creation
-- Line-level discounts are calculated as: item_discount[] = qty × rate - line_total
-- They are summed into invoices.discount_amount but not individually stored
```

### **installment_plans Table**
```sql
CREATE TABLE installment_plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL,              -- FK to invoices.id (CASCADE Delete)
    installment_no  INTEGER NOT NULL,              -- 1, 2, 3...
    due_date        TEXT NOT NULL,                 -- YYYY-MM-DD format
    amount_due      REAL NOT NULL DEFAULT 0,       -- Amount expected for this installment
    amount_paid     REAL NOT NULL DEFAULT 0,       -- Amount received (updated when receipts created)
    status          TEXT DEFAULT 'pending',        -- CHECK: pending|partially_paid|paid|overdue
    remarks         TEXT,                          -- Custom notes or "Full payment"
    created_at      TEXT NOT NULL,
    updated_at      TEXT
)
```

### **courses Table** (referenced in items)
```sql
CREATE TABLE courses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name     TEXT NOT NULL UNIQUE,
    duration        TEXT,                          -- e.g., "3 months"
    fee             REAL NOT NULL DEFAULT 0,       -- Used to populate item rate when course selected
    course_type     TEXT DEFAULT 'standard',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT
)
```

### **students Table** (referenced)
```sql
CREATE TABLE students (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_code        TEXT NOT NULL UNIQUE,      -- e.g., "STU-001"
    full_name           TEXT NOT NULL,
    phone               TEXT NOT NULL,
    email               TEXT,
    address             TEXT,
    joined_date         TEXT NOT NULL,
    status              TEXT DEFAULT 'active',     -- CHECK: active|completed|dropped
    gender              TEXT,
    education_level     TEXT,
    qualification       TEXT,
    employment_status   TEXT DEFAULT 'unemployed',
    branch_id           INTEGER,                   -- Each student must have a branch
    date_of_birth       TEXT,
    parent_name         TEXT,
    parent_contact      TEXT,
    photo_filename      TEXT,                      -- Recently added column
    created_at          TEXT NOT NULL,
    updated_at          TEXT
)
```

---

## 3. HTML FORM STRUCTURE - `templates/billing/invoice_form.html`

### Form Layout: Two-Column Grid
```
Left Column (Main Area)           Right Column (Fixed Summary Box)
├─ Item Table                     ├─ Subtotal: ₹ X.XX
├─ Installment Plan               ├─ Discount: ₹ X.XX
├─ Notes                          ├─ NET TOTAL: ₹ X.XX
└─ Custom Installments Section    ├─ Installment Total: ₹ X.XX
                                  ├─ Difference: ₹ X.XX
                                  ├─ Status (Balanced/Not Balanced)
                                  └─ [Save Invoice Button]
```

### Top Header Section (4 Fields in Grid)
1. **Student Selector** (TomSelect dropdown)
   - Shows: `{student_code} - {full_name}`
   - Source: All active students ordered by name
   - `name="student_id"` (required)

2. **Invoice Date** (date input)
   - Default: Today's date (`{{ today }}` from backend)
   - `name="invoice_date"` (required)

3. **Installment Type** (select)
   - Options: "Full Payment" (value="full") | "Custom Installments" (value="custom")
   - Triggers: `toggleInstallmentSections()` on change
   - `name="installment_type"` (required)

4. **Full Payment Due Date** (date input)
   - `name="full_due_date"`
   - Visible/hidden based on installment_type
   - Disabled when installment_type="custom"

### Bill Items Table
**Columns (6):**
| Fee Head / Description | Qty | Rate | Discount | Amount | Delete |
|---|---|---|---|---|---|
| 34% width | 12% | 16% | 16% | 16% | 6% |

**Per Item Row:**
1. **Course Selector + Description (stacked)**
   - TomSelect dropdown: `name="item_course_id[]"`
     - Options: `{course_name} - ₹ {fee}` for all active courses
     - Has `data-name` and `data-fee` attributes
     - onChange: triggers `handleCourseSelect()` → populates description & rate
   - Text input: `name="item_description[]"` (required)
     - Placeholder: "Fee head / description"
     - Auto-populated if course selected

2. **Quantity** - `name="item_qty[]"`
   - Type: number, min=1, step=1
   - Default: 1
   - oninput: `calculateInvoiceTotals()`

3. **Rate** - `name="item_rate[]"`
   - Type: number, min=0, step=0.01
   - Default: 0 (or course fee if course selected)
   - oninput: `calculateInvoiceTotals()`

4. **Discount** - `name="item_discount[]"`
   - Type: number, min=0, step=0.01
   - This is the **line-level discount** per item
   - oninput: `calculateInvoiceTotals()`

5. **Amount** (readonly) - `name="item_amount[]"`
   - Calculated: `qty × rate - discount`
   - Read-only field, updated by JavaScript

6. **Delete Button** - Class: `delete-btn`
   - onclick: `removeItemRow(this)`
   - Prevents deletion if only one row remains

**Add Row Button:**
- Clones first row (with cleared values)
- Reinitializes TomSelect for course dropdown
- `onclick: addItemRow()`

### Payment Information Section (Edit Mode Only)
Shows when in edit mode:
- Invoice Total
- Amount Paid (from receipts)
- Balance Amount
- Current installment plan table

### Installment Plan Section
**Visible only when `installment_type == "custom"`**

**Quick Split Selector:**
- Options: "Split into 2" | "Split into 3"
- Applies even distribution with last row capturing rounding

**Installment Count Input:**
- Type: number, min=1, max=6
- oninput: `renderInstallmentRows()` - rebuilds table dynamically

**Installment Table:**
| No | Due Date | Amount | Remarks | Delete |
|---|---|---|---|---|

Per installment row:
- **No** - Static display (1, 2, 3...)
- **Due Date** - `name="due_date_{i}"` (date input, required)
- **Amount** - `name="amount_due_{i}"` (number, class=installment-amount)
  - oninput: `updateInstallmentSummary()`
  - **MUST sum to exactly total_amount**
- **Remarks** - `name="remarks_{i}"` (text input)
- **Delete** - Renumbers rows and updates names accordingly

### Notes Section
```html
<textarea name="notes" rows="3" placeholder="Optional notes"></textarea>
```

### Summary Box (Right Side - Sticky Position)
**Display Fields (readonly, updated by JavaScript):**
1. **Subtotal** - `#summary_subtotal` - Sum of `qty × rate` for all items
2. **Total Discount** - `#summary_discount` - Sum of line-level discounts
3. **Net Total** - `#summary_total` - `subtotal - total_discount` (BOLD)
4. **Installment Total** - `#installment_total` - Sum of `amount_due` values
5. **Difference** - `#difference_total` - `net_total - installment_total`
6. **Status** - `#balance_status` - "Balanced ✅" (green) or "Not Balanced ❌" (red)

**Save Button:**
- Class: btn btn-primary
- Type: submit
- Text: "Save Invoice" (create mode) | "Save Changes" (edit mode)

---

## 4. JAVASCRIPT FUNCTIONS & CALCULATIONS

### `calculateInvoiceTotals()`
**What it does:** Updates all summary fields when items change

```javascript
// For each item row:
const qty = row.item-qty value
const rate = row.item-rate value
let discount = row.item-discount value (capped at gross)

const gross = qty * rate
const amount = gross - discount

subtotal += gross
totalDiscount += discount
netTotal += amount

// Update row's readonly item-amount field
// Update right sidebar summary
```

**Triggers:** 
- oninput on item_qty, item_rate, item_discount fields
- removeItemRow()
- addItemRow()
- handleCourseSelect()

### `handleCourseSelect(selectEl)`
**What it does:** When a course is selected from dropdown

```javascript
const courseName = selected.data-name attribute
const courseFee = selected.data-fee attribute

// Auto-populate description
descInput.value = courseName

// Auto-populate rate if there's a fee
rateInput.value = courseFee.toFixed(2)

// Ensure quantity is at least 1
if (!qtyInput.value || qty <= 0) {
    qtyInput.value = 1
}

calculateInvoiceTotals()
```

### `toggleInstallmentSections()`
**What it does:** Shows/hides installment UI based on selection

```javascript
if installment_type == "full":
    Hide custom_installment_section
    Enable full_due_date field
else (custom):
    Show custom_installment_section
    Disable full_due_date field
    If no rows yet: renderInstallmentRows()

updateInstallmentSummary()
```

### `renderInstallmentRows()`
**What it does:** Dynamically creates N installment rows based on count input

```javascript
for i = 1 to installment_count:
    Create row with:
    - Static No: i
    - due_date_{i} (date input)
    - amount_due_{i} (number, class=installment-amount)
    - remarks_{i} (text)
    - Delete button
```

### `applyQuickSplit()`
**What it does:** Splits net total evenly across installment count

```javascript
const split = selectedValue (2 or 3)
const finalTotal = summary_total value

baseAmount = floor((finalTotal / split) × 100) / 100  // Prevent pennies
runningTotal = 0

for each installment:
    if not last: amount = baseAmount, runningTotal += baseAmount
    if last: amount = finalTotal - runningTotal  // Capture rounding

updateInstallmentSummary()
```

### `updateInstallmentSummary()`
**What it does:** Validates installment plan and updates status

```javascript
if installment_type == "full":
    installmentTotal = netTotal
else:
    installmentTotal = sum of all amount_due_{i} inputs

difference = netTotal - installmentTotal

// Update display fields
installment_total.text = installmentTotal.toFixed(2)
difference_total.text = difference.toFixed(2)

if Math.abs(difference) < 0.01:
    balance_status = "Balanced ✅" (green)
else:
    balance_status = "Not Balanced ❌" (red)
```

### `removeItemRow(btn)`, `addItemRow()`
- Remove: Prevents single row deletion; recalculates
- Add: Clones template row; resets values; reinitializes TomSelect

### `removeInstallmentRow(btn)`
- Prevents single row deletion
- Renumbers remaining rows
- Updates all field names (`due_date_1`, `amount_due_1`, etc.)
- Updates installment_count value

### Form Submit Validation
```javascript
document.getElementById("invoiceForm").addEventListener("submit", function(e) {
    const finalTotal = summary_total value
    const installmentTotal = installment_total value
    const type = installment_type value

    if finalTotal <= 0:
        Alert "Please enter at least one valid bill item"
        Prevent submit

    if type == "custom" AND abs(finalTotal - installmentTotal) >= 0.01:
        Alert "Installment total must exactly match net total"
        Prevent submit
})
```

### Window Load
```javascript
window.onload = function() {
    calculateInvoiceTotals()           // Initialize summary
    toggleInstallmentSections()        // Show/hide sections
    initStudentTomSelect()             // Initialize student dropdown
    initAllCourseTomSelects()          // Initialize all course dropdowns
    updateInstallmentSummary()         // Initialize installment section
}
```

### Keyboard Navigation
- Enter key moves focus to next focusable element (smooth data entry flow)

---

## 5. CURRENT INSTALLMENT HANDLING

### What the System Supports

**Two Installment Types:**

#### 1. **Full Payment** (single installment)
- Single `amount_due` equal to total invoice amount
- Single `due_date`
- Single `remarks = "Full payment"`
- `installment_no = 1`

#### 2. **Custom Multi-Installment Plans**
- 2-6 installments (enforced by max=6 in input)
- Each installment:
  - Has unique `due_date`
  - Has `amount_due` (must be > 0)
  - Can have custom `remarks`
  - Numbered sequentially
- **Validation:** Sum of all `amount_due` MUST exactly equal `total_amount`
  - Prevents underpayment/overpayment setup

### Current Installment Fields in Database

```
installment_plans:
- id (PK)
- invoice_id (FK)
- installment_no (sequential)
- due_date (YYYY-MM-DD)
- amount_due (what was agreed to owe)
- amount_paid (updated when receipts received)
- status (pending|partially_paid|paid|overdue)
- remarks (e.g., "Full payment", "First half", "Final payment")
```

### What's NOT Currently Part of Installments

❌ Grace period
❌ Late fees/penalties
❌ Interest charges
❌ Automatic reminders
❌ Payment confirmation
❌ Custom payment modes per installment
❌ Partial installment payment tracking

---

## 6. MULTIPLE ITEMS HANDLING

### How Items Are Currently Handled

**Dynamic Rows:**
- Form captures arrays of values per field name:
  ```
  item_course_id[] = [5, null, 8]
  item_description[] = ["Excel Course", "Books", "Practice Sessions"]
  item_qty[] = [1, 2, 1]
  item_rate[] = [5000, 500, 0]
  item_discount[] = [0, 100, 0]
  ```

**Calculation Per Item:**
```
For each item i:
  gross = qty[i] × rate[i]
  discount = discount[i] (capped at gross)
  line_total = gross - discount
  
  subtotal += gross
  total_discount += discount
  net_total += line_total
```

**Storage:**
- One `invoice_items` row per line item
- Each row includes:
  - course_id (optional)
  - description (required)
  - quantity
  - unit_price
  - line_total (calculated field)

**Discount Handling:**
- Line-level discounts are calculated but NOT stored individually in invoice_items.discount
  - The `discount` column exists but remains 0
  - Discount is implied: `discount = (qty × unit_price) - line_total`
  - Total discounts summed into invoices.discount_amount

**Visual Feedback:**
- Amount column is readonly, auto-updated by JavaScript
- Summary box shows running subtotal, discount, and net total
- All changes recalculate in real-time

---

## 7. CURRENT DISCOUNT ARCHITECTURE

### Discount Levels

**Level 1: Line-Item Level (Per Row)**
- Per-item discount: `item_discount[]`
- Calculated: `qty × rate - line_total`
- Not stored individually (only implied)
- Summed into `invoices.discount_amount`

**Level 2: Invoice Level**
- `invoices.discount_type` (always "none" in current creation flow)
- `invoices.discount_value` (always 0)
- `invoices.discount_amount` (sum of line-level discounts)

### What's Missing

❌ No invoice-level discount option in current form
❌ No discount_type selector (fixed % percentage) not used
❌ No way to apply invoice-total discount during creation
❌ discount column in invoice_items not used

### Discount Edge Cases Handled

1. **Discount Capped at Gross:**
   ```python
   if row_discount > gross:
       row_discount = gross  # Prevent negative line_total
   ```

2. **Per-Row Discount Validation:**
   - Must be >= 0
   - Must be <= item's gross amount

3. **Installment Validation:**
   - Total of all installments must equal net_amount
   - No discount allowance on individual installments

---

## 8. FORM FIELD NAMES & STRUCTURE

### All Form Field Names Submitted

**Invoice Header:**
- `student_id` - Single select value (student.id)
- `invoice_date` - YYYY-MM-DD date
- `installment_type` - "full" or "custom"
- `notes` - Optional text

**Items (Array Format):**
- `item_course_id[]` - Array of course IDs (can be empty/null)
- `item_description[]` - Array of descriptions
- `item_qty[]` - Array of quantities
- `item_rate[]` - Array of unit prices
- `item_discount[]` - Array of line discounts

**Installment Planning:**
- `full_due_date` - Only if installment_type="full"

**Custom Installments (if installment_type="custom"):**
- `installment_count` - Number of installments (2-6)
- `due_date_{i}` - Due date for installment i
- `amount_due_{i}` - Amount for installment i
- `remarks_{i}` - Remarks for installment i

---

## 9. FLOW DIAGRAM: Create Invoice

```
┌─ GET /billing/invoice/new
│  ├─ Load students (active, sorted by name)
│  ├─ Load courses (active, sorted by name)
│  ├─ Pass today's date to template
│  └─ Render empty form
│
└─ POST /billing/invoice/new
   ├─ Extract form fields
   ├─ Validate student exists & has branch
   ├─ Process item rows
   │  ├─ Skip empty rows
   │  ├─ Validate required fields
   │  ├─ Calculate gross, discount, line_total
   │  └─ Accumulate subtotal, discount, total
   ├─ Create invoice record (status=unpaid, installment_type stored)
   ├─ Auto-generate invoice_no (GIT/B/###)
   ├─ Insert invoice_items rows (one per item)
   ├─ IF installment_type = "full"
   │  └─ Insert 1 installment_plans row with full amount & due_date
   ├─ ELSE (custom)
   │  ├─ Validate installment_count > 0
   │  ├─ For each installment i
   │  │  ├─ Get due_date, amount, remarks
   │  │  ├─ Validate amount > 0
   │  │  └─ Insert installment_plans row
   │  └─ Validate SUM(amount_due) == total_amount
   ├─ Commit transaction
   ├─ Log activity (action_type="create", module="invoices")
   └─ Redirect to invoice_view
```

---

## 10. VISUAL APPEARANCE (Key UI Elements)

### Layout
- **Sticky Summary Box** on right (top: 80px)
  - Remains visible while scrolling through items
  - Shows running totals and balance status
  - Contains save button at bottom

- **Two-Column Responsive Layout**
  - Desktop (> 1200px): 2fr main area + 360px sidebar
  - Tablet (≤ 1200px): Stacked to 1 column, summary no longer sticky
  - Mobile (≤ 768px): Single column, compact layout

### Colors & Status
- Subtotal: Black text
- Discount: Black text (negative impact)
- Net Total: **Bold 16px font**
- Status: 
  - ✅ Green "Balanced ✅" when difference < ₹0.01
  - ❌ Red "Not Balanced ❌" when difference ≥ ₹0.01
- Alert backgrounds: #f0f4f8 (light blue) for edit mode info

### Form Fields
- Bootstrap-styled inputs (border: #ced4da, focus: #0d6efd)
- TomSelect dropdowns for student & course selection
- Required field indicators: HTML5 `required` attribute
- Numeric inputs with step=0.01 for currency fields

---

## 11. KNOWN ISSUES & LIMITATIONS

### Issue 1: Discount Column Not Utilized
- `invoice_items.discount` column exists but always remains 0
- Line discounts are recalculated from: `(qty × unit_price) - line_total`
- Should populate discount column for data integrity

### Issue 2: invoice_items.discount Migration
- Database schema was updated to add this column (line 512 in db.py)
- But creation code doesn't populate it
- Recommend: Update INSERT to store discount value

### Issue 3: Discount Type Support
- Database supports: 'none', 'fixed', 'percentage'
- But form always sets 'none', never uses discount_value
- No UI for invoice-level discount application

### Issue 4: No Student Photo in Form
- Student table has `photo_filename` column
- But invoice form doesn't display/reference it

### Issue 5: Branch Assignment
- If student has no branch_id, invoice creation fails
- "Selected student does not have a branch assigned"

### Issue 6: Installment Validation
- Sum validation is done after all inserts start
- If validation fails, items/first installment already inserted
- Should validate installment total BEFORE any inserts

### Issue 7: Database Photo Column Error (from logs)
- Error: `sqlite3.OperationalError: table students has no column named photo_filename`
- Column exists in schema but wasn't in initial table
- Migration added it, but may need to run `flask db upgrade`

---

## 12. RELATED TABLES & RELATIONSHIPS

### Parent Tables (referenced in invoices)
- **students** - Student being billed
- **users** - User creating invoice (created_by)
- **branches** - Branch location of student

### Child Tables (depend on invoices)
- **invoice_items** (CASCADE DELETE)
- **installment_plans** (CASCADE DELETE)
- **receipts** (relates to invoices, payments)
- **bad_debt_writeoffs** (relates to invoices)

### Related Features (not in creation flow)
- **Receipts** - Payment records against invoices
- **Attendance/Orders** - May reference invoices
- **Reports** - Query invoices for analytics

---

## SUMMARY TABLE

| Aspect | Details |
|--------|---------|
| **Route Handler** | `@billing_bp.route("/invoice/new", methods=["GET", "POST"])` |
| **Template** | `templates/billing/invoice_form.html` |
| **Database Tables** | invoices, invoice_items, installment_plans, courses, students |
| **Multiple Items** | Dynamic table rows with real-time calculation |
| **Line-Level Discount** | Per-item discount field (calculated but not fully stored) |
| **Invoice-Level Discount** | Database support exists but not in current form |
| **Installment Types** | "full" (1 payment) or "custom" (2-6 payments) |
| **Auto Generated Fields** | invoice_no (GIT/B/###), subtotal, total, discount_amount |
| **Validation** | Student + branch required, items required, installment total matched |
| **Form Submission** | JavaScript prevents invalid states (zero total, unbalanced installments) |
| **Redirect Success** | Redirects to `invoice_view` for the new invoice |

