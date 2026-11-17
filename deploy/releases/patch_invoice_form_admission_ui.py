"""Replace the legacy unstructured admission block in the production template."""

from __future__ import annotations

import re
import sys
from pathlib import Path


INCLUDE = '{% include "billing/_invoice_admission_setup.html" %}'
LEGACY_BLOCK = re.compile(
    r'<div class="modern-card"><label>Invoice booking branch '
    r'\(also the origin for new admissions\)</label><select\s+'
    r'name="invoice_branch_id".*?</p></div>',
    re.DOTALL,
)


def upgrade_template(source: str) -> str:
    if INCLUDE in source:
        return source
    updated, count = LEGACY_BLOCK.subn(INCLUDE, source)
    if count != 1:
        raise RuntimeError(
            f"Expected one legacy admission block, found {count}; refusing partial patch"
        )
    return updated


def main(path: str) -> None:
    template = Path(path)
    source = template.read_text(encoding="utf-8")
    template.write_text(upgrade_template(source), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_invoice_form_admission_ui.py TEMPLATE")
    main(sys.argv[1])
