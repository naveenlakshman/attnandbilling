import sqlite3

for db_path in ['instance/database.db', 'instance/lms.db']:
    try:
        c = sqlite3.connect(db_path)
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"\n=== {db_path} ===")
        print("Tables:", tables)
        for t in tables:
            if 'assign' in t.lower() or 'submiss' in t.lower():
                cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
                print(f"  {t}: {cols}")
        c.close()
    except Exception as e:
        print(f"Error with {db_path}: {e}")
