"""Regression checks for authenticated, tenant-scoped student documents."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "students" / "routes.py").read_text(encoding="utf-8")
STUDENT_PROFILE = (
    ROOT / "templates" / "students" / "profile.html"
).read_text(encoding="utf-8")
STAFF_PROFILE = (
    ROOT / "templates" / "billing" / "student_profile.html"
).read_text(encoding="utf-8")


class StudentDocumentAccessTests(unittest.TestCase):
    def test_document_route_uses_database_id_and_tenant_scope(self):
        self.assertIn(
            "@students_bp.route('/profile/document/<int:document_id>')",
            ROUTES,
        )
        self.assertIn("WHERE d.id = ? AND s.institute_id = ?", ROUTES)
        self.assertIn("int(document['student_id']) != int(student_id)", ROUTES)
        self.assertIn("Cross-institute storage access denied.", (
            ROOT / "services" / "storage.py"
        ).read_text(encoding="utf-8"))

    def test_branch_limited_staff_cannot_cross_branches(self):
        self.assertIn("user['role'] not in ('admin', 'staff')", ROUTES)
        self.assertIn("user['can_view_all_branches']", ROUTES)
        self.assertIn("document['branch_id']", ROUTES)

    def test_student_profile_no_longer_uses_public_upload_path(self):
        self.assertNotIn("/uploads/student_documents/", STUDENT_PROFILE)
        self.assertEqual(
            STUDENT_PROFILE.count("students.profile_document"),
            3,
        )

    def test_staff_profile_lists_view_and_download_actions(self):
        self.assertIn("Verification Documents", STAFF_PROFILE)
        self.assertIn("uploaded_docs | length", STAFF_PROFILE)
        self.assertGreaterEqual(
            STAFF_PROFILE.count("students.profile_document"),
            2,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
