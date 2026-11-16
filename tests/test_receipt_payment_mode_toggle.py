"""Receipt collection defaults to manual payment and exposes Cashfree on demand."""

from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from extensions import csrf, limiter
from modules.billing import routes
from test_cashfree_payments import sandbox  # noqa: F401 - fixture dependency
from test_student_payment_links import linked  # noqa: F401 - fixture dependency


@pytest.fixture()
def collection(linked):
    conn = linked.connect()
    conn.execute("ALTER TABLE installment_plans ADD COLUMN remarks TEXT")
    conn.commit()
    conn.close()

    app = Flask(__name__)
    app.config.update(linked.app.config)
    app.jinja_loader = ChoiceLoader(
        [
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader("templates"),
        ]
    )
    csrf.init_app(app)
    limiter.init_app(app)
    app.register_blueprint(routes.billing_bp, url_prefix="/billing")
    app.add_url_rule("/login", endpoint="core.login", view_func=lambda: "login")

    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=10, institute_id=1, role="staff")
    return SimpleNamespace(app=app, client=client, ledger=linked)


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = {}
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            assert self.current is None, "Payment forms must not be nested"
            self.current = values["id"]
            self.forms[self.current] = values

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def test_receipt_page_defaults_to_offline_and_keeps_online_separate(collection):
    page = collection.client.get("/billing/receipt/new?invoice_id=101")

    assert page.status_code == 200
    assert 'id="offline-payment-tab"' in page.text
    offline_start = page.text.index('id="offline-payment-tab"')
    assert 'aria-selected="true"' in page.text[offline_start : offline_start + 300]
    assert 'id="offline-payment-panel"' in page.text
    assert 'id="online-payment-tab"' in page.text
    assert 'id="online-payment-panel"' in page.text
    online_start = page.text.index('id="online-payment-panel"')
    assert "hidden" in page.text[online_start : online_start + 220]

    forms = Forms(page.text).forms
    assert "manual-receipt-form" in forms
    assert "cashfree-payment-form" in forms
    assert page.text.index('id="offline-payment-panel"') < page.text.index(
        'id="online-payment-panel"'
    )


def test_online_toggle_is_hidden_when_cashfree_is_unavailable(collection):
    collection.app.config["CASHFREE_SECRET_KEY"] = ""

    page = collection.client.get("/billing/receipt/new?invoice_id=101")

    assert page.status_code == 200
    assert 'id="offline-payment-tab"' in page.text
    assert 'id="online-payment-tab"' not in page.text
    assert "manual-receipt-form" in Forms(page.text).forms
    assert "cashfree-payment-form" not in Forms(page.text).forms


def test_invoice_view_no_longer_embeds_cashfree_checkout():
    template = (
        Path(__file__).parents[1] / "templates" / "billing" / "invoice_view.html"
    ).read_text(encoding="utf-8")

    assert "billing/_cashfree_checkout.html" not in template
    assert "billing.receipt_new" in template


def test_other_tenant_invoice_is_not_visible_from_receipt_page(collection):
    page = collection.client.get("/billing/receipt/new?invoice_id=201")

    assert page.status_code == 302
    assert page.location.endswith("/billing/invoices")
