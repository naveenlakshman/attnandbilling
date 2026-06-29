def generate_certificate_number(conn, template_code, year, settings):
    """
    Generates a unique, concurrent-safe certificate number using the certificate_sequences table.
    Enforces atomic incrementing inside the database transaction.
    """
    cur = conn.cursor()
    
    # Perform transaction-safe atomic increment
    cur.execute("""
        INSERT INTO certificate_sequences (template_code, year, current_sequence, updated_at)
        VALUES (?, ?, 1, datetime('now'))
        ON CONFLICT(template_code, year) DO UPDATE SET
            current_sequence = current_sequence + 1,
            updated_at = datetime('now')
    """, (template_code, year))
    
    # Retrieve the incremented sequence value
    row = cur.execute(
        "SELECT current_sequence FROM certificate_sequences WHERE template_code = ? AND year = ?",
        (template_code, year)
    ).fetchone()
    
    seq = row["current_sequence"]
    
    # Read formatting options from configuration settings
    seq_len = settings.get("sequence_length", 6)
    padded_seq = f"{seq:0{seq_len}d}"
    prefix = settings.get("prefix", "GIT")
    
    return f"{prefix}-{template_code}-{year}-{padded_seq}"
