"""
Phase 1.8 Adversarial Security Tests — Authoritative Fail-Closed Duplicate-ID Lookup & Concurrency Guard.

Verifies that pre-write duplicate-ID and cross-table collision validation in AppsScriptBridge:
1. Always reads fresh=True (never trusts stale cache).
2. Fails closed (HTTP 503, zero remote HTTP calls) on storage outages, timeouts, 429, 500, 503, and auth errors.
3. Fails closed (HTTP 503, zero remote HTTP calls) on malformed payloads (None, dict, str, non-dict rows).
4. Verifies Row-1 schema header evidence on BOTH empty and non-empty tables (missing/wrong/unverified headers fail closed;
   legitimate empty tables WITH verified headers containing the expected ID column pass preflight).
5. Fails closed on cross-table and child-table lookup outages and rejects cross-table collisions with HTTP 409.
6. Enforces an in-process concurrency guard preventing two threads from passing preflight for the same (tab, ID)
   and always releases reservations cleanly even on bridge error.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # noqa: F401 - standardized hardened stdlib shims

import app.apps_script_bridge as bridge_mod
import app.schema_registry as schema_reg
import app.sheets as sheets_mod
from app.apps_script_bridge import AppsScriptBridge


class _FakeWorksheet:
    def __init__(self, title, headers, rows=None, records_exc=None, headers_exc=None):
        self.title = title
        self._headers = headers
        self._rows = rows if rows is not None else []
        self._records_exc = records_exc
        self._headers_exc = headers_exc

    def row_values(self, row_idx):
        if self._headers_exc is not None:
            raise self._headers_exc
        return self._headers if row_idx == 1 else []

    def get_all_records(self):
        if self._records_exc is not None:
            raise self._records_exc
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, ws_map):
        self._ws_map = ws_map

    def worksheet(self, tab_name):
        if tab_name not in self._ws_map:
            raise KeyError(f"Worksheet {tab_name} not found")
        return self._ws_map[tab_name]


class TestPhase18DuplicateIdSecurity(unittest.TestCase):
    def setUp(self):
        self._orig_connected = sheets_mod.db.is_connected
        self._orig_spreadsheet = sheets_mod.db.spreadsheet
        self._orig_fallback = sheets_mod.db.allow_in_memory_fallback
        sheets_mod.db._records_cache.clear()
        sheets_mod.db._worksheets.clear()
        sheets_mod.db._test_tab_headers.clear()
        schema_reg.clear_runtime_core_schema_reconciliations()
        with AppsScriptBridge._INFLIGHT_ID_LOCK:
            AppsScriptBridge._INFLIGHT_IDS.clear()

    def tearDown(self):
        sheets_mod.db.is_connected = self._orig_connected
        sheets_mod.db.spreadsheet = self._orig_spreadsheet
        sheets_mod.db.allow_in_memory_fallback = self._orig_fallback
        sheets_mod.db._records_cache.clear()
        sheets_mod.db._worksheets.clear()
        sheets_mod.db._test_tab_headers.clear()
        schema_reg.clear_runtime_core_schema_reconciliations()
        with AppsScriptBridge._INFLIGHT_ID_LOCK:
            AppsScriptBridge._INFLIGHT_IDS.clear()

    def _run_journal_write(self, journal_id="JV-000101", lines=None, nonce="NONCE-P18-JV-1"):
        bridge = AppsScriptBridge()
        return bridge.execute_governed_write(
            action="POST_JOURNAL_VOUCHER",
            target_tab="JournalHeaders",
            payload={
                "journal_id": journal_id,
                "lines": lines if lines is not None else [
                    {"line_id": "JVL-000101", "debit": 100, "credit": 0},
                    {"line_id": "JVL-000102", "debit": 0, "credit": 100},
                ],
            },
            nonce=nonce,
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            id_field="journal_id",
        )

    def test_stale_cache_cannot_hide_existing_duplicate_id_fresh_true_enforced(self):
        """Cached empty rows must NEVER bypass duplicate detection; fresh=True must read live worksheet."""
        ws_headers = _FakeWorksheet(
            "JournalHeaders",
            headers=sheets_mod.REQUIRED_TABS["JournalHeaders"],
            rows=[{"journal_id": "JV-000101", "entry_date": "2026-11-19"}],
        )
        ws_lines = _FakeWorksheet(
            "JournalLines",
            headers=sheets_mod.REQUIRED_TABS["JournalLines"],
            rows=[],
        )
        sheets_mod.db.is_connected = True
        sheets_mod.db.spreadsheet = _FakeSpreadsheet({
            "JournalHeaders": ws_headers,
            "JournalLines": ws_lines,
        })
        # Poison the read cache with a fresh-timestamp EMPTY list
        sheets_mod.db._records_cache["JournalHeaders"] = (time.monotonic(), [])

        observed_fresh_flags = []
        orig_get_records = sheets_mod.db.get_records

        def spy_get_records(tab_name, fresh=False):
            observed_fresh_flags.append((tab_name, fresh))
            return orig_get_records(tab_name, fresh=fresh)

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", side_effect=spy_get_records):
            res = self._run_journal_write(journal_id="JV-000101", nonce="NONCE-STALE-CACHE")

        self.assertEqual(res.status, "REJECTED")
        self.assertEqual(res.http_status, 409)
        self.assertEqual(res.error_code, "DUPLICATE_RECORD_ID")
        self.assertIn(("JournalHeaders", True), observed_fresh_flags)
        self.assertTrue(all(flag is True for _, flag in observed_fresh_flags))
        mock_opener.assert_not_called()

    def test_storage_outages_timeout_429_500_503_auth_fail_closed_zero_remote_calls(self):
        """Every read outage class must fail closed with HTTP 503 and zero Apps Script HTTP POST calls."""
        outage_cases = [
            ("disconnected", RuntimeError("Persistent storage is unavailable: Google Sheets is disconnected.")),
            ("timeout", TimeoutError("Read timed out waiting for Google Sheets")),
            ("quota_429", RuntimeError("APIError: [429]: RESOURCE_EXHAUSTED Quota exceeded")),
            ("server_500", RuntimeError("APIError: [500]: Internal server error")),
            ("unavailable_503", RuntimeError("APIError: [503]: Service temporarily unavailable")),
            ("auth_401", PermissionError("401 Unauthorized: service account token invalid")),
        ]
        for label, exc in outage_cases:
            with self.subTest(outage=label):
                with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
                     patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
                     patch.object(bridge_mod.db, "get_records", side_effect=exc):
                    res = self._run_journal_write(journal_id="JV-000201", nonce=f"NONCE-OUTAGE-{label}")

                self.assertEqual(res.status, "REJECTED")
                self.assertEqual(res.http_status, 503)
                self.assertEqual(res.error_code, "DUPLICATE_CHECK_STORE_UNAVAILABLE")
                self.assertTrue(res.retryable)
                mock_opener.assert_not_called()

    def test_malformed_record_payloads_fail_closed_zero_remote_calls(self):
        """None, dict, str, int, or lists containing non-dict rows must fail closed (HTTP 503)."""
        malformed_cases = [
            ("none", None),
            ("dict", {"journal_id": "JV-000301"}),
            ("string", "corrupted-payload"),
            ("int", 42),
            ("list_with_none", [None]),
            ("list_with_str", [{"journal_id": "JV-000001"}, "bad-row"]),
            ("list_with_list", [["JV-000001"]]),
        ]
        for label, bad_payload in malformed_cases:
            with self.subTest(payload=label):
                with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
                     patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
                     patch.object(bridge_mod.db, "get_records", return_value=bad_payload):
                    res = self._run_journal_write(journal_id="JV-000301", nonce=f"NONCE-MAL-{label}")

                self.assertEqual(res.status, "REJECTED")
                self.assertEqual(res.http_status, 503)
                self.assertEqual(res.error_code, "DUPLICATE_CHECK_DATA_MALFORMED")
                self.assertTrue(res.retryable)
                mock_opener.assert_not_called()

    def test_missing_wrong_or_unverified_headers_fail_closed_even_when_rows_empty(self):
        """An empty row list with missing, wrong, or unreadable Row-1 headers must NEVER be treated as a safe empty table."""
        # Case 1: Empty Row-1 headers on connected worksheet
        ws_empty_hdr = _FakeWorksheet("JournalHeaders", headers=[], rows=[])
        sheets_mod.db.is_connected = True
        sheets_mod.db.spreadsheet = _FakeSpreadsheet({"JournalHeaders": ws_empty_hdr})

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            res_empty_hdr = self._run_journal_write(journal_id="JV-000401", nonce="NONCE-HDR-EMPTY")
        self.assertEqual(res_empty_hdr.status, "REJECTED")
        self.assertEqual(res_empty_hdr.http_status, 503)
        self.assertEqual(res_empty_hdr.error_code, "DUPLICATE_CHECK_SCHEMA_UNVERIFIED")
        mock_opener.assert_not_called()

        # Case 2: Wrong Row-1 headers lacking 'journal_id' on empty table
        ws_wrong_hdr = _FakeWorksheet("JournalHeaders", headers=["wrong_col_a", "wrong_col_b"], rows=[])
        sheets_mod.db._worksheets.clear()
        sheets_mod.db.spreadsheet = _FakeSpreadsheet({"JournalHeaders": ws_wrong_hdr})

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            res_wrong_hdr = self._run_journal_write(journal_id="JV-000402", nonce="NONCE-HDR-WRONG")
        self.assertEqual(res_wrong_hdr.status, "REJECTED")
        self.assertEqual(res_wrong_hdr.http_status, 503)
        self.assertEqual(res_wrong_hdr.error_code, "DUPLICATE_CHECK_SCHEMA_UNVERIFIED")
        mock_opener.assert_not_called()

        # Case 3: Header read throws exception
        ws_err_hdr = _FakeWorksheet(
            "JournalHeaders",
            headers=sheets_mod.REQUIRED_TABS["JournalHeaders"],
            rows=[],
            headers_exc=RuntimeError("503 header read timeout"),
        )
        sheets_mod.db._worksheets.clear()
        sheets_mod.db.spreadsheet = _FakeSpreadsheet({"JournalHeaders": ws_err_hdr})

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            res_err_hdr = self._run_journal_write(journal_id="JV-000403", nonce="NONCE-HDR-ERR")
        self.assertEqual(res_err_hdr.status, "REJECTED")
        self.assertEqual(res_err_hdr.http_status, 503)
        self.assertEqual(res_err_hdr.error_code, "DUPLICATE_CHECK_SCHEMA_UNVERIFIED")
        mock_opener.assert_not_called()

        # Case 4: Non-empty rows returned with arbitrary keys missing 'journal_id'
        ws_bad_row_cols = _FakeWorksheet(
            "JournalHeaders",
            headers=sheets_mod.REQUIRED_TABS["JournalHeaders"],
            rows=[{"unrelated_column": "value"}],
        )
        sheets_mod.db._worksheets.clear()
        sheets_mod.db.spreadsheet = _FakeSpreadsheet({"JournalHeaders": ws_bad_row_cols})

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener:
            res_bad_cols = self._run_journal_write(journal_id="JV-000404", nonce="NONCE-ROW-BADCOLS")
        self.assertEqual(res_bad_cols.status, "REJECTED")
        self.assertEqual(res_bad_cols.http_status, 503)
        self.assertEqual(res_bad_cols.error_code, "DUPLICATE_CHECK_SCHEMA_UNVERIFIED")
        mock_opener.assert_not_called()

    def test_legitimate_empty_table_with_verified_headers_passes_preflight(self):
        """A genuinely empty table with verified Row-1 headers containing expected ID columns passes preflight."""
        ws_headers = _FakeWorksheet(
            "JournalHeaders",
            headers=sheets_mod.REQUIRED_TABS["JournalHeaders"],
            rows=[],
        )
        ws_lines = _FakeWorksheet(
            "JournalLines",
            headers=sheets_mod.REQUIRED_TABS["JournalLines"],
            rows=[],
        )
        sheets_mod.db.is_connected = True
        sheets_mod.db.spreadsheet = _FakeSpreadsheet({
            "JournalHeaders": ws_headers,
            "JournalLines": ws_lines,
        })

        # Leave bridge unconfigured so we prove preflight PASSED and reached the bridge configuration gate
        with patch.object(AppsScriptBridge, "is_configured", return_value=False):
            res = self._run_journal_write(journal_id="JV-000501", nonce="NONCE-LEGIT-EMPTY")

        self.assertEqual(res.status, "BLOCKED_PENDING_OWNER_SETUP")
        self.assertEqual(res.error_code, "APPS_SCRIPT_BRIDGE_UNCONFIGURED")

    def test_cross_table_and_child_lookup_outages_fail_closed_zero_remote_calls(self):
        """Failure reading cross-table (SalaryReceipts/Payments) or child table (JournalLines) must fail closed."""
        schema_reg.approve_core_schema_reconciliation(
            "Sales",
            headers=schema_reg.get_expected_canonical_reconciliation_headers("Sales"),
            approved_by="USR-OWNER-001",
        )

        def fail_on_salary_receipts(tab_name, fresh=False):
            if tab_name == "SalaryReceipts":
                raise TimeoutError("SalaryReceipts read timed out")
            return []

        bridge = AppsScriptBridge()
        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", side_effect=fail_on_salary_receipts):
            res_cross = bridge.execute_governed_write(
                action="RECORD_SALE_PAYMENT",
                target_tab="Payments",
                payload={"payment_id": "RCPT-000701", "sale_id": "INV-000001", "amount": 500},
                nonce="NONCE-CROSS-OUTAGE",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
        self.assertEqual(res_cross.status, "REJECTED")
        self.assertEqual(res_cross.http_status, 503)
        self.assertEqual(res_cross.error_code, "DUPLICATE_CHECK_STORE_UNAVAILABLE")
        mock_opener.assert_not_called()

        def fail_on_journal_lines(tab_name, fresh=False):
            if tab_name == "JournalLines":
                raise RuntimeError("429 Quota exceeded on JournalLines")
            return []

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener, \
             patch.object(bridge_mod.db, "get_records", side_effect=fail_on_journal_lines):
            res_child = self._run_journal_write(journal_id="JV-000702", nonce="NONCE-CHILD-OUTAGE")
        self.assertEqual(res_child.status, "REJECTED")
        self.assertEqual(res_child.http_status, 503)
        self.assertEqual(res_child.error_code, "DUPLICATE_CHECK_STORE_UNAVAILABLE")
        mock_opener.assert_not_called()

    def test_concurrent_in_process_duplicate_id_writes_allow_only_one_and_release_lock(self):
        """Two concurrent threads submitting the exact same ID cannot both enter the HTTP bridge."""
        entered_bridge = threading.Event()
        release_bridge = threading.Event()
        opener_calls = []

        class SlowFakeOpener:
            def open(self, req, timeout=None):
                opener_calls.append(req)
                entered_bridge.set()
                release_bridge.wait(timeout=3.0)
                raise TimeoutError("Simulated slow bridge timeout")

        results = []

        def worker(idx):
            res = self._run_journal_write(journal_id="JV-000999", nonce=f"NONCE-CONC-{idx}")
            results.append(res)

        with patch.object(AppsScriptBridge, "is_configured", return_value=True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40), \
             patch.object(bridge_mod.urllib.request, "build_opener", return_value=SlowFakeOpener()):
            t1 = threading.Thread(target=worker, args=(1,))
            t1.start()
            self.assertTrue(entered_bridge.wait(timeout=2.0), "First thread should enter bridge")

            t2 = threading.Thread(target=worker, args=(2,))
            t2.start()
            t2.join(timeout=2.0)

            release_bridge.set()
            t1.join(timeout=2.0)

        self.assertEqual(len(opener_calls), 1, "Only one concurrent thread may enter remote bridge")
        self.assertEqual(len(results), 2)
        codes = sorted(r.error_code for r in results)
        self.assertEqual(codes, ["APPS_SCRIPT_UNKNOWN_OUTCOME", "DUPLICATE_RECORD_ID"])
        # Verify in-flight reservation map was cleanly released (no leaked lock)
        with AppsScriptBridge._INFLIGHT_ID_LOCK:
            self.assertEqual(len(AppsScriptBridge._INFLIGHT_IDS), 0)

    def test_direct_id_exists_wrapper_raises_instead_of_failing_open(self):
        """Direct calls to _id_exists_in_tab must raise RuntimeError on storage failure, never return False."""
        with patch.object(bridge_mod.db, "get_records", side_effect=RuntimeError("Sheets unavailable")):
            with self.assertRaises(RuntimeError) as ctx:
                AppsScriptBridge._id_exists_in_tab("JournalHeaders", ("journal_id",), "JV-000001")
            self.assertIn("DUPLICATE_CHECK_STORE_UNAVAILABLE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
