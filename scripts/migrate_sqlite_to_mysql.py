import os
import sqlite3
import pymysql
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sqlite_path = os.environ.get("DB_PATH", "instance/database.db")
mysql_host = os.environ.get("MYSQL_HOST", "127.0.0.1")
mysql_port = int(os.environ.get("MYSQL_PORT", 3306))
mysql_user = os.environ.get("MYSQL_USER", "root")
mysql_password = os.environ.get("MYSQL_PASSWORD")
mysql_db = os.environ.get("MYSQL_DB", "test_attn_billing")

if not mysql_password:
    raise RuntimeError("MYSQL_PASSWORD must be set before running this migration")

print("--- Starting SQLite to MySQL Database Migration ---")
print(f"Source SQLite File: {sqlite_path}")
print(f"Target MySQL Host: {mysql_host}:{mysql_port}")
print(f"Target MySQL Database: {mysql_db}")
print("---------------------------------------------------")

# 1. Connect to SQLite and MySQL
if not os.path.exists(sqlite_path):
    raise FileNotFoundError(f"SQLite database file not found at: {sqlite_path}")

sqlite_conn = sqlite3.connect(sqlite_path)
sqlite_cur = sqlite_conn.cursor()

mysql_conn = pymysql.connect(
    host=mysql_host,
    port=mysql_port,
    user=mysql_user,
    password=mysql_password,
    database=mysql_db
)
mysql_cur = mysql_conn.cursor()

# Disable foreign key checks during migration to avoid insertion ordering issues
mysql_cur.execute("SET FOREIGN_KEY_CHECKS = 0;")

# Get list of all tables in SQLite
sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
tables = [row[0] for row in sqlite_cur.fetchall()]

for table in tables:
    print(f"\nMigrating table: {table}...")
    
    # Get table columns info using PRAGMA
    sqlite_cur.execute(f"PRAGMA table_info(`{table}`)")
    columns = sqlite_cur.fetchall()
    
    # Build CREATE TABLE statement for MySQL
    col_defs = []
    pk_cols = []
    for col in columns:
        col_name = col[1]
        col_type = col[2].upper()
        
        # Check if PK
        is_pk = col[5] > 0
        if is_pk:
            pk_cols.append(f"`{col_name}`")
            notnull = "NOT NULL" # Force NOT NULL on primary key columns for MySQL
        else:
            notnull = "NOT NULL" if col[3] else "NULL"
        
        # Default value handling
        dflt_val = ""
        if col[4] is not None:
            raw_dflt = str(col[4]).strip()
            if "CURRENT_TIMESTAMP" in raw_dflt or "datetime('now')" in raw_dflt:
                dflt_val = "DEFAULT CURRENT_TIMESTAMP"
            elif raw_dflt.startswith("'") and raw_dflt.endswith("'"):
                dflt_val = f"DEFAULT {raw_dflt}"
            elif raw_dflt.isdigit():
                dflt_val = f"DEFAULT {raw_dflt}"
        
        # Map SQLite type to MySQL type
        max_len = 0
        if "INT" in col_type:
            mysql_type = "INT"
        elif "TIME" in col_type or "DATE" in col_type:
            mysql_type = "DATETIME"
        elif not col_type or "CHAR" in col_type or "TEXT" in col_type:
            # Query actual max length in SQLite using native LENGTH
            sqlite_cur.execute(f"SELECT MAX(LENGTH(`{col_name}`)) FROM `{table}`")
            max_len = sqlite_cur.fetchone()[0] or 0
            
            if max_len > 65535:
                mysql_type = "LONGTEXT"
                dflt_val = ""
            elif max_len > 255:
                mysql_type = "TEXT"
                dflt_val = "" # TEXT columns in MySQL cannot have default values
            else:
                mysql_type = "VARCHAR(255)"
        elif "REAL" in col_type or "FLOAT" in col_type or "DOUBLE" in col_type or "NUMERIC" in col_type:
            # Map financial columns to DECIMAL
            if any(term in col_name.lower() for term in ["amount", "fee", "price", "subtotal", "discount", "total", "received", "paid", "balance"]):
                mysql_type = "DECIMAL(12, 2)"
            else:
                mysql_type = "DOUBLE"
        elif "BLOB" in col_type:
            mysql_type = "LONGBLOB"
            dflt_val = "" # BLOB columns in MySQL cannot have default values
        else:
            mysql_type = "VARCHAR(255)"
            
        # Ensure default CURRENT_TIMESTAMP is only on DATETIME
        if "CURRENT_TIMESTAMP" in dflt_val and mysql_type not in ["DATETIME", "TIMESTAMP"]:
            mysql_type = "DATETIME"
            
        # If it is a PK, handle auto increment
        if is_pk:
            if len(columns) > 1 and col_type == "INTEGER" and len(pk_cols) == 1:
                col_defs.append(f"`{col_name}` {mysql_type} AUTO_INCREMENT {notnull} {dflt_val}")
                continue
                
        col_defs.append(f"`{col_name}` {mysql_type} {notnull} {dflt_val}")
        
    if pk_cols:
        col_defs.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
        
    create_sql = f"CREATE TABLE IF NOT EXISTS `{table}` (\n  " + ",\n  ".join(col_defs) + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
    
    # Drop table first to ensure clean import
    mysql_cur.execute(f"DROP TABLE IF EXISTS `{table}`")
    mysql_cur.execute(create_sql)
    
    # Copy data
    sqlite_cur.execute(f"SELECT * FROM `{table}`")
    rows = sqlite_cur.fetchall()
    if rows:
        col_names = [col[1] for col in columns]
        cols_str = ", ".join([f"`{name}`" for name in col_names])
        placeholders = ", ".join(["%s"] * len(col_names))
        
        insert_sql = f"INSERT INTO `{table}` ({cols_str}) VALUES ({placeholders})"
        # Execute in chunks/batches to prevent payload size limits
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            mysql_cur.executemany(insert_sql, rows[i:i+batch_size])
        print(f"  Successfully copied {len(rows)} rows.")
    else:
        print("  Table is empty.")

# Re-enable foreign key checks
mysql_cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
mysql_conn.commit()

sqlite_conn.close()
mysql_conn.close()
print("\nDatabase migration completed successfully!")
