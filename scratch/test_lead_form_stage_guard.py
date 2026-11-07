from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.leads import services


def main():
    assert services.EDITABLE_STAGES == [
        "New Lead",
        "Contacted",
        "Interested",
        "Counseling Done",
        "Follow-up",
    ]
    assert services.TERMINAL_STAGES == {"Converted", "Lost"}
    assert not (set(services.EDITABLE_STAGES) & services.TERMINAL_STAGES)

    template = Path("templates/leads/lead_form.html").read_text(encoding="utf-8")
    assert "{% for s in editable_stages %}" in template
    assert 'value="{{ st }}" disabled' in template

    routes = Path("modules/leads/routes.py").read_text(encoding="utf-8")
    assert routes.count("stage not in lead_services.EDITABLE_STAGES") == 2
    assert routes.count("Use the dedicated Convert or Mark Lost action.") == 2

    print("Lead creation/edit terminal-stage guard regression checks passed.")


if __name__ == "__main__":
    main()
