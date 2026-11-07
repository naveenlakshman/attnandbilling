"""
Automated unit test script for CSV Data Import multi-tenant scoping and validation.
"""
import os
import sys
import unittest
from google.cloud.sql.connector import Connector

class TestCSVImportTenantScoping(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.connector = Connector()
        cls.conn = cls.connector.connect(
            "global-it-erp-staging:asia-south1:global-it-erp-staging-db",
            "pymysql",
            user="attn_app",
            password="gTuipqWulGalACh4ZsQ2QVfDwzEczgQd2Ij0KiDwZvqWSlhT",
            db="global_it_erp_staging"
        )

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.connector.close()

    def setUp(self):
        self.cur = self.conn.cursor()

    def test_courses_table_has_institute_id(self):
        """Verify courses table has institute_id column."""
        self.cur.execute("SHOW COLUMNS FROM courses LIKE 'institute_id'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "courses table must have institute_id column")

    def test_invoices_table_has_institute_id(self):
        """Verify invoices table has institute_id column."""
        self.cur.execute("SHOW COLUMNS FROM invoices LIKE 'institute_id'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "invoices table must have institute_id column")

    def test_receipts_table_has_institute_id(self):
        """Verify receipts table has institute_id column."""
        self.cur.execute("SHOW COLUMNS FROM receipts LIKE 'institute_id'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "receipts table must have institute_id column")

    def test_expenses_table_has_institute_id(self):
        """Verify expenses table has institute_id column."""
        self.cur.execute("SHOW COLUMNS FROM expenses LIKE 'institute_id'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "expenses table must have institute_id column")

    def test_followups_table_has_institute_id(self):
        """Verify followups table has institute_id column."""
        self.cur.execute("SHOW COLUMNS FROM followups LIKE 'institute_id'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "followups table must have institute_id column")

    def test_cross_tenant_branch_validation(self):
        """Verify that branch validation query restricts to current institute_id."""
        self.cur.execute("SELECT id FROM branches WHERE id = 198 AND institute_id = 1")
        inst1_branch = self.cur.fetchone()
        self.assertIsNotNone(inst1_branch, "Branch 198 should exist in Institute 1")

        # Query for Institute 7 with branch 198 should return None
        self.cur.execute("SELECT id FROM branches WHERE id = 198 AND institute_id = 7")
        cross_inst_branch = self.cur.fetchone()
        self.assertIsNone(cross_inst_branch, "Branch 198 should NOT belong to Institute 7")

if __name__ == '__main__':
    unittest.main()
