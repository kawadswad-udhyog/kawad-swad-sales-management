"""Unit tests for Google Sheets rate limit (429 Quota Exceeded) backoff and resilience."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import unittest
import time
from app.sheets import db

class TestSheetsQuotaHandling(unittest.TestCase):
    def setUp(self):
        db.is_connected = True
        for k in list(db.memory_store):
            db.memory_store[k] = []
        db._records_cache.clear()
        db._worksheets.clear()

    def tearDown(self):
        db.is_connected = False
        db.spreadsheet = None

    def test_stale_cache_served_on_429_quota_exceeded(self):
        """When Google Sheets throws 429 Quota Exceeded, get_records serves stale cache rather than failing."""
        # 1. Prime cache with existing AuthUsers
        db._records_cache["AuthUsers"] = (
            time.monotonic() - 100, # expired cache
            [{"auth_id": "AUTH-1", "user_id": "USR-1", "username": "ankit", "role": "OWNER", "active": "true"}]
        )

        # 2. Mock worksheet that raises a 429 Quota Exceeded APIError
        class QuotaExceededWorksheet:
            def get_all_records(self):
                raise Exception("APIError: [429]: Quota exceeded for quota metric 'Read requests' and limit 'Read requests per minute per user' of service 'sheets.googleapis.com'")

        class QuotaMockSpreadsheet:
            def worksheet(self, tab):
                return QuotaExceededWorksheet()

        db.spreadsheet = QuotaMockSpreadsheet()

        # 3. Reading AuthUsers with fresh=True should catch 429 and return stale cached record
        records = db.get_records("AuthUsers", fresh=True)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["username"], "ankit")

    def test_quota_error_message_is_clear_when_no_cache(self):
        """When no cache exists and 429 persists, a clear quota error is raised instead of generic crash."""
        class QuotaExceededWorksheet:
            def get_all_records(self):
                raise Exception("APIError: [429]: Quota exceeded for quota metric 'Read requests'")

        class QuotaMockSpreadsheet:
            def worksheet(self, tab):
                return QuotaExceededWorksheet()

        db.spreadsheet = QuotaMockSpreadsheet()

        with self.assertRaises(RuntimeError) as ctx:
            db.get_records("UnknownTab", fresh=True)

        self.assertIn("quota", str(ctx.exception).lower())

if __name__ == "__main__":
    unittest.main()
