import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA synchronous = NORMAL;")

    def parse_ddmmyyyy(date_str):
        if not date_str:
            return None
        try:
            if "-" in date_str:
                parts = date_str.split("-")
                if len(parts) == 3:
                    first_part = int(parts[0])
                    if first_part > 31:
                        return date_str
                    else:
                        day, month, year = parts
                        return f"{year}-{month}-{day}"
        except:
            pass
        return date_str

    conn.create_function("parse_date", 1, parse_ddmmyyyy)
    return conn


def log_activity(user_id, branch_id, action_type, module_name, record_id, description):
    conn = get_conn()
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute("""
            INSERT INTO activity_logs (
                user_id,
                branch_id,
                action_type,
                module_name,
                record_id,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            branch_id,
            action_type,
            module_name,
            record_id,
            description,
            now
        ))
        conn.commit()
    finally:
        conn.close()


def add_column_if_not_exists(cur, table_name, column_name, column_def):
    try:
        cur.execute(f"PRAGMA table_info({table_name})")
        columns = [row["name"] for row in cur.fetchall()]
        if column_name not in columns:
            clean_def = column_def.replace(" UNIQUE", "").replace("UNIQUE ", "")
            cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {clean_def}")
    except Exception as e:
        print(f"Warning: Could not add column {column_name} to {table_name}: {e}")


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    # ---------- BRANCHES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_name TEXT NOT NULL UNIQUE,
            branch_code TEXT NOT NULL UNIQUE,
            address TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # ---------- USERS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
            phone TEXT,
            branch_id INTEGER,
            can_view_all_branches INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # ---------- LEADS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            whatsapp TEXT,
            gender TEXT,
            age INTEGER,
            education_status TEXT,
            stream TEXT,
            institute_name TEXT,
            career_goal TEXT,
            interested_courses TEXT,
            lead_source TEXT,
            decision_maker TEXT DEFAULT 'Self',
            start_timeframe TEXT,
            lead_score INTEGER DEFAULT 0,
            stage TEXT DEFAULT 'New Lead',
            status TEXT DEFAULT 'active',
            lost_reason TEXT,
            last_contact_date TEXT,
            next_followup_date TEXT,
            followup_count INTEGER DEFAULT 0,
            lead_location TEXT
                CHECK(lead_location IN ('rural', 'urban')),
            notes TEXT,
            is_deleted INTEGER DEFAULT 0,
            assigned_to_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (assigned_to_id) REFERENCES users(id)
        )
    """)

    # ---------- FOLLOWUPS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            user_id INTEGER,
            method TEXT,
            outcome TEXT,
            note TEXT,
            next_followup_date TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # ---------- STUDENTS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            address TEXT,
            joined_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'completed', 'dropped')),
            gender TEXT,
            education_level TEXT,
            qualification TEXT,
            employment_status TEXT DEFAULT 'unemployed',
            branch_id INTEGER,
            date_of_birth TEXT,
            parent_name TEXT,
            parent_contact TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # ---------- COURSES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL UNIQUE,
            duration TEXT,
            fee REAL NOT NULL DEFAULT 0,
            course_type TEXT DEFAULT 'standard',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)

    # ---------- BATCHES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_name TEXT NOT NULL,
            course_id INTEGER,
            branch_id INTEGER NOT NULL,
            start_date TEXT,
            end_date TEXT,
            start_time TEXT,
            end_time TEXT,
            trainer_id INTEGER,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'completed', 'cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id),
            FOREIGN KEY (trainer_id) REFERENCES users(id)
        )
    """)

    # ---------- STUDENT BATCH MAP ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            joined_on TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'completed', 'dropped')),
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(student_id, batch_id),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
        )
    """)

    # ---------- ATTENDANCE RECORDS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_date TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'absent'
                CHECK(status IN ('present', 'absent', 'late', 'leave')),
            remarks TEXT,
            marked_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(attendance_date, student_id, batch_id),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id),
            FOREIGN KEY (marked_by) REFERENCES users(id)
        )
    """)

    # ---------- ATTENDANCE TIME WARNINGS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_time_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            attendance_status TEXT NOT NULL,
            marked_at TEXT NOT NULL,
            actual_time TEXT NOT NULL,
            batch_start_time TEXT,
            batch_end_time TEXT,
            warning_type TEXT NOT NULL
                CHECK(warning_type IN ('before_start', 'after_end')),
            marked_by INTEGER,
            UNIQUE(batch_id, student_id, attendance_date),
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (marked_by) REFERENCES users(id)
        )
    """)

    # ---------- ATTENDANCE FOLLOWUPS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            batch_id INTEGER,
            followup_date TEXT NOT NULL,
            reason TEXT,
            action_taken TEXT,
            followup_status TEXT NOT NULL DEFAULT 'pending'
                CHECK(followup_status IN ('pending', 'contacted', 'resolved', 'no_response')),
            last_followup_date TEXT,
            remarks TEXT,
            notes TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE,
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # ---------- INVOICES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT NOT NULL UNIQUE,
            student_id INTEGER NOT NULL,
            invoice_date TEXT NOT NULL,
            subtotal REAL NOT NULL DEFAULT 0,
            discount_type TEXT NOT NULL DEFAULT 'none'
                CHECK(discount_type IN ('none', 'fixed', 'percentage')),
            discount_value REAL NOT NULL DEFAULT 0,
            discount_amount REAL NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,
            installment_type TEXT NOT NULL DEFAULT 'full'
                CHECK(installment_type IN ('full', 'custom')),
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'unpaid'
                CHECK(status IN ('unpaid', 'partially_paid', 'paid', 'cancelled', 'write_off', 'partially_written_off')),
            created_by INTEGER NOT NULL,
            branch_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (created_by) REFERENCES users(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # ---------- INVOICE ITEMS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            course_id INTEGER,
            description TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL DEFAULT 0,
            discount REAL NOT NULL DEFAULT 0,
            line_total REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    """)

    # ---------- INSTALLMENT PLANS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS installment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            installment_no INTEGER NOT NULL,
            due_date TEXT NOT NULL,
            amount_due REAL NOT NULL DEFAULT 0,
            amount_paid REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'partially_paid', 'paid', 'overdue')),
            remarks TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        )
    """)

    # ---------- RECEIPTS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_no TEXT NOT NULL UNIQUE,
            invoice_id INTEGER NOT NULL,
            receipt_date TEXT NOT NULL,
            amount_received REAL NOT NULL DEFAULT 0,
            payment_mode TEXT DEFAULT 'cash',
            notes TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # ---------- BAD DEBT WRITE-OFFS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bad_debt_writeoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            amount_written_off REAL NOT NULL,
            paid_amount REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL,
            student_status_at_writeoff TEXT,
            authorized_by INTEGER,
            writeoff_date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id),
            FOREIGN KEY (authorized_by) REFERENCES users(id)
        )
    """)

    # ---------- EXPENSE CATEGORIES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expense_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # ---------- EXPENSES ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_date TEXT NOT NULL,
            branch_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            payment_mode TEXT NOT NULL
                CHECK(payment_mode IN ('cash', 'upi', 'bank_transfer', 'card')),
            reference_no TEXT,
            notes TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches(id),
            FOREIGN KEY (category_id) REFERENCES expense_categories(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # ---------- ACTIVITY LOGS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            branch_id INTEGER,
            action_type TEXT NOT NULL,
            module_name TEXT NOT NULL,
            record_id INTEGER,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # ---------- ASSETS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_code TEXT NOT NULL UNIQUE,
            asset_name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT,
            purchase_date TEXT,
            purchase_cost REAL DEFAULT 0,
            condition TEXT DEFAULT 'Good'
                CHECK(condition IN ('Good', 'Repair', 'Damaged')),
            status TEXT DEFAULT 'Active'
                CHECK(status IN ('Active', 'In Repair', 'Disposed')),
            branch_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # ---------- ASSET ALLOCATION ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS asset_allocation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            assigned_to TEXT NOT NULL,
            assigned_role TEXT NOT NULL
                CHECK(assigned_role IN ('staff', 'student')),
            assigned_date TEXT NOT NULL,
            return_date TEXT,
            status TEXT DEFAULT 'Allocated'
                CHECK(status IN ('Allocated', 'Returned')),
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
        )
    """)

    # ---------- ASSET LOGS ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS asset_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            action TEXT NOT NULL
                CHECK(action IN ('Created', 'Assigned', 'Returned', 'Repaired', 'Disposed', 'Updated')),
            description TEXT,
            done_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
            FOREIGN KEY (done_by) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reminder_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            installment_id INTEGER NOT NULL,
            phone_number TEXT,
            reminder_type TEXT NOT NULL,
            message_text TEXT NOT NULL,
            status TEXT NOT NULL,
            sent_via TEXT NOT NULL,
            followup_note TEXT,
            sent_by INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(invoice_id) REFERENCES invoices(id),
            FOREIGN KEY(installment_id) REFERENCES installment_plans(id),
            FOREIGN KEY(sent_by) REFERENCES users(id)
        )
    """)

    # ---------- SAFE MIGRATIONS ----------
    add_column_if_not_exists(cur, "users", "phone", "TEXT")
    add_column_if_not_exists(cur, "users", "branch_id", "INTEGER")
    add_column_if_not_exists(cur, "users", "can_view_all_branches", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_not_exists(cur, "users", "updated_at", "TEXT")

    add_column_if_not_exists(cur, "students", "gender", "TEXT")
    add_column_if_not_exists(cur, "students", "education_level", "TEXT")
    add_column_if_not_exists(cur, "students", "qualification", "TEXT")
    add_column_if_not_exists(cur, "students", "employment_status", "TEXT DEFAULT 'unemployed'")
    add_column_if_not_exists(cur, "students", "branch_id", "INTEGER")
    add_column_if_not_exists(cur, "students", "student_location", "TEXT")
    add_column_if_not_exists(cur, "students", "date_of_birth", "TEXT")
    add_column_if_not_exists(cur, "students", "parent_name", "TEXT")
    add_column_if_not_exists(cur, "students", "parent_contact", "TEXT")
    add_column_if_not_exists(cur, "students", "photo_filename", "TEXT")
    add_column_if_not_exists(cur, "students", "student_signature_filename", "TEXT")
    add_column_if_not_exists(cur, "students", "student_signature_date", "TEXT")
    add_column_if_not_exists(cur, "students", "parent_signature_filename", "TEXT")
    add_column_if_not_exists(cur, "students", "parent_signature_date", "TEXT")
    add_column_if_not_exists(cur, "leads", "lead_location", "TEXT")

    add_column_if_not_exists(cur, "courses", "course_type", "TEXT DEFAULT 'standard'")

    add_column_if_not_exists(cur, "invoices", "branch_id", "INTEGER")

    add_column_if_not_exists(cur, "invoice_items", "discount", "REAL NOT NULL DEFAULT 0")

    add_column_if_not_exists(cur, "receipts", "payment_mode", "TEXT DEFAULT 'cash'")
    add_column_if_not_exists(cur, "receipts", "notes", "TEXT")

    add_column_if_not_exists(cur, "branches", "no_of_computers", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_not_exists(cur, "branches", "opening_time", "TEXT")
    add_column_if_not_exists(cur, "branches", "closing_time", "TEXT")

    # ---------- MIGRATE asset_logs CONSTRAINT ----------
    # Update asset_logs table to allow 'Updated' action
    try:
        cur.execute("PRAGMA table_info(asset_logs)")
        if cur.fetchone():
            # Create backupof asset_logs data
            cur.execute("SELECT * FROM asset_logs")
            backup_data = cur.fetchall()
            
            # Drop old table and create new one with updated constraint
            cur.execute("DROP TABLE IF EXISTS asset_logs")
            cur.execute("""
                CREATE TABLE asset_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    action TEXT NOT NULL
                        CHECK(action IN ('Created', 'Assigned', 'Returned', 'Repaired', 'Disposed', 'Updated')),
                    description TEXT,
                    done_by INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                    FOREIGN KEY (done_by) REFERENCES users(id)
                )
            """)
            
            # Restore data if exists
            if backup_data:
                for row in backup_data:
                    cur.execute("""
                        INSERT INTO asset_logs (id, asset_id, action, description, done_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (row["id"], row["asset_id"], row["action"], row["description"], row["done_by"], row["created_at"]))
    except:
        pass

    # ---------- DEFAULT BRANCHES ----------
    cur.execute("SELECT id FROM branches WHERE branch_code = ?", ("HO",))
    ho_branch = cur.fetchone()
    if not ho_branch:
        cur.execute("""
            INSERT INTO branches (branch_name, branch_code, address, is_active, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Global IT Education Head Office",
            "HO",
            "T G Extension, Opposite to B M Lab, Hoskote",
            1,
            now
        ))

    cur.execute("SELECT id FROM branches WHERE branch_code = ?", ("HB",))
    hb_branch = cur.fetchone()
    if not hb_branch:
        cur.execute("""
            INSERT INTO branches (branch_name, branch_code, address, is_active, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Global IT Education – Hoskote Branch",
            "HB",
            "College Road, Near Ayyappa Swamy Temple, Hoskote",
            1,
            now
        ))

    cur.execute("SELECT id FROM branches WHERE branch_code = ?", ("HO",))
    head_office = cur.fetchone()
    head_office_id = head_office["id"] if head_office else 1

    # ---------- DEFAULT ADMIN USER ----------
    cur.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    existing_admin = cur.fetchone()

    if not existing_admin:
        cur.execute("""
            INSERT INTO users (
                full_name,
                username,
                password_hash,
                role,
                phone,
                branch_id,
                can_view_all_branches,
                is_active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Administrator",
            "admin",
            generate_password_hash("admin123"),
            "admin",
            "",
            head_office_id,
            1,
            1,
            now,
            now
        ))

    # ---------- BACKFILL OLD DATA ----------
    cur.execute("UPDATE users SET branch_id = ? WHERE branch_id IS NULL", (head_office_id,))
    cur.execute("UPDATE users SET can_view_all_branches = 1 WHERE can_view_all_branches IS NULL")

    cur.execute("UPDATE students SET branch_id = ? WHERE branch_id IS NULL", (head_office_id,))
    cur.execute("UPDATE invoices SET branch_id = ? WHERE branch_id IS NULL", (head_office_id,))

    # ---------- DEFAULT EXPENSE CATEGORIES ----------
    default_categories = [
        "Rent",
        "Salary",
        "Electricity",
        "Internet",
        "Marketing",
        "Stationery",
        "Travel",
        "Maintenance",
        "Tea/Snacks",
        "Software/Tools",
        "Uncollectible Receivables",
        "Miscellaneous"
    ]

    for category_name in default_categories:
        cur.execute("SELECT id FROM expense_categories WHERE category_name = ?", (category_name,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO expense_categories (category_name, is_active, created_at)
                VALUES (?, ?, ?)
            """, (category_name, 1, now))

    # ---------- RECEIPT DATE STANDARDIZATION ----------
    try:
        cur.execute("SELECT id, receipt_date FROM receipts WHERE receipt_date IS NOT NULL")
        receipt_dates = cur.fetchall()

        for receipt in receipt_dates:
            date_str = receipt["receipt_date"]
            if date_str and "-" in date_str:
                parts = date_str.split("-")
                if len(parts) == 3:
                    try:
                        first_part = int(parts[0])
                        if first_part <= 31:
                            day, month, year_val = parts
                            normalized_date = f"{year_val}-{month}-{day}"
                            cur.execute("""
                                UPDATE receipts
                                SET receipt_date = ?
                                WHERE id = ?
                            """, (normalized_date, receipt["id"]))
                    except:
                        pass
    except:
        pass

    # ---------- RECEIPT NUMBER NORMALIZATION ----------
    try:
        cur.execute("""
            SELECT id, receipt_no
            FROM receipts
            WHERE receipt_no LIKE 'GIT/P/%' OR receipt_no LIKE 'RCP%'
            ORDER BY id ASC
        """)
        old_receipts = cur.fetchall()

        for receipt in old_receipts:
            new_receipt_no = f"GIT/{receipt['id']}"
            cur.execute("""
                UPDATE receipts
                SET receipt_no = ?
                WHERE id = ?
            """, (new_receipt_no, receipt["id"]))
    except:
        pass

    # ---------- RECALCULATE INVOICE STATUS ----------
    try:
        cur.execute("SELECT id, total_amount FROM invoices")
        all_invoices = cur.fetchall()

        for invoice in all_invoices:
            invoice_id = invoice["id"]
            total_amount = float(invoice["total_amount"] or 0)

            cur.execute("""
                SELECT IFNULL(SUM(amount_received), 0) AS total_received
                FROM receipts
                WHERE invoice_id = ?
            """, (invoice_id,))
            receipt_result = cur.fetchone()
            total_received = float(receipt_result["total_received"] or 0)

            if total_received >= total_amount and total_amount > 0:
                new_status = "paid"
            elif total_received > 0:
                new_status = "partially_paid"
            else:
                new_status = "unpaid"

            cur.execute("""
                UPDATE invoices
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (new_status, now, invoice_id))
    except:
        pass

    # ---------- MIGRATIONS ----------
    try:
        # Add branch_id to attendance_followups if missing
        add_column_if_not_exists(cur, 'attendance_followups', 'branch_id', 'INTEGER NOT NULL DEFAULT 1')
        
        # Add last_followup_date to attendance_followups if missing
        add_column_if_not_exists(cur, 'attendance_followups', 'last_followup_date', 'TEXT')
        
        # Add remarks to attendance_followups if missing
        add_column_if_not_exists(cur, 'attendance_followups', 'remarks', 'TEXT')
    except:
        pass

    conn.commit()
    conn.close()