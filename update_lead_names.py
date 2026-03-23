#!/usr/bin/env python3
"""
Update lead names in the database from provided list
"""
from db import get_conn
from datetime import datetime

# List of lead names in order
lead_names = [
    "Srinivas K P",
    "Sharath R",
    "Hema Chandra",
    "Vignesh M",
    "Sunitha K",
    "Likitha S",
    "Vasanth",
    "Varsha",
    "Sushma S G",
    "Sunil Kumar",
    "Sirisha L",
    "Chaithali",
    "N Tejashree",
    "Siri",
    "Ullas R",
    "Vittal V M",
    "Pallavi U",
    "Monika H A",
    "Parinav S Vikyatth",
    "Yashaswini",
    "Jeevitha D",
    "Lakshmi",
    "Chandra Kumar S",
    "Karthik N M",
    "Nethravathi C",
    "Harshith Mishra",
    "Sujan H C",
    "Chaithanya D"
]

conn = get_conn()
cur = conn.cursor()

try:
    updated_count = 0
    for idx, name in enumerate(lead_names, start=1):
        cur.execute("""
            UPDATE leads 
            SET name = ?, updated_at = ?
            WHERE id = ? AND is_deleted = 0
        """, (name, datetime.now().isoformat(), idx))
        
        if cur.rowcount > 0:
            updated_count += 1
            print(f"✓ Lead {idx}: {name}")
        else:
            print(f"✗ Lead {idx}: {name} - NOT FOUND")
    
    conn.commit()
    print(f"\n✅ Successfully updated {updated_count} lead names!")
    
    # Verify the update
    print("\nVerification:")
    cur.execute("SELECT id, name FROM leads WHERE id IN (1, 28) ORDER BY id")
    for row in cur.fetchall():
        print(f"  Lead {row['id']}: {row['name']}")
    
except Exception as e:
    print(f"❌ Error: {str(e)}")
    conn.rollback()
finally:
    conn.close()
