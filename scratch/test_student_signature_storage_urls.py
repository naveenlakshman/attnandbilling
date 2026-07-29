from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")
STORAGE = (ROOT / "services" / "storage.py").read_text(encoding="utf-8")


def test_legacy_gcs_signatures_use_authenticated_application_route():
    assert 'if gcs_path.startswith("signatures/"):' in STORAGE
    assert 'return f"/student-signatures/{filename}"' in STORAGE


def test_signature_route_is_authenticated_and_streams_storage_bytes():
    assert '@app.get("/student-signatures/<path:filename>")' in APP
    assert 'authenticated_tenant = session.get("institute_id") or session.get(' in APP
    assert 'object_path = f"signatures/{normalized_filename}"' in APP
    assert "data = storage_service.download_file(object_path)" in APP
    assert "as_attachment=False" in APP
