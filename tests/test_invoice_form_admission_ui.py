"""Regression checks for the new-invoice admission setup UI."""

from pathlib import Path
import sys

from jinja2 import Environment

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from deploy.releases.patch_invoice_form_admission_ui import INCLUDE, upgrade_template


FRAGMENT = ROOT / "templates" / "billing" / "_invoice_admission_setup.html"


LEGACY = """
{% if mode == 'create' %}
<div class="modern-card"><label>Invoice booking branch (also the origin for new admissions)</label><select
name="invoice_branch_id" required><option value="">Choose?</option>{% for b in admission_branches %}<option value="{{ b.id }}">{{ b.branch_name }}</option>{% endfor %}</select><label>Admission linkage</label><select
name="admission_mode" required><option value="">Choose?</option><option value="new">New purchase: create one admission for each purchased course</option><option value="existing">Additional invoice: use existing admissions entered on the course rows</option></select><p>A DFA purchase creates one admission with Basics and Tally. For another invoice on the same purchase, choose existing admissions. Admission IDs are available in Admissions and financial history.</p></div>
{% endif %}
"""


def test_runtime_patch_replaces_only_the_legacy_block():
    updated = upgrade_template("before\n" + LEGACY + "\nafter")

    assert updated.startswith("before")
    assert updated.endswith("after")
    assert updated.count(INCLUDE) == 1
    assert "<label>Invoice booking branch" not in updated


def test_admission_fragment_is_structured_responsive_and_preserves_fields():
    source = FRAGMENT.read_text(encoding="utf-8")
    template = Environment().from_string(source)

    assert 'class="admission-setup-grid"' in source
    assert "grid-template-columns: minmax(0, 720px)" in source
    assert "@media (max-width: 768px)" in source
    assert 'name="invoice_branch_id"' in source
    assert 'for="invoice_branch_id"' in source
    assert "No active branch is configured" in source

    rendered = template.render(admission_branches=[{"id": 2, "branch_name": "Hoskote"}])
    assert '<option value="2">Hoskote</option>' in rendered
    assert 'name="invoice_branch_id"' in rendered

    empty = template.render(admission_branches=[])
    assert 'name="invoice_branch_id"' not in empty
    assert "No active branch is configured" in empty


if __name__ == "__main__":
    test_runtime_patch_replaces_only_the_legacy_block()
    test_admission_fragment_is_structured_responsive_and_preserves_fields()
