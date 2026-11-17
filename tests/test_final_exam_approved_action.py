from pathlib import Path

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "exams" / "student_final_exam_apply.html"


def test_approved_exam_action_precedes_eligibility_warnings():
    source = TEMPLATE.read_text(encoding="utf-8")
    Environment().parse(source)

    approved = source.index("application.status == 'APPROVED'")
    blocked = source.index("not checks.application_ready")
    assert approved < blocked
    assert "exam_unlocked" in source
    assert "Take Final Exam" in source
    assert "Opens on {{ application.requested_exam_date }}" in source
    assert "exam_window_expired" in source


if __name__ == "__main__":
    test_approved_exam_action_precedes_eligibility_warnings()
