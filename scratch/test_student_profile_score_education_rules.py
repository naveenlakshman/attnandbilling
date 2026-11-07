from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "modules" / "students" / "routes.py"
tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
score_function = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "calculate_profile_score"
)
namespace = {}
exec(compile(ast.Module(body=[score_function], type_ignores=[]), str(ROUTES), "exec"), namespace)
calculate_profile_score = namespace["calculate_profile_score"]


BASE_PROFILE = {
    "full_name": "Student",
    "phone": "9999999999",
    "email": "student@example.com",
    "address": "Address",
    "gender": "Female",
    "education_level": "School",
    "qualification": "8th Standard",
    "employment_status": "Active",
    "date_of_birth": "2013-01-01",
    "parent_name": "Parent",
    "parent_contact": "8888888888",
    "father_name": "Father",
    "mother_name": "Mother",
    "student_signature_filename": "student.png",
    "parent_signature_filename": "parent.png",
    "tenth_institution": "",
    "tenth_percentage": "",
    "puc_institution": "",
    "puc_percentage": "",
}

ALL_DOCUMENTS = [
    {"category": "qualification"},
    {"category": "identity"},
    {"category": "address"},
]


class StudentProfileScoreEducationRuleTests(unittest.TestCase):
    def test_eighth_standard_does_not_require_tenth_or_puc_history(self):
        self.assertEqual(calculate_profile_score(BASE_PROFILE, ALL_DOCUMENTS), 100)

    def test_completed_tenth_requires_tenth_history_but_not_puc_history(self):
        student = {
            **BASE_PROFILE,
            "qualification": "10th Standard / SSLC Completed",
        }
        self.assertEqual(calculate_profile_score(student, ALL_DOCUMENTS), 90)

        student["tenth_institution"] = "School"
        student["tenth_percentage"] = "85"
        self.assertEqual(calculate_profile_score(student, ALL_DOCUMENTS), 100)

    def test_second_puc_requires_tenth_and_puc_history(self):
        student = {
            **BASE_PROFILE,
            "education_level": "Pre-University",
            "qualification": "2nd PUC - Commerce",
            "tenth_institution": "School",
            "tenth_percentage": "85",
        }
        self.assertEqual(calculate_profile_score(student, ALL_DOCUMENTS), 90)

        student["puc_institution"] = "College"
        student["puc_percentage"] = "80"
        self.assertEqual(calculate_profile_score(student, ALL_DOCUMENTS), 100)


if __name__ == "__main__":
    unittest.main()
