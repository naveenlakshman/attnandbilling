import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class BillingPdfDownloadRegressionTests(unittest.TestCase):
    def test_pdf_templates_do_not_close_the_download_tab(self):
        for relative_path in (
            "templates/billing/invoice_print.html",
            "templates/billing/receipt_print.html",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("window.close()", source)
            self.assertIn(".save().then(function()", source)
            self.assertIn(".catch(function(error)", source)
            self.assertIn("PDF downloaded. You can close this tab.", source)

    def test_logged_in_receipt_routes_require_current_institute(self):
        source = (ROOT / "modules/billing/routes.py").read_text(encoding="utf-8")
        receipt_routes = source[
            source.index("def receipt_view(receipt_id):"):
            source.index("def _receipt_serializer():", source.index("def receipt_view(receipt_id):"))
        ]
        self.assertEqual(
            receipt_routes.count("AND students.institute_id = ?"),
            2,
        )
        self.assertGreaterEqual(
            receipt_routes.count("get_current_institute_id(default=1)"),
            2,
        )

    def test_invoice_pdf_uses_tenant_branch_address_as_fallback(self):
        routes = (ROOT / "modules/billing/routes.py").read_text(encoding="utf-8")
        template = (ROOT / "templates/billing/invoice_print.html").read_text(
            encoding="utf-8"
        )
        self.assertGreaterEqual(
            routes.count("branches.address AS branch_address"),
            3,
        )
        self.assertIn(
            "company.address or invoice.branch_address",
            template,
        )
        self.assertIn("<strong>Branch Address:</strong>", template)


if __name__ == "__main__":
    unittest.main()
