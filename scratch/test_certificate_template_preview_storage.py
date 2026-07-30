"""Regression checks for tenant certificate-template assets and ownership."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "certificates" / "routes.py").read_text(
    encoding="utf-8"
)
EDITOR = (ROOT / "templates" / "certificates" / "admin_templates.html").read_text(
    encoding="utf-8"
)
VIEW = (ROOT / "templates" / "certificates" / "view.html").read_text(
    encoding="utf-8"
)
MY_CERTIFICATES = (
    ROOT / "templates" / "certificates" / "my_certificates.html"
).read_text(encoding="utf-8")


class CertificateTemplatePreviewStorageTests(unittest.TestCase):
    def test_uploaded_background_uses_tenant_storage_url(self):
        self.assertIn(
            "storage_url(sel_template.background_filename)",
            EDITOR,
        )
        self.assertNotIn(
            "images/certificate_templates/' ~ sel_template.background_filename",
            EDITOR,
        )

    def test_certificate_views_do_not_prepend_legacy_static_path(self):
        self.assertIn(
            "storage_url(template.preview_filename or template.background_filename)",
            VIEW,
        )
        self.assertIn("storage_url(template.background_filename)", VIEW)
        self.assertIn("storage_url(cert.background_filename)", MY_CERTIFICATES)
        self.assertNotIn(
            "static/images/certificate_templates/' ~",
            VIEW + MY_CERTIFICATES,
        )

    def test_template_admin_reads_and_writes_are_institute_scoped(self):
        route = ROUTES.split("def admin_templates():", 1)[1].split(
            "# Admin - Audit History Viewer", 1
        )[0]
        self.assertIn("get_current_institute_id(default=1)", route)
        self.assertGreaterEqual(route.count("AND institute_id = ?"), 4)
        self.assertIn("WHERE institute_id = ?", route)
        self.assertIn(
            "institute_id, template_name, template_code, background_filename",
            route,
        )

    def test_uploads_persist_canonical_tenant_path(self):
        route = ROUTES.split("def admin_templates():", 1)[1].split(
            "# Admin - Audit History Viewer", 1
        )[0]
        self.assertIn("bg_filename = storage_service.upload_file(", route)
        self.assertIn("bg_filename = storage_service.replace_file(", route)
        self.assertIn("sig_filename = storage_service.replace_file(", route)
        self.assertIn("seal_filename = storage_service.replace_file(", route)


if __name__ == "__main__":
    unittest.main(verbosity=2)
