import sqlite3

def dump_schema():
    conn = sqlite3.connect('instance/database.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cur.fetchall()
    
    with open('scratch/db_schema.txt', 'w') as f:
        for t in tables:
            f.write(f"=== Table: {t['name']} ===\n")
            f.write(f"{t['sql']}\n\n")
            
    print("Schema dumped to scratch/db_schema.txt successfully.")

if __name__ == '__main__':
    dump_schema()
