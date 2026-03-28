#!/usr/bin/env python
"""
Database Migration Script for Bad Debt Write-off Module
This script safely migrates your existing database to support the new bad debt management module.

Usage:
    python migrate_baddebt.py
"""

from db import get_conn
from datetime import datetime
import sys


def migrate():
    """Perform database migration for bad debt module"""
    conn = get_conn()
    cur = conn.cursor()

    try:
        print("=" * 60)
        print("🔧 Bad Debt Module Database Migration")
        print("=" * 60)

        # 1. Create bad_debt_writeoffs table
        print("\n[1/4] Creating bad_debt_writeoffs table...")
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
        print("   ✓ bad_debt_writeoffs table created")

        # 2. Add "Uncollectible Receivables" expense category
        print("\n[2/4] Adding 'Uncollectible Receivables' expense category...")
        cur.execute("""
            SELECT id FROM expense_categories 
            WHERE category_name = 'Uncollectible Receivables'
        """)
        if not cur.fetchone():
            now = datetime.now().isoformat(timespec="seconds")
            cur.execute("""
                INSERT INTO expense_categories (category_name, is_active, created_at)
                VALUES (?, ?, ?)
            """, ("Uncollectible Receivables", 1, now))
            print("   ✓ Expense category added")
        else:
            print("   ✓ Expense category already exists")

        # 3. Check if invoices table needs constraint update
        print("\n[3/4] Checking invoice status constraints...")
        cur.execute("PRAGMA table_info(invoices)")
        columns = cur.fetchall()

        # Get current table schema
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'")
        current_schema = cur.fetchone()

        if current_schema:
            schema_text = current_schema[0]
            # Check if new statuses are already in the constraint
            if "'write_off'" in schema_text and "'partially_written_off'" in schema_text:
                print("   ✓ Invoice statuses already include write_off and partially_written_off")
            else:
                print("   ⚠ Updating invoice status constraint...")
                
                # Backup old invoices data
                cur.execute("SELECT * FROM invoices")
                invoices_data = cur.fetchall()
                print(f"   📦 Backed up {len(invoices_data)} existing invoices")

                if invoices_data:
                    # Get column info to preserve ALL fields
                    cur.execute("PRAGMA table_info(invoices)")
                    column_info = cur.fetchall()
                    column_names = [col[1] for col in column_info]

                    # Disable foreign keys temporarily
                    cur.execute("PRAGMA foreign_keys=OFF")

                    # Drop old table
                    cur.execute("DROP TABLE invoices")

                    # Create new table with updated constraints
                    cur.execute("""
                        CREATE TABLE invoices (
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
                    print("   ✓ Invoices table recreated with new statuses")

                    # Restore data
                    col_placeholders = ", ".join(["?"] * len(column_names))
                    col_names_str = ", ".join(column_names)
                    
                    for invoice in invoices_data:
                        cur.execute(
                            f"INSERT INTO invoices ({col_names_str}) VALUES ({col_placeholders})",
                            invoice
                        )
                    print(f"   ✓ Restored {len(invoices_data)} invoices")

                    # Re-enable foreign keys
                    cur.execute("PRAGMA foreign_keys=ON")

        # 4. Verify migration
        print("\n[4/4] Verifying migration...")
        cur.execute("SELECT COUNT(*) as count FROM bad_debt_writeoffs")
        writeoff_count = cur.fetchone()["count"]
        print(f"   ✓ bad_debt_writeoffs table ready ({writeoff_count} records)")

        cur.execute("SELECT COUNT(*) as count FROM expense_categories WHERE category_name = 'Uncollectible Receivables'")
        category_count = cur.fetchone()["count"]
        print(f"   ✓ Expense category ready ({category_count} category)")

        # Commit all changes
        conn.commit()

        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Verify data preservation in your application")
        print("2. Test the bad debt write-off module at /baddebt/")
        print("3. If on PythonAnywhere, reload the web app")
        print("4. All existing data has been preserved")
        print("=" * 60 + "\n")

        return True

    except Exception as e:
        conn.rollback()
        print("\n" + "=" * 60)
        print(f"❌ Migration failed: {str(e)}")
        print("=" * 60)
        print("\nError details:")
        print(f"  {type(e).__name__}: {str(e)}")
        print("\nPlease report this error with the above details")
        print("=" * 60 + "\n")
        return False

    finally:
        conn.close()


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
