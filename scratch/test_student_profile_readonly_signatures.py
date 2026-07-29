"""Regression checks for student-profile signature ownership and update-form UX."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "modules" / "students" / "routes.py").read_text(encoding="utf-8")
PROFILE = (ROOT / "templates" / "students" / "profile.html").read_text(encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
