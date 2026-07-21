"""Phase 1 route/template regression checks for the assignment overview."""

from app import app
from db import get_conn


conn = get_conn()
admin = conn.execute(
    """SELECT id, branch_id FROM users
       WHERE role = 'admin' AND is_active = 1 ORDER BY id LIMIT 1"""
).fetchone()
conn.close()
if not admin:
    raise RuntimeError("Local MySQL needs one active administrator")

app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
client = app.test_client()
with client.session_transaction() as session:
    session["user_id"] = admin["id"]
    session["role"] = "admin"
    session["branch_id"] = admin.get("branch_id")

response = client.get("/lms_admin/master/assignments")
assert response.status_code == 200
html = response.get_data(as_text=True)

assert '<col class="assignment-column">' in html
assert '<col class="context-column">' in html
assert '<col class="progress-column">' in html
assert '<col class="actions-column">' in html
assert "Course context" in html
assert "Review progress" in html
assert "assignment-review-progress" in html
assert "assignment-actions-cell" in html
assert "position: sticky" in html
assert "@media (max-width: 991.98px)" in html
assert "grid-template-columns: 1fr 1fr" in html
assert "<th>Chapter / Topic</th>" not in html
assert '<th class="text-center">Submissions</th>' not in html

conn = get_conn()
assignment = conn.execute("SELECT id FROM lms_assignments ORDER BY id LIMIT 1").fetchone()
conn.close()
if assignment:
    edit_response = client.get(f"/lms_admin/master/assignments/{assignment['id']}/edit")
    assert edit_response.status_code == 200
    assert b"Edit Assignment" in edit_response.data
    assert b"Back to Assignments" not in edit_response.data

print(f"phase1_assignment_layout=OK response_bytes={len(response.data)}")
print("phase1_edit_back_link_removed=OK")
