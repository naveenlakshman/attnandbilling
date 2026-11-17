"""Regression coverage for invoice-list rows from mixed release generations."""

from pathlib import Path

from jinja2 import Environment, StrictUndefined


TEMPLATE_PATH = (
    Path(__file__).parents[1] / "templates" / "billing" / "invoices.html"
)


def _invoice_row_fragments():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    balance_start = source.index("{% set balance =")
    balance_end = source.index("%}", balance_start) + 2
    cell_start = source.index('<td data-label="Balance"', balance_end)
    cell_end = source.index("</td>", cell_start) + len("</td>")
    return source[balance_start:balance_end] + source[cell_start:cell_end]


def test_legacy_invoice_rows_render_without_accuracy_fields():
    template = Environment(undefined=StrictUndefined).from_string(
        _invoice_row_fragments()
    )

    rendered = template.render(
        inv={"total_amount": 15300.0, "paid_amount": 5000.0}
    )

    assert "10300.00" in rendered
    assert "Credit:" not in rendered


def test_accuracy_invoice_rows_use_ledger_balance_and_credit():
    template = Environment(undefined=StrictUndefined).from_string(
        _invoice_row_fragments()
    )

    rendered = template.render(
        inv={
            "total_amount": 15300.0,
            "paid_amount": 5000.0,
            "outstanding_amount": 3075.0,
            "credit_amount": 250.0,
        }
    )

    assert "3075.00" in rendered
    assert "Credit:" in rendered
    assert "250.00" in rendered
