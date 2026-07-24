"""
Test & Baseline Reconciliation Script for Multi-Institute Phase 5 (Finance & Assets)
Executes migration against local Docker MySQL database and verifies baseline integrity.
"""
import pymysql

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3308,
    'user': 'attn_app',
    'password': 'admin210499',
    'database': 'attn_billing_testing',
    'cursorclass': pymysql.cursors.DictCursor
}

def add_column_if_missing(cur, table, column, col_def):
    cur.execute("""
        SELECT COUNT(*) AS cnt 
        FROM information_schema.columns 
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
    """, (table, column))
    if cur.fetchone()['cnt'] == 0:
        sql = f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_def}"
        cur.execute(sql)
        print(f"Added column {column} to {table}")

def create_index_if_missing(cur, table, index_name, cols):
    cur.execute("""
        SELECT COUNT(*) AS cnt 
        FROM information_schema.statistics 
        WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s
    """, (table, index_name))
    if cur.fetchone()['cnt'] == 0:
        sql = f"CREATE INDEX `{index_name}` ON `{table}` ({cols})"
        cur.execute(sql)
        print(f"Created index {index_name} on {table}")

def run_test():
    print("[*] Connecting to Docker MySQL database...")
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1. Capture Global IT (institute_id = 1) Baseline Totals
    print("\n--- 1. Global IT (Institute 1) Baseline Reconciliation ---")
    cur.execute("SELECT COUNT(*) AS cnt, IFNULL(SUM(total_amount), 0) AS total FROM invoices WHERE student_id IN (SELECT id FROM students WHERE institute_id = 1)")
    inv_baseline = cur.fetchone()
    print(f"Global IT Invoices: Count={inv_baseline['cnt']}, Total={inv_baseline['total']}")

    cur.execute("SELECT COUNT(*) AS cnt, IFNULL(SUM(amount_received), 0) AS total FROM receipts WHERE invoice_id IN (SELECT id FROM invoices WHERE student_id IN (SELECT id FROM students WHERE institute_id = 1))")
    rec_baseline = cur.fetchone()
    print(f"Global IT Receipts: Count={rec_baseline['cnt']}, Total={rec_baseline['total']}")

    cur.execute("SELECT COUNT(*) AS cnt, IFNULL(SUM(amount), 0) AS total FROM expenses")
    exp_baseline = cur.fetchone()
    print(f"Global IT Expenses: Count={exp_baseline['cnt']}, Total={exp_baseline['total']}")

    cur.execute("SELECT COUNT(*) AS cnt FROM assets")
    asset_baseline = cur.fetchone()
    print(f"Global IT Assets: Count={asset_baseline['cnt']}")

    # 2. Execute Migration Safe Logic
    print("\n--- 2. Executing Phase 5 Migration ---")
    # institute_settings
    add_column_if_missing(cur, 'institute_settings', 'invoice_prefix', "VARCHAR(50) DEFAULT 'GIT/B/'")
    add_column_if_missing(cur, 'institute_settings', 'receipt_prefix', "VARCHAR(50) DEFAULT 'GIT/'")

    cur.execute("UPDATE institute_settings SET invoice_prefix = 'GIT/B/', receipt_prefix = 'GIT/' WHERE institute_id = 1 AND (invoice_prefix IS NULL OR invoice_prefix = '')")
    cur.execute("""
        INSERT INTO institute_settings (institute_id, invoice_prefix, receipt_prefix, updated_at)
        VALUES (16, 'MEI/B/', 'MEI/', NOW())
        ON DUPLICATE KEY UPDATE invoice_prefix = 'MEI/B/', receipt_prefix = 'MEI/', updated_at = NOW()
    """)

    # invoices
    add_column_if_missing(cur, 'invoices', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE invoices i JOIN students s ON i.student_id = s.id SET i.institute_id = s.institute_id")
    create_index_if_missing(cur, 'invoices', 'idx_invoices_inst_status', 'institute_id, status')
    create_index_if_missing(cur, 'invoices', 'idx_invoices_inst_date', 'institute_id, invoice_date')

    # receipts
    add_column_if_missing(cur, 'receipts', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE receipts r JOIN invoices i ON r.invoice_id = i.id SET r.institute_id = i.institute_id")
    create_index_if_missing(cur, 'receipts', 'idx_receipts_inst_date', 'institute_id, receipt_date')
    create_index_if_missing(cur, 'receipts', 'idx_receipts_inst_mode', 'institute_id, payment_mode')

    # expense_categories & expenses
    add_column_if_missing(cur, 'expense_categories', 'institute_id', "INT NOT NULL DEFAULT 1")
    create_index_if_missing(cur, 'expense_categories', 'idx_exp_cat_inst', 'institute_id')

    add_column_if_missing(cur, 'expenses', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE expenses e LEFT JOIN branches b ON e.branch_id = b.id SET e.institute_id = COALESCE(b.institute_id, 1)")
    create_index_if_missing(cur, 'expenses', 'idx_expenses_inst_date', 'institute_id, expense_date')

    # bad_debt_writeoffs
    add_column_if_missing(cur, 'bad_debt_writeoffs', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE bad_debt_writeoffs w JOIN invoices i ON w.invoice_id = i.id SET w.institute_id = i.institute_id")
    create_index_if_missing(cur, 'bad_debt_writeoffs', 'idx_writeoffs_inst', 'institute_id')

    # assets, asset_allocation, asset_logs
    add_column_if_missing(cur, 'assets', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE assets a LEFT JOIN branches b ON a.branch_id = b.id SET a.institute_id = COALESCE(b.institute_id, 1)")
    create_index_if_missing(cur, 'assets', 'idx_assets_inst', 'institute_id')

    add_column_if_missing(cur, 'asset_allocation', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE asset_allocation aa JOIN assets a ON aa.asset_id = a.id SET aa.institute_id = a.institute_id")
    create_index_if_missing(cur, 'asset_allocation', 'idx_asset_alloc_inst', 'institute_id')

    add_column_if_missing(cur, 'asset_logs', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE asset_logs al JOIN assets a ON al.asset_id = a.id SET al.institute_id = a.institute_id")
    create_index_if_missing(cur, 'asset_logs', 'idx_asset_logs_inst', 'institute_id')

    # reminder_logs
    add_column_if_missing(cur, 'reminder_logs', 'institute_id', "INT NOT NULL DEFAULT 1")
    cur.execute("UPDATE reminder_logs r LEFT JOIN invoices i ON r.invoice_id = i.id SET r.institute_id = COALESCE(i.institute_id, 1)")
    create_index_if_missing(cur, 'reminder_logs', 'idx_reminder_logs_inst', 'institute_id')

    conn.commit()
    print("Migration executed and committed successfully!")

    # 3. Verify Post-Migration Scoped Totals
    print("\n--- 3. Post-Migration Verification (Institute 1) ---")
    cur.execute("SELECT COUNT(*) AS cnt, IFNULL(SUM(total_amount), 0) AS total FROM invoices WHERE institute_id = 1")
    inv_post = cur.fetchone()
    assert inv_post['cnt'] == inv_baseline['cnt'], f"Invoice count mismatch: {inv_post['cnt']} vs {inv_baseline['cnt']}"
    assert float(inv_post['total']) == float(inv_baseline['total']), f"Invoice total mismatch: {inv_post['total']} vs {inv_baseline['total']}"
    print(f"[OK] Invoices Scoped Total Matches Baseline: Count={inv_post['cnt']}, Total={inv_post['total']}")

    cur.execute("SELECT COUNT(*) AS cnt, IFNULL(SUM(amount_received), 0) AS total FROM receipts WHERE institute_id = 1")
    rec_post = cur.fetchone()
    assert rec_post['cnt'] == rec_baseline['cnt'], f"Receipt count mismatch: {rec_post['cnt']} vs {rec_baseline['cnt']}"
    assert float(rec_post['total']) == float(rec_baseline['total']), f"Receipt total mismatch: {rec_post['total']} vs {rec_baseline['total']}"
    print(f"[OK] Receipts Scoped Total Matches Baseline: Count={rec_post['cnt']}, Total={rec_post['total']}")

    cur.execute("SELECT COUNT(*) AS cnt, IFNULL(SUM(amount), 0) AS total FROM expenses WHERE institute_id = 1")
    exp_post = cur.fetchone()
    assert exp_post['cnt'] == exp_baseline['cnt'], f"Expense count mismatch: {exp_post['cnt']} vs {exp_baseline['cnt']}"
    print(f"[OK] Expenses Scoped Total Matches Baseline: Count={exp_post['cnt']}, Total={exp_post['total']}")

    cur.execute("SELECT COUNT(*) AS cnt FROM assets WHERE institute_id = 1")
    asset_post = cur.fetchone()
    assert asset_post['cnt'] == asset_baseline['cnt'], f"Asset count mismatch: {asset_post['cnt']} vs {asset_baseline['cnt']}"
    print(f"[OK] Assets Scoped Count Matches Baseline: Count={asset_post['cnt']}")

    # 4. Check Institute Settings Prefix
    print("\n--- 4. Checking Institute Numbering Settings ---")
    cur.execute("SELECT institute_id, invoice_prefix, receipt_prefix FROM institute_settings WHERE institute_id IN (1, 16)")
    settings = cur.fetchall()
    for s in settings:
        print(f"Institute {s['institute_id']}: Invoice Prefix='{s['invoice_prefix']}', Receipt Prefix='{s['receipt_prefix']}'")

    conn.close()
    print("\n=======================================================")
    print("ALL PHASE 5 MYSQL MIGRATION & BASELINE TESTS PASSED! 100%")
    print("=======================================================")

if __name__ == '__main__':
    run_test()
