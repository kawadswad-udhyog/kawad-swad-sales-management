"""
Mission 51B-1R — TX-FINAL-07 Regression Suite: Post-Transmission Action/Table Mismatch -> UNKNOWN.

Verifies:
- Post-transmission Apps Script response with mismatched `action` is classified as:
  - lifecycle_state = TransactionState.UNKNOWN
  - bridge status = PENDING_UNKNOWN
  - http_status = 504
  - error_code = RESPONSE_ACTION_MISMATCH
  - failure_category = WRITE_OUTCOME_UNKNOWN
- Post-transmission Apps Script response with mismatched `target_tab` is classified as:
  - lifecycle_state = TransactionState.UNKNOWN
  - bridge status = PENDING_UNKNOWN
  - http_status = 504
  - error_code = RESPONSE_TABLE_MISMATCH
  - failure_category = WRITE_OUTCOME_UNKNOWN
- Subsequent same-nonce retry with mutated payload is blocked (HTTP 409 IDEMPOTENCY_PAYLOAD_CONFLICT).
- Subsequent same-nonce retry with identical payload runs recovery inspection cleanly.
"""

import json
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
from app.apps_script_bridge import AppsScriptBridge
from app.transaction_safety import FailureCategory, TransactionState


class _FakeHttpResp:
    def __init__(self, body_dict: dict, status: int = 200):
        self._body = json.dumps(body_dict).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class TestTxFinal07ResponseMismatch(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_tx07_")
        self.db_path = os.path.join(self.tmp_dir, "coord_tx07.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.bridge = AppsScriptBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _run_with_mismatched_response(self, *, nonce: str, echo_action: str, echo_tab: str):
        payload = {
            "payment": {
                "sale_id": "SAL-000001",
                "customer_id": "CUST-000001",
                "amount": 350.0,
                "payment_mode": "CASH",
            }
        }

        class _MismatchOpener:
            def open(self, req, timeout=None):
                body = json.loads(req.data.decode("utf-8"))
                return _FakeHttpResp(
                    {
                        "status": "CONFIRMED",
                        "correlation_id": body["correlation_id"],
                        "nonce": nonce,
                        "action": echo_action,
                        "target_tab": echo_tab,
                        "allocated_id": "RCPT-000777",
                    }
                )

        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
            patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
            patch.object(bridge_mod.db, "get_records", return_value=[]),
            patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
            patch.object(bridge_mod.db, "log_audit", return_value=True),
            patch.object(bridge_mod.urllib.request, "build_opener", return_value=_MismatchOpener()),
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
            return res, payload

    def test_response_action_mismatch_is_classified_as_unknown_504(self):
        nonce = "NONCE-TX07-ACT-MISMATCH"
        res, payload = self._run_with_mismatched_response(
            nonce=nonce,
            echo_action="CREATE_SALE",  # Mismatched action!
            echo_tab="Payments",
        )
        self.assertEqual(res.status, "PENDING_UNKNOWN")
        self.assertEqual(res.http_status, 504)
        self.assertEqual(res.error_code, "RESPONSE_ACTION_MISMATCH")
        self.assertEqual(res.transaction_state, TransactionState.UNKNOWN.value)
        self.assertEqual(res.failure_category, FailureCategory.WRITE_OUTCOME_UNKNOWN.value)
        self.assertTrue(res.retryable)

        persisted = self.coord.get_governed_transaction(nonce)
        self.assertEqual(persisted["lifecycle_state"], TransactionState.UNKNOWN.value)
        self.assertEqual(persisted["error_code"], "RESPONSE_ACTION_MISMATCH")

        # Same-nonce retry with mutated payload must be rejected with 409 IDEMPOTENCY_PAYLOAD_CONFLICT
        mutated_payload = {
            "payment": {
                "sale_id": "SAL-000001",
                "customer_id": "CUST-000001",
                "amount": 999.0,  # Mutated!
                "payment_mode": "CASH",
            }
        }
        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
            patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
            patch.object(bridge_mod.db, "get_records", return_value=[]),
            patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener,
        ):
            conflict_res = self.bridge.execute_governed_write(
                action="RECORD_SALE_PAYMENT",
                target_tab="Payments",
                payload=mutated_payload,
                nonce=nonce,
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
            self.assertEqual(mock_opener.call_count, 0)
            self.assertEqual(conflict_res.http_status, 409)
            self.assertEqual(conflict_res.error_code, "IDEMPOTENCY_PAYLOAD_CONFLICT")

    def test_response_table_mismatch_is_classified_as_unknown_504_and_recovers_on_same_nonce(self):
        nonce = "NONCE-TX07-TAB-MISMATCH"
        res, payload = self._run_with_mismatched_response(
            nonce=nonce,
            echo_action="RECORD_SALE_PAYMENT",
            echo_tab="Sales",  # Mismatched target_tab!
        )
        self.assertEqual(res.status, "PENDING_UNKNOWN")
        self.assertEqual(res.http_status, 504)
        self.assertEqual(res.error_code, "RESPONSE_TABLE_MISMATCH")
        self.assertEqual(res.transaction_state, TransactionState.UNKNOWN.value)
        self.assertEqual(res.failure_category, FailureCategory.WRITE_OUTCOME_UNKNOWN.value)

        # Simulate that the write actually landed cleanly in Sheets -> same-nonce retry recovers without new POST
        tables = {
            "IdAllocations": [{"nonce": nonce, "tab_name": "Payments", "allocated_id": "RCPT-000777"}],
            "AuditLog": [{"action": "RECORD_SALE_PAYMENT", "entity_type": "Payments", "entity_id": "RCPT-000777", "related_record_id": nonce}],
            "Payments": [{"payment_id": "RCPT-000777", "sale_id": "SAL-000001", "customer_id": "CUST-000001", "amount": 350.0, "payment_mode": "CASH"}],
            "JournalHeaders": [
                {
                    "journal_id": "JV-000777",
                    "voucher_type": "RECEIPT",
                    "reference_type": "PAYMENT_COLLECTION",
                    "reference_id": "RCPT-000777",
                    "status": "POSTED",
                    "total_debit": 350.0,
                    "total_credit": 350.0,
                }
            ],
            "JournalLines": [
                {"line_id": "JL-777A", "journal_id": "JV-000777", "account_code": "1115", "debit_amount": 350.0, "credit_amount": 0.0},
                {"line_id": "JL-777B", "journal_id": "JV-000777", "account_code": "1130", "debit_amount": 0.0, "credit_amount": 350.0},
            ],
        }
        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
            patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
            patch.object(bridge_mod.db, "get_records", side_effect=lambda tab, fresh=False: list(tables.get(tab, []))),
            patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
            patch.object(bridge_mod.db, "log_audit", return_value=True),
            patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener,
        ):
            rec_res = self.bridge.execute_governed_write(
                action="RECORD_SALE_PAYMENT",
                target_tab="Payments",
                payload=payload,
                nonce=nonce,
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
            self.assertEqual(mock_opener.call_count, 0, "Recovered UNKNOWN mismatch must NOT duplicate POST")
            self.assertEqual(rec_res.status, "CONFIRMED")
            self.assertEqual(rec_res.allocated_id, "RCPT-000777")
            self.assertEqual(
                self.coord.get_governed_transaction(nonce)["lifecycle_state"],
                TransactionState.COMMITTED.value,
            )


if __name__ == "__main__":
    unittest.main()
