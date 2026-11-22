"""
Mission 51B-1R — TX-FINAL-05 Regression Suite: SQLite Corruption / Read Fail-Open Prevention.

Verifies:
- Corrupted SQLite database file bytes -> get_governed_transaction() & list_unresolved_transactions()
  raise CoordinatorDurabilityError (NEVER silently return None or []).
- Dropped governed_transactions table -> raises CoordinatorDurabilityError.
- Corrupted JSON in steps_json / result_snapshot_json -> raises CoordinatorDurabilityError (COORDINATOR_STORAGE_CORRUPTED).
- Corrupted SQLite during execute_governed_write() -> blocks mutation fail-closed (HTTP 503, 0 gateway POSTs).
- Corrupted SQLite during check_transaction_status() -> returns UNKNOWN_STORAGE_UNAVAILABLE with safe_to_retry_same_nonce=False.
"""

import os
import shutil
import sqlite3
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
from app.transaction_safety import CoordinatorDurabilityError, compute_deterministic_payload_hash


class TestTxFinal05SqliteCorruption(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_tx05_")
        self.db_path = os.path.join(self.tmp_dir, "coord_tx05.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.bridge = AppsScriptBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _seed_one_tx(self, nonce: str = "NONCE-TX05-SEED"):
        p_hash = compute_deterministic_payload_hash(
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload={"payment": {"sale_id": "SAL-1", "amount": 100}},
        )
        st, _ = self.coord.begin_governed_transaction(
            nonce=nonce,
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            actor_user_id="USR-OWNER-001",
            payload_hash=p_hash,
            correlation_id="CORR-TX05-1",
        )
        self.assertEqual(st, "ACQUIRED")

    def test_corrupted_sqlite_file_raises_instead_of_returning_none_or_empty(self):
        self._seed_one_tx("NONCE-TX05-BYTES")
        # Corrupt the SQLite file on disk with non-SQLite garbage bytes
        with open(self.db_path, "wb") as fh:
            fh.write(b"NOT_A_VALID_SQLITE_DATABASE_HEADER_CORRUPT_BYTES" * 64)

        with self.assertRaises(CoordinatorDurabilityError):
            self.coord.get_governed_transaction("NONCE-TX05-BYTES")

        with self.assertRaises(CoordinatorDurabilityError):
            self.coord.list_unresolved_transactions()

    def test_dropped_table_raises_coordinator_durability_error(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DROP TABLE governed_transactions;")
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(CoordinatorDurabilityError):
            self.coord.get_governed_transaction("NONCE-ANY")

        with self.assertRaises(CoordinatorDurabilityError):
            self.coord.list_unresolved_transactions()

    def test_corrupted_json_columns_raise_storage_corrupted(self):
        nonce_steps = "NONCE-TX05-BAD-STEPS"
        self._seed_one_tx(nonce_steps)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("UPDATE governed_transactions SET steps_json = '{bad-json' WHERE nonce = ?", (nonce_steps,))
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(CoordinatorDurabilityError) as ctx_s:
            self.coord.get_governed_transaction(nonce_steps)
        self.assertEqual(ctx_s.exception.error_code, "COORDINATOR_STORAGE_CORRUPTED")

        # Also test corrupted result_snapshot_json
        nonce_snap = "NONCE-TX05-BAD-SNAP"
        self._seed_one_tx(nonce_snap)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("UPDATE governed_transactions SET steps_json = '[]' WHERE nonce = ?", (nonce_steps,))
            conn.execute("UPDATE governed_transactions SET result_snapshot_json = '[not-a-dict]' WHERE nonce = ?", (nonce_snap,))
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(CoordinatorDurabilityError) as ctx_r:
            self.coord.get_governed_transaction(nonce_snap)
        self.assertEqual(ctx_r.exception.error_code, "COORDINATOR_STORAGE_CORRUPTED")

    def test_execute_governed_write_and_status_check_fail_closed_on_corrupted_sqlite(self):
        with open(self.db_path, "wb") as fh:
            fh.write(b"CORRUPTED_DB_PAYLOAD" * 128)

        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
            patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
            patch.object(bridge_mod.db, "get_records", return_value=[]),
            patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
            patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener,
        ):
            res = self.bridge.execute_governed_write(
                action="RECORD_SALE_PAYMENT",
                target_tab="Payments",
                payload={"payment": {"sale_id": "SAL-1", "customer_id": "CUST-1", "amount": 250.0, "payment_mode": "CASH"}},
                nonce="NONCE-TX05-WRITE",
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field="payment_id",
            )
            self.assertEqual(mock_opener.call_count, 0, "Corrupted SQLite MUST block gateway POST fail-closed")
            self.assertEqual(res.http_status, 503)
            self.assertNotEqual(res.status, "CONFIRMED")

            st = self.bridge.check_transaction_status(nonce="NONCE-TX05-WRITE", actor_is_owner=True)
            self.assertEqual(st["status"], "UNKNOWN_STORAGE_UNAVAILABLE")
            self.assertFalse(st["safe_to_retry_same_nonce"])


if __name__ == "__main__":
    unittest.main()
