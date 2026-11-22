"""
Mission 51B-1R — TX-FINAL-02 Regression Suite: Fail-Open Sheets Allocation Lookup.

Verifies that `_find_existing_sheets_allocation_for_nonce()` and its callers:
- Return `None` ONLY when `IdAllocations` is cleanly read as a valid list of dicts with no match.
- Raise `_SheetsAllocationLookupError` on TimeoutError, connectivity failure, HTTP 503/RuntimeError,
  None response, non-list dict/string response, or malformed non-dict row inside the list.
- Block any new financial mutation fail-closed (HTTP 503 `SHEETS_ALLOCATION_LOOKUP_FAILED`) with
  ZERO gateway HTTP POST calls and ZERO local transaction begin/mutation when lookup fails.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import tests  # noqa: F401 - activates offline fastapi shim

from app import apps_script_bridge as bridge_mod
from app.accounting.transaction_coordinator import TransactionCoordinator
from app.apps_script_bridge import AppsScriptBridge, _SheetsAllocationLookupError


class TestTxFinal02AllocationLookup(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_tx02_")
        self.db_path = os.path.join(self.tmp_dir, "coord_tx02.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.bridge = AppsScriptBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_clean_empty_list_returns_none_and_match_returns_row(self):
        with patch.object(bridge_mod.db, "get_records", return_value=[]):
            self.assertIsNone(self.bridge._find_existing_sheets_allocation_for_nonce("NONCE-ABSENT"))

        matching_row = {"nonce": "NONCE-FOUND", "tab_name": "Sales", "allocated_id": "SAL-000010"}
        with patch.object(bridge_mod.db, "get_records", return_value=[matching_row]):
            found = self.bridge._find_existing_sheets_allocation_for_nonce("NONCE-FOUND")
            self.assertEqual(found, matching_row)

    def test_lookup_raises_on_errors_and_malformed_responses(self):
        faults = [
            ("timeout", TimeoutError("Google Sheets API timed out")),
            ("connection_error", ConnectionError("Temporary network drop")),
            ("http_503", RuntimeError("503 Service Unavailable")),
            ("none_response", None),
            ("dict_response", {"error": "quota exceeded"}),
            ("string_response", "HTML error page"),
            ("malformed_row", [{"nonce": "OK"}, "corrupt-row-not-dict"]),
        ]

        for label, fault in faults:
            with self.subTest(fault=label):
                if isinstance(fault, Exception):
                    patcher = patch.object(bridge_mod.db, "get_records", side_effect=fault)
                else:
                    patcher = patch.object(bridge_mod.db, "get_records", return_value=fault)
                with patcher:
                    with self.assertRaises(_SheetsAllocationLookupError):
                        self.bridge._find_existing_sheets_allocation_for_nonce(f"NONCE-FAIL-{label}")

    def test_execute_governed_write_blocks_financial_post_when_allocation_lookup_fails(self):
        faults = [
            ("timeout", TimeoutError("Sheets timeout")),
            ("connectivity", OSError("Network unreachable")),
            ("malformed_none", None),
            ("malformed_dict", {"status": "error"}),
            ("malformed_list_item", ["not-a-dict"]),
        ]
        payload = {
            "payment": {
                "sale_id": "SAL-000001",
                "customer_id": "CUST-000001",
                "amount": 750.0,
                "payment_mode": "CASH",
            }
        }

        for idx, (label, fault) in enumerate(faults):
            with self.subTest(fault=label):
                nonce = f"NONCE-TX02-BLOCK-{idx}"

                def _fake_get_records(tab_name, fresh=False):
                    if tab_name == "IdAllocations":
                        if isinstance(fault, Exception):
                            raise fault
                        return fault
                    return []

                with (
                    patch.object(bridge_mod, "tx_coordinator", self.coord),
                    patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
                    patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
                    patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
                    patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
                    patch.object(bridge_mod.db, "get_records", side_effect=_fake_get_records),
                    patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
                    patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener,
                ):
                    res = self.bridge.execute_governed_write(
                        action="RECORD_SALE_PAYMENT",
                        target_tab="Payments",
                        payload=payload,
                        nonce=nonce,
                        actor_user_id="USR-OWNER-001",
                        actor_role="OWNER_ADMIN",
                        id_field="payment_id",
                    )
                    self.assertEqual(mock_opener.call_count, 0, f"{label}: MUST NOT issue gateway POST on lookup failure")
                    self.assertEqual(res.http_status, 503)
                    self.assertEqual(res.error_code, "SHEETS_ALLOCATION_LOOKUP_FAILED")
                    self.assertNotEqual(res.status, "CONFIRMED")
                    self.assertIsNone(
                        self.coord.get_governed_transaction(nonce),
                        f"{label}: Must fail closed BEFORE beginning a new local transaction",
                    )


if __name__ == "__main__":
    unittest.main()
