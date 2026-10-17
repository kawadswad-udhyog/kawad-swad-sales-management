"""Tests for Google Sheets connectivity enforcement, data loss prevention, and persistent storage protection."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import unittest
from app.sheets import db, REQUIRED_TABS

class TestStorageConnectivityProtection(unittest.TestCase):
    def setUp(self):
        self.orig_connected = db.is_connected
        self.orig_spreadsheet = db.spreadsheet
        self.orig_fallback = db.allow_in_memory_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def tearDown(self):
        db.is_connected = self.orig_connected
        db.spreadsheet = self.orig_spreadsheet
        db.allow_in_memory_fallback = self.orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def test_writes_strictly_blocked_when_disconnected_in_production(self):
        """When in production (allow_in_memory_fallback=False) and disconnected, writes must be rejected to prevent data loss."""
        db.is_connected = False
        db.spreadsheet = None
        db.allow_in_memory_fallback = False
        db.last_connection_error = "Mock disconnected state"

        # 1. append_record should return False and not store in memory
        res = db.append_record("Sales", {"sale_id": "SALE-999999", "bill_total": 500}, raise_on_error=False)
        self.assertFalse(res, "append_record must return False when disconnected in production")
        self.assertNotIn("SALE-999999", [r.get("sale_id") for r in db.memory_store.get("Sales", [])])

        # 2. append_record with raise_on_error=True must raise RuntimeError
        with self.assertRaises(RuntimeError) as ctx:
            db.append_record("Sales", {"sale_id": "SALE-999998"}, raise_on_error=True)
        self.assertIn("persistent storage is unavailable", str(ctx.exception).lower())

        # 3. update_record should return False and not update
        res_update = db.update_record("Sales", "sale_id", "SALE-999999", {"bill_status": "PAID"})
        self.assertFalse(res_update)

        # 4. get_records should raise RuntimeError rather than returning empty memory store
        with self.assertRaises(RuntimeError) as ctx:
            db.get_records("Sales", fresh=True)
        self.assertIn("persistent storage is unavailable", str(ctx.exception).lower())

    def test_verify_tabs_accessibility_when_connected(self):
        """verify_tabs_accessibility correctly queries and verifies each required tab."""
        class MockWorksheet:
            def __init__(self, title):
                self.title = title
            def row_values(self, row):
                return ["col1", "col2", "col3"]

        class MockSpreadsheet:
            def worksheet(self, tab):
                return MockWorksheet(tab)

        db.is_connected = True
        db.spreadsheet = MockSpreadsheet()
        db.allow_in_memory_fallback = True

        health = db.verify_tabs_accessibility()
        self.assertTrue(health["connected"])
        self.assertTrue(health["all_tabs_accessible"])
        self.assertIn("Sales", health["tabs"])
        self.assertIn("Recipes", health["tabs"])
        self.assertEqual(health["tabs"]["Sales"]["status"], "ok")

    def test_verify_tabs_accessibility_reports_failures(self):
        """verify_tabs_accessibility catches missing/inaccessible tabs and flags all_tabs_accessible as False."""
        class BrokenSpreadsheet:
            def worksheet(self, tab):
                if tab == "Recipes":
                    raise Exception("Permission denied for Recipes tab")
                class MockWs:
                    def row_values(self, row): return ["c1"]
                return MockWs()

        db.is_connected = True
        db.spreadsheet = BrokenSpreadsheet()
        health = db.verify_tabs_accessibility()
        self.assertFalse(health["all_tabs_accessible"])
        self.assertEqual(health["tabs"]["Recipes"]["status"], "error")

    def test_reconnect_clears_caches_and_attempts_init(self):
        """reconnect method flushes cached worksheets and records."""
        db._worksheets["Sales"] = "old_worksheet"
        db._records_cache["Sales"] = (12345.0, [{"id": 1}])
        
        # Trigger reconnect
        db.reconnect()
        self.assertEqual(len(db._worksheets), 0)
        self.assertEqual(len(db._records_cache), 0)

if __name__ == "__main__":
    unittest.main()
