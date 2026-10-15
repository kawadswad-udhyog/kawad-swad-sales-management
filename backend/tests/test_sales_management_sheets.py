"""Unit tests for the isolated sales Sheets adapter; no live Google calls."""
import os
import unittest
from unittest.mock import patch

from app.services.sales_management_sheets import (
    SalesGoogleSheets,
    SalesSheetsConfigurationError,
)


class SalesSheetsAdapterTests(unittest.TestCase):
    def test_refuses_missing_sales_spreadsheet_id(self):
        with patch.dict(os.environ, {
            "SALES_GOOGLE_SPREADSHEET_ID": "",
            "SALES_GOOGLE_SERVICE_ACCOUNT_FILE": "/not/used.json",
        }, clear=False):
            adapter = SalesGoogleSheets()
            with self.assertRaises(SalesSheetsConfigurationError):
                adapter._connect()

    def test_refuses_missing_service_account_path(self):
        with patch.dict(os.environ, {
            "SALES_GOOGLE_SPREADSHEET_ID": "development-only-id",
            "SALES_GOOGLE_SERVICE_ACCOUNT_FILE": "",
        }, clear=False):
            adapter = SalesGoogleSheets()
            with self.assertRaises(SalesSheetsConfigurationError):
                adapter._connect()


if __name__ == "__main__":
    unittest.main()
