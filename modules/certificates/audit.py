import datetime

def log_certificate_action(conn, certificate_id, action, performed_by=None, previous_status=None, new_status=None, reason=None, ip_address=None, user_agent=None):
    """
    Creates an audit log entry in the certificate_audit_logs table.
    Designed to run as part of an active database transaction.
    """
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    cur.execute("""
        INSERT INTO certificate_audit_logs (
            certificate_id,
            action,
            previous_status,
            new_status,
            reason,
            performed_by,
            ip_address,
            user_agent,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        certificate_id,
        action,
        previous_status,
        new_status,
        reason,
        performed_by,
        ip_address,
        user_agent,
        now
    ))
