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
    Environment().parse(source)

    assert 'class="admission-setup-grid"' in source
    assert "grid-template-columns: repeat(2" in source
    assert "@media (max-width: 768px)" in source
    assert 'name="invoice_branch_id"' in source
    assert 'name="admission_mode"' in source
    assert 'value="new"' in source
    assert 'value="existing"' in source
    assert 'for="invoice_branch_id"' in source
    assert 'for="admission_mode"' in source


if __name__ == "__main__":
    test_runtime_patch_replaces_only_the_legacy_block()
    test_admission_fragment_is_structured_responsive_and_preserves_fields()
