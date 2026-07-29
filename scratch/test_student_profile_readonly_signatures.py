"""Regression checks for student-profile signature ownership and update-form UX."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "students" / "routes.py").read_text(encoding="utf-8")
PROFILE = (ROOT / "templates" / "students" / "profile.html").read_text(encoding="utf-8")
BILLING_ROUTES = (ROOT / "modules" / "billing" / "routes.py").read_text(
    encoding="utf-8"
)
BILLING_PROFILE = (ROOT / "templates" / "billing" / "student_profile.html").read_text(
    encoding="utf-8"
)
AGREEMENT = (
    ROOT / "templates" / "billing" / "student_enrollment_agreement.html"
).read_text(encoding="utf-8")


class StudentProfileReadOnlySignatureTests(unittest.TestCase):
    def test_both_student_signature_endpoints_reject_writes(self):
        message = (
            "Enrollment signatures are read-only. "
            "Contact institute staff for corrections."
        )
        self.assertGreaterEqual(ROUTES.count(message), 2)
        self.assertGreaterEqual(ROUTES.count("}), 403"), 1)
        self.assertIn('}, 403', ROUTES)

    def test_profile_displays_stored_signatures_without_edit_buttons(self):
        visible_profile = PROFILE.split("{% if false %}", 1)[0]
        self.assertIn("student.student_signature_filename", visible_profile)
        self.assertIn("student.parent_signature_filename", visible_profile)
        self.assertIn(
            "storage_url(student.student_signature_filename)", visible_profile
        )
        self.assertIn(
            "storage_url(student.parent_signature_filename)", visible_profile
        )
        self.assertNotIn("/static/images/student_signatures/", visible_profile)
        self.assertIn("official records and are read-only", visible_profile)
        self.assertNotIn("openSigModal(", visible_profile)
        self.assertNotIn("Collect Signature", visible_profile)
        self.assertNotIn("Update Signature", visible_profile)

    def test_profile_update_form_is_collapsed_behind_button(self):
        self.assertIn('data-bs-target="#profileUpdateRequestForm"', PROFILE)
        self.assertIn(
            'class="collapse mt-3" id="profileUpdateRequestForm"',
            PROFILE,
        )
        button_pos = PROFILE.index('data-bs-target="#profileUpdateRequestForm"')
        form_pos = PROFILE.index(
            'action="{{ url_for(\'students.profile_request_update\') }}"'
        )
        self.assertLess(button_pos, form_pos)

    def test_staff_profile_and_agreement_use_tenant_storage_urls(self):
        for template in (BILLING_PROFILE, AGREEMENT):
            self.assertIn(
                "storage_url(student.student_signature_filename)", template
            )
            self.assertIn(
                "storage_url(student.parent_signature_filename)", template
            )
            self.assertNotIn("/static/images/student_signatures/", template)

    def test_staff_signature_write_is_tenant_scoped_and_stores_canonical_path(self):
        signature_route = BILLING_ROUTES.split(
            "def student_save_signature(student_id):", 1
        )[1].split(
            '@billing_bp.route("/student/<int:student_id>/batches-available")', 1
        )[0]
        self.assertIn("get_current_institute_id(default=1)", signature_route)
        self.assertEqual(signature_route.count("WHERE id = ? AND institute_id = ?"), 1)
        self.assertEqual(signature_route.count("WHERE id=? AND institute_id=?"), 2)
        self.assertIn("stored_path = storage_service.upload_file(", signature_route)
        self.assertIn('"filename": stored_path', signature_route)


if __name__ == "__main__":
    unittest.main(verbosity=2)
