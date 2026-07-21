"""Local-only Flask/MySQL smoke test for assignment create and edit routes."""

import uuid

from app import app
from db import get_conn


token = uuid.uuid4().hex
valid_title = f"__assignment_route_smoke_{token}__"
oversize_title = f"__assignment_oversize_smoke_{token}__"

conn = get_conn()
topic = conn.execute("SELECT id FROM lms_master_topics ORDER BY id LIMIT 1").fetchone()
user = conn.execute("SELECT id, role, branch_id FROM users ORDER BY id LIMIT 1").fetchone()
conn.close()
if not topic or not user:
    raise RuntimeError("Local MySQL needs at least one master topic and one user")

app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
client = app.test_client()
with client.session_transaction() as session:
    session["user_id"] = user["id"]
    session["role"] = user.get("role") or "admin"
    session["branch_id"] = user.get("branch_id")

create_url = f"/lms_admin/master/topic/{topic['id']}/assignments"

try:
    oversized = client.post(
        create_url,
        data={"title": oversize_title, "description": "x" * (500 * 1024 + 1)},
    )
    assert oversized.status_code == 302
    conn = get_conn()
    assert conn.execute(
        "SELECT id FROM lms_assignments WHERE title = ?", (oversize_title,)
    ).fetchone() is None
    conn.close()

    created = client.post(
        create_url,
        data={"title": valid_title, "description": "a" * (400 * 1024)},
    )
    assert created.status_code == 302
    conn = get_conn()
    assignment = conn.execute(
        "SELECT id, OCTET_LENGTH(description) AS size FROM lms_assignments WHERE title = ?",
        (valid_title,),
    ).fetchone()
    assert assignment and assignment["size"] == 400 * 1024
    conn.close()

    edit_url = f"/lms_admin/master/assignments/{assignment['id']}/edit"
    edited = client.post(
        edit_url,
        data={"title": valid_title, "description": "b" * (450 * 1024)},
    )
    assert edited.status_code == 302
    conn = get_conn()
    updated = conn.execute(
        "SELECT OCTET_LENGTH(description) AS size FROM lms_assignments WHERE id = ?",
        (assignment["id"],),
    ).fetchone()
    assert updated["size"] == 450 * 1024
    conn.close()

    rejected_edit = client.post(
        edit_url,
        data={"title": valid_title, "description": "c" * (500 * 1024 + 1)},
    )
    assert rejected_edit.status_code == 302
    conn = get_conn()
    unchanged = conn.execute(
        "SELECT OCTET_LENGTH(description) AS size FROM lms_assignments WHERE id = ?",
        (assignment["id"],),
    ).fetchone()
    assert unchanged["size"] == 450 * 1024
    conn.close()

    edit_page = client.get(edit_url)
    assert edit_page.status_code == 200
    assert b"TextEncoder" in edit_page.data
    assert b"Maximum allowed size is 500 KB" in edit_page.data
    print("assignment_create_edit_routes=OK")
finally:
    conn = get_conn()
    conn.execute(
        "DELETE FROM lms_assignments WHERE title IN (?, ?)",
        (valid_title, oversize_title),
    )
    conn.commit()
    conn.close()
