"""
Migration: Delete all spam leads created by 'RussellSuP' bot.
Run once on production:
    python scripts/delete_spam_leads.py
"""

import sqlite3
import os

DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'instance', 'database.db')
)

def run():
    print(f"Connecting to database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Find the IDs of the spam leads to be deleted
    cur.execute("SELECT id, name, phone, created_at FROM leads WHERE name = 'RussellSuP'")
    spam_leads = cur.fetchall()

    if not spam_leads:
        print("No spam leads found with the name 'RussellSuP'.")
        conn.close()
        return

    print(f"Found {len(spam_leads)} spam leads to delete.")
    lead_ids = [lead[0] for lead in spam_leads]

    # Delete related followups first to maintain integrity
    cur.execute(
        f"DELETE FROM followups WHERE lead_id IN ({','.join(['?'] * len(lead_ids))})",
        lead_ids
    )
    deleted_followups = cur.rowcount
    print(f"Deleted {deleted_followups} associated followups.")

    # Delete the leads
    cur.execute(
        f"DELETE FROM leads WHERE id IN ({','.join(['?'] * len(lead_ids))})",
        lead_ids
    )
    deleted_leads = cur.rowcount
    print(f"Deleted {deleted_leads} spam leads.")

    conn.commit()
    conn.close()
    print("Spam leads deletion completed successfully.")

if __name__ == '__main__':
    run()
