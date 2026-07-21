"""Transactional local-MySQL smoke test for assignment create/edit description sizes."""

from db import get_conn


CREATE_SIZE = 400 * 1024
EDIT_SIZE = 450 * 1024

conn = get_conn()
try:
    column = conn.execute(
        """
        SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'lms_assignments'
          AND COLUMN_NAME = 'description'
        """
    ).fetchone()
    assert column["DATA_TYPE"].lower() == "mediumtext", dict(column)

    topic = conn.execute("SELECT id FROM lms_master_topics ORDER BY id LIMIT 1").fetchone()
    user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if not topic or not user:
        raise RuntimeError("Local MySQL needs at least one master topic and one user")

    cursor = conn.execute(
        """
        INSERT INTO lms_assignments
            (master_topic_id, title, description, uploaded_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, NOW(), NOW())
        """,
        (topic["id"], "__description_size_smoke__", "a" * CREATE_SIZE, user["id"]),
    )
    assignment_id = cursor.lastrowid
    created = conn.execute(
        "SELECT OCTET_LENGTH(description) AS size FROM lms_assignments WHERE id = ?",
        (assignment_id,),
    ).fetchone()
    assert created["size"] == CREATE_SIZE

    conn.execute(
        "UPDATE lms_assignments SET description = ?, updated_at = NOW() WHERE id = ?",
        ("b" * EDIT_SIZE, assignment_id),
    )
    edited = conn.execute(
        "SELECT OCTET_LENGTH(description) AS size FROM lms_assignments WHERE id = ?",
        (assignment_id,),
    ).fetchone()
    assert edited["size"] == EDIT_SIZE
    print(
        f"assignment_mysql_create_edit=OK create={CREATE_SIZE} edit={EDIT_SIZE} "
        f"column={column['DATA_TYPE']} max={column['CHARACTER_MAXIMUM_LENGTH']}"
    )
finally:
    conn.rollback()
    conn.close()
