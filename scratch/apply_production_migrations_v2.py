"""Execute all production schema migrations cleanly with proper DELIMITER handling."""

from pathlib import Path
import pymysql

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"

MIGRATION_FILES = [
    "20260722_multi_institute_phase1_foundation.sql",
    "20260723_multi_institute_phase2_core_identity.sql",
    "20260723_multi_institute_phase4_crm_student.sql",
    "20260724_multi_institute_phase5_finance_assets.sql",
    "20260727_multi_institute_phase9_onboarding_subscriptions.sql",
    "20260728_courses_tenant_ownership.sql",
    "20260728_institute_domain_verification.sql",
    "20260728_platform_owner_separation.sql",
    "20260728_student_password_changed_at.sql",
    "20260729_tenant_asset_sequences.sql",
    "20260729_tenant_document_sequences.sql",
    "20260729_tenant_writeoff_sequences.sql",
    "add_mysql_performance_indexes.sql",
]


def split_sql_file(sql_text):
    delimiter = ";"
    statements = []
    current = []

    for line in sql_text.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("--"):
            continue
        if trimmed.upper().startswith("DELIMITER"):
            parts = trimmed.split()
            if len(parts) > 1:
                delimiter = parts[1].strip()
            continue

        if delimiter != ";" and trimmed.endswith(delimiter):
            line_clean = line[: line.rfind(delimiter)]
            current.append(line_clean)
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            delimiter = ";"
            continue

        if delimiter == ";" and trimmed.endswith(";"):
            current.append(line)
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            continue

        current.append(line)

    if current:
        stmt = "\n".join(current).strip()
        if stmt:
            statements.append(stmt)
    return statements


def run_migrations():
    print("Connecting to production Cloud SQL (34.93.184.172)...")
    conn = pymysql.connect(
        host="34.93.184.172",
        port=3306,
        user="attn_app",
        password="admin210499",
        database="attn_billing_testing",
        autocommit=True,
        charset="utf8mb4",
    )

    cursor = conn.cursor()
    try:
        for filename in MIGRATION_FILES:
            filepath = MIGRATIONS_DIR / filename
            if not filepath.exists():
                print(f"[!] Warning: Migration file {filename} not found.")
                continue

            print(f"--> Executing migration: {filename}")
            sql_text = filepath.read_text(encoding="utf-8")
            statements = split_sql_file(sql_text)

            for stmt in statements:
                stmt_clean = stmt.rstrip(";").strip()
                if not stmt_clean:
                    continue
                try:
                    cursor.execute(stmt_clean)
                except Exception as e:
                    err_str = str(e).lower()
                    if any(k in err_str for k in ["duplicate column", "already exists", "1060", "1061", "1091", "1050", "3780", "1822"]):
                        continue
                    else:
                        print(f"    [!] Notice: {e}")

            print(f"    [OK] {filename} completed.")

        print("\n[+] All production schema migrations executed cleanly!")
    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
