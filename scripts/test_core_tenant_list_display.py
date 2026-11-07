from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _template(name):
    return (ROOT / "templates" / "core" / name).read_text(encoding="utf-8")


def test_users_hide_internal_ids_and_format_created_at_in_ist():
    template = _template("users.html")

    assert "<th>ID</th>" not in template
    assert "<td>{{ user.id }}</td>" not in template
    assert "user.created_at | format_ist_datetime('%d-%b-%Y %I:%M %p')" in template


def test_branches_hide_internal_ids_and_format_created_at_in_ist():
    template = _template("branches.html")

    assert "<th>ID</th>" not in template
    assert "<td>{{ branch.id }}</td>" not in template
    assert "branch.created_at | format_ist_datetime('%d-%b-%Y %I:%M %p')" in template
