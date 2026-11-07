def get_challenge(conn, institute_id, session_id, challenge_id):
    row = conn.execute(
        """
        SELECT * FROM counselling_otp_challenges
        WHERE id = ? AND institute_id = ? AND counselling_session_id = ?
        LIMIT 1
        """,
        (int(challenge_id), int(institute_id), int(session_id)),
    ).fetchone()
    return dict(row) if row else None


def get_latest_challenge(conn, institute_id, session_id):
    row = conn.execute(
        """
        SELECT * FROM counselling_otp_challenges
        WHERE institute_id = ? AND counselling_session_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (int(institute_id), int(session_id)),
    ).fetchone()
    return dict(row) if row else None


def count_recent_challenges(conn, column, value, institute_id, since):
    allowed = {"mobile_normalized", "created_by_user_id", "counselling_session_id"}
    if column not in allowed:
        raise ValueError("Unsupported OTP rate-limit dimension")
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS total FROM counselling_otp_challenges
        WHERE institute_id = ? AND {column} = ? AND created_at >= ?
        """,
        (int(institute_id), value, since),
    ).fetchone()
    return int(row["total"] or 0)


def invalidate_pending(conn, institute_id, session_id, now):
    conn.execute(
        """
        UPDATE counselling_otp_challenges
        SET status = 'INVALIDATED', invalidated_at = ?, updated_at = ?
        WHERE institute_id = ? AND counselling_session_id = ? AND status = 'PENDING'
        """,
        (now, now, int(institute_id), int(session_id)),
    )


def insert_challenge(conn, **values):
    cursor = conn.execute(
        """
        INSERT INTO counselling_otp_challenges (
            institute_id, counselling_session_id, mobile_normalized, otp_hash,
            status, attempt_count, max_attempts, send_sequence, expires_at,
            resend_available_at, delivery_status, created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
        """,
        (
            values["institute_id"], values["session_id"], values["mobile"], values["otp_hash"],
            values["max_attempts"], values["send_sequence"], values["expires_at"],
            values["resend_available_at"], values["actor_user_id"], values["now"], values["now"],
        ),
    )
    return int(cursor.lastrowid)
