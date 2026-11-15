"""Tests for Google Sheets diagnostic batch optimization, quota/network error handling, and health endpoint security."""
import os

os.environ["SALES_TESTING"] = "1"
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # noqa: F401 - initializes stub modules when running with system python3
import unittest
from unittest.mock import patch
from fastapi import HTTPException

from app.sheets import db, REQUIRED_TABS
from app.main import (
    health_check,
    health_details,
    health_reconnect,
    health_verify_tabs,
    health_schema_compatibility,
)


class MockQuotaAPIError(Exception):
    def __init__(self, message="APIError: [429]: Quota exceeded for quota metric 'Read requests'"):
        super().__init__(message)
        self.code = 429
        self.error = {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": message}


class MockBatchWorksheet:
    def __init__(self, title, headers):
        self.title = title
        self._headers = list(headers)

    def row_values(self, row):
        raise AssertionError(f"Per-tab row_values() should NOT be called when values_batch_get() is available ({self.title})")


class MockBatchSpreadsheet:
    def __init__(
        self,
        headers_by_tab=None,
        fail_worksheets_exc=None,
        fail_batch_on_call=None,
        fail_batch_exc=None,
        missing_tabs=None,
    ):
        self.headers_by_tab = headers_by_tab if headers_by_tab is not None else {t: list(cols) for t, cols in REQUIRED_TABS.items()}
        self.missing_tabs = set(missing_tabs or [])
        self.fail_worksheets_exc = fail_worksheets_exc
        self.fail_batch_on_call = fail_batch_on_call
        self.fail_batch_exc = fail_batch_exc
        self.worksheets_calls = 0
        self.batch_get_calls = 0
        self.batch_ranges_history = []

    def worksheets(self):
        self.worksheets_calls += 1
        if self.fail_worksheets_exc is not None:
            raise self.fail_worksheets_exc
        return [
            MockBatchWorksheet(tab, self.headers_by_tab.get(tab, []))
            for tab in REQUIRED_TABS
            if tab not in self.missing_tabs
        ]

    def values_batch_get(self, ranges):
        self.batch_get_calls += 1
        self.batch_ranges_history.append(list(ranges))
        if self.fail_batch_exc is not None and (
            self.fail_batch_on_call is None or self.batch_get_calls >= self.fail_batch_on_call
        ):
            raise self.fail_batch_exc

        value_ranges = []
        for r in ranges:
            # Parse "'TabName'!1:1" back to tab title
            sheet_part = r.split("!")[0]
            if sheet_part.startswith("'") and sheet_part.endswith("'"):
                tab = sheet_part[1:-1].replace("''", "'")
            else:
                tab = sheet_part
            hdrs = self.headers_by_tab.get(tab, [])
            if hdrs:
                value_ranges.append({"range": r, "values": [hdrs]})
            else:
                # Google Sheets omits "values" when row 1 is genuinely empty
                value_ranges.append({"range": r})
        return {"valueRanges": value_ranges}


class TestDiagnosticQuotaCachingAndSecurity(unittest.TestCase):
    def setUp(self):
        self.orig_connected = db.is_connected
        self.orig_spreadsheet = db.spreadsheet
        self.orig_fallback = db.allow_in_memory_fallback
        self.orig_last_err = db.last_connection_error
        db._records_cache.clear()
        db._worksheets.clear()
        db.invalidate_diagnostic_cache()
        self.owner = {"user_id": "USR-OWNER", "role": "OWNER"}
        self.pa = {"user_id": "USR-PA", "role": "PA"}
        self.salesman = {"user_id": "USR-SALES", "role": "SALESMAN"}
        self.accountant = {"user_id": "USR-ACC", "role": "ACCOUNTANT"}

    def tearDown(self):
        db.is_connected = self.orig_connected
        db.spreadsheet = self.orig_spreadsheet
        db.allow_in_memory_fallback = self.orig_fallback
        db.last_connection_error = self.orig_last_err
        db._records_cache.clear()
        db._worksheets.clear()
        db.invalidate_diagnostic_cache()

    def test_batch_read_optimization_and_safe_caching(self):
        """Diagnostics use chunked values_batch_get instead of 66 row_values(1) calls and share TTL cache."""
        headers_by_tab = {t: list(cols) for t, cols in REQUIRED_TABS.items()}
        headers_by_tab["Products"] = list(REQUIRED_TABS["Products"]) + ["custom_owner_note"]
        headers_by_tab["PackagingBatches"] = [c for c in REQUIRED_TABS["PackagingBatches"] if c != "cost_status"]

        ss = MockBatchSpreadsheet(headers_by_tab=headers_by_tab)
        db.is_connected = True
        db.spreadsheet = ss

        tabs_res = db.verify_tabs_accessibility()
        self.assertTrue(tabs_res["all_tabs_accessible"])
        self.assertEqual(tabs_res["status"], "OK")
        self.assertTrue(tabs_res["verification_completed"])
        self.assertFalse(tabs_res["cached"])
        self.assertEqual(ss.worksheets_calls, 1)
        # 66 tabs in chunks of 35 => only 2 batchGet calls (3 calls total instead of 67)
        self.assertLessEqual(ss.batch_get_calls, 3)

        # Immediate follow-up schema-compatibility check hits cache => 0 new API calls
        schema_res = db.inspect_schema_compatibility()
        self.assertEqual(schema_res["status"], "COMPATIBLE_WITH_OPTIONAL_GAPS")
        self.assertTrue(schema_res["cached"])
        self.assertTrue(schema_res["verification_completed"])
        self.assertFalse(schema_res["mutated"])
        self.assertEqual(schema_res["checked_tabs"], len(REQUIRED_TABS))
        self.assertIn("custom_owner_note", schema_res["extra_columns_preserved"]["Products"])
        self.assertEqual(schema_res["missing_optional_columns"]["PackagingBatches"], ["cost_status"])
        self.assertEqual(ss.worksheets_calls, 1)
        self.assertLessEqual(ss.batch_get_calls, 3)

        # force_refresh=True bypasses cache and re-reads cleanly
        schema_refreshed = db.inspect_schema_compatibility(force_refresh=True)
        self.assertFalse(schema_refreshed["cached"])
        self.assertEqual(ss.worksheets_calls, 2)

    def test_quota_429_on_worksheets_never_reports_incompatible(self):
        """HTTP 429 on worksheets() must return TEMPORARILY_UNAVAILABLE, never INCOMPATIBLE."""
        ss = MockBatchSpreadsheet(fail_worksheets_exc=MockQuotaAPIError())
        db.is_connected = True
        db.spreadsheet = ss

        schema_res = db.inspect_schema_compatibility()
        self.assertEqual(schema_res["status"], "TEMPORARILY_UNAVAILABLE")
        self.assertEqual(schema_res["error_type"], "QUOTA_EXCEEDED")
        self.assertTrue(schema_res["quota_exceeded"])
        self.assertFalse(schema_res["verification_completed"])
        self.assertFalse(schema_res["mutated"])
        self.assertEqual(schema_res["missing_tabs"], [])
        self.assertEqual(schema_res["missing_required_columns"], {})
        self.assertNotEqual(schema_res["status"], "INCOMPATIBLE")

        tabs_res = db.verify_tabs_accessibility()
        self.assertEqual(tabs_res["status"], "TEMPORARILY_UNAVAILABLE")
        self.assertEqual(tabs_res["error_type"], "QUOTA_EXCEEDED")
        self.assertTrue(tabs_res["quota_exceeded"])
        self.assertFalse(tabs_res["all_tabs_accessible"])
        self.assertFalse(tabs_res["verification_completed"])

    def test_quota_429_mid_batch_or_per_tab_never_treats_unreadable_as_empty(self):
        """HTTP 429 mid-scan must not treat unreadable sheets as empty or produce INCOMPATIBLE."""
        # 1. Batch chunk 2 raises HTTP 429 after chunk 1 succeeded
        ss = MockBatchSpreadsheet(fail_batch_on_call=2, fail_batch_exc=MockQuotaAPIError())
        db.is_connected = True
        db.spreadsheet = ss

        schema_res = db.inspect_schema_compatibility()
        self.assertEqual(schema_res["status"], "TEMPORARILY_UNAVAILABLE")
        self.assertEqual(schema_res["error_type"], "QUOTA_EXHAUSTED" if False else "QUOTA_EXCEEDED")
        self.assertTrue(schema_res["quota_exceeded"])
        self.assertFalse(schema_res["verification_completed"])
        self.assertEqual(schema_res["missing_required_columns"], {})
        self.assertEqual(schema_res["missing_tabs"], [])
        self.assertGreater(len(schema_res["unreadable_tabs"]), 0)

        # Failed quota scan must NOT be cached; recovering on next call succeeds cleanly
        ss.fail_batch_exc = None
        recovered = db.inspect_schema_compatibility()
        self.assertEqual(recovered["status"], "COMPATIBLE")
        self.assertTrue(recovered["verification_completed"])
        self.assertFalse(recovered["cached"])

        # 2. Legacy per-tab row_values(1) raising 429 must fail fast and never report INCOMPATIBLE
        class Legacy429Spreadsheet:
            def __init__(self):
                self.calls = 0

            def worksheet(self, tab):
                self.calls += 1
                if self.calls >= 3:
                    raise MockQuotaAPIError("APIError: [429]: Quota exceeded for quota metric")

                class Ws:
                    def row_values(self_inner, row):
                        return list(REQUIRED_TABS.get(tab, ["id"]))

                return Ws()

        db.invalidate_diagnostic_cache()
        legacy_ss = Legacy429Spreadsheet()
        db.spreadsheet = legacy_ss
        legacy_res = db.inspect_schema_compatibility()
        self.assertEqual(legacy_res["status"], "TEMPORARILY_UNAVAILABLE")
        self.assertEqual(legacy_res["error_type"], "QUOTA_EXCEEDED")
        self.assertFalse(legacy_res["verification_completed"])
        self.assertEqual(legacy_res["missing_required_columns"], {})
        self.assertEqual(legacy_res.calls if hasattr(legacy_res, "calls") else legacy_ss.calls, 3)

    def test_network_error_distinguished_from_quota_and_schema_incompatibility(self):
        """Network/timeout failures must return CHECK_FAILED (NETWORK_ERROR), never INCOMPATIBLE."""
        ss = MockBatchSpreadsheet(fail_batch_on_call=1, fail_batch_exc=TimeoutError("Read timed out connecting to sheets.googleapis.com"))
        db.is_connected = True
        db.spreadsheet = ss

        schema_res = db.inspect_schema_compatibility()
        self.assertEqual(schema_res["status"], "CHECK_FAILED")
        self.assertEqual(schema_res["error_type"], "NETWORK_ERROR")
        self.assertFalse(schema_res["quota_exceeded"])
        self.assertFalse(schema_res["verification_completed"])
        self.assertEqual(schema_res["missing_tabs"], [])
        self.assertEqual(schema_res["missing_required_columns"], {})

        tabs_res = db.verify_tabs_accessibility()
        self.assertEqual(tabs_res["status"], "CHECK_FAILED")
        self.assertEqual(tabs_res["error_type"], "NETWORK_ERROR")
        self.assertFalse(tabs_res["all_tabs_accessible"])

    def test_genuine_schema_incompatibility_still_detected_accurately(self):
        """When all readable sheets succeed without errors, genuinely missing tabs/columns still report INCOMPATIBLE."""
        headers_by_tab = {t: list(cols) for t, cols in REQUIRED_TABS.items()}
        # Genuinely empty header row on Products and missing Sales tab
        headers_by_tab["Products"] = []
        ss = MockBatchSpreadsheet(headers_by_tab=headers_by_tab, missing_tabs={"Sales"})
        db.is_connected = True
        db.spreadsheet = ss

        res = db.inspect_schema_compatibility()
        self.assertEqual(res["status"], "INCOMPATIBLE")
        self.assertTrue(res["verification_completed"])
        self.assertIsNone(res["error_type"])
        self.assertEqual(res["missing_tabs"], ["Sales"])
        self.assertIn("Products", res["missing_required_columns"])

    def test_public_health_is_minimal_and_hides_infrastructure_and_secrets(self):
        """Public /health and /api/health stay Render/frontend-compatible without leaking config or secrets."""
        db.is_connected = False
        db.spreadsheet = None
        db.last_connection_error = (
            "Failed /etc/secrets/sales-service-account.json for sa@proj.iam.gserviceaccount.com spreadsheet 1abcXYZ999"
        )

        pub = health_check()
        self.assertEqual(pub["status"], "storage_disconnected")
        self.assertEqual(pub["service"], "kawad-swad-sales-dev")
        self.assertFalse(pub["google_sheets_connected"])
        self.assertFalse(pub["persistent_writes_enabled"])
        self.assertEqual(pub["backend"]["status"], "CONNECTED")
        for forbidden_key in (
            "spreadsheet_id_configured",
            "service_account_configured",
            "allow_in_memory_fallback",
            "last_connection_error",
            "google_sheets",
            "required_sheets",
        ):
            self.assertNotIn(forbidden_key, pub)

        db.is_connected = True
        db.spreadsheet = MockBatchSpreadsheet()
        pub_ok = health_check()
        self.assertEqual(pub_ok["status"], "ok")
        self.assertTrue(pub_ok["google_sheets_connected"])
        self.assertTrue(pub_ok["persistent_writes_enabled"])

    def test_protected_health_diagnostics_require_owner_or_pa_and_redact_secrets(self):
        """Detailed health, reconnect, verify-tabs, and schema-compatibility require Owner/PA and redact secrets."""
        # Non-manager roles must get 403 Forbidden
        for unauthorized in (self.salesman, self.accountant):
            for fn in (
                lambda u=unauthorized: health_details(current_user=u),
                lambda u=unauthorized: health_reconnect(current_user=u),
                lambda u=unauthorized: health_verify_tabs(current_user=u),
                lambda u=unauthorized: health_schema_compatibility(current_user=u),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    fn()
                self.assertEqual(ctx.exception.status_code, 403)

        # Owner and PA are permitted and sensitive values are redacted
        db.is_connected = True
        db.spreadsheet = MockBatchSpreadsheet()
        with patch("app.config.SALES_GOOGLE_SPREADSHEET_ID", "1RealSecretSheetIdABC123"):
            with patch("app.config.SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/etc/secrets/sales-service-account.json"):
                db.last_connection_error = (
                    "Could not open 1RealSecretSheetIdABC123 with /etc/secrets/sales-service-account.json "
                    "and kawad-sa@demo-proj.iam.gserviceaccount.com"
                )
                details = health_details(current_user=self.pa)
                self.assertNotIn("1RealSecretSheetIdABC123", str(details))
                self.assertNotIn("/etc/secrets/sales-service-account.json", str(details))
                self.assertNotIn("kawad-sa@demo-proj.iam.gserviceaccount.com", str(details))
                self.assertIn("[REDACTED]", details["last_connection_error"])
                self.assertIn("[REDACTED_SERVICE_ACCOUNT]", details["last_connection_error"])

                tabs_out = health_verify_tabs(current_user=self.owner)
                self.assertEqual(tabs_out["status"], "OK")
                schema_out = health_schema_compatibility(current_user=self.pa)
                self.assertEqual(schema_out["status"], "COMPATIBLE")

    def test_fastapi_routes_enforce_auth_dependencies(self):
        """Verify FastAPI route definitions for protected health endpoints require Depends(auth.get_current_user)."""
        main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "main.py"))
        with open(main_path, "r", encoding="utf-8") as f:
            src = f.read()

        for fn_sig in (
            "def health_details(current_user: dict = Depends(auth.get_current_user))",
            "def health_reconnect(current_user: dict = Depends(auth.get_current_user))",
            "def health_verify_tabs(refresh: bool = False, current_user: dict = Depends(auth.get_current_user))",
            "def health_schema_compatibility(refresh: bool = False, current_user: dict = Depends(auth.get_current_user))",
            "def health_backup(current_user: dict = Depends(auth.get_current_user))",
        ):
            self.assertIn(fn_sig, src)


if __name__ == "__main__":
    unittest.main()
