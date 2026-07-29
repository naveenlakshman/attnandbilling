"""Static regressions for tenant-aware student photo storage and rendering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "billing" / "routes.py").read_text(encoding="utf-8")
PROFILE = (ROOT / "templates" / "billing" / "student_profile.html").read_text(
    encoding="utf-8"
)
FORM = (ROOT / "templates" / "billing" / "student_form.html").read_text(
    encoding="utf-8"
)
STUDENTS = (ROOT / "templates" / "billing" / "students.html").read_text(
    encoding="utf-8"
)


def test_photo_writer_delegates_tenant_namespace_to_storage_provider():
    assert 'dest_path = f"student_photos/{student_code}.jpg"' in ROUTES
    assert 'dest_path = f"tenants/{current_inst}/student_photos/' not in ROUTES
    assert "return stored_path" in ROUTES


def test_quick_photo_update_is_tenant_scoped_and_returns_renderable_url():
    route_start = ROUTES.index("def student_upload_photo(student_id):")
    route_end = ROUTES.index(
        '@billing_bp.route("/student/<int:student_id>/save-signature"',
        route_start,
    )
    route = ROUTES[route_start:route_end]
    assert "WHERE id = ? AND institute_id = ?" in route
    assert '"photo_url": photo_url' in route


def test_profile_and_registration_views_do_not_duplicate_photo_prefix():
    for template in (PROFILE, FORM, STUDENTS):
        assert "storage_url(" in template
        assert 'src="/static/images/student_photos/{{' not in template
    assert "data.photo_url +" in PROFILE
    assert "'/static/images/student_photos/' + data.photo_filename" not in PROFILE


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} student photo storage tests passed.")
