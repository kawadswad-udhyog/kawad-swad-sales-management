"""
Mission 51B-1R — TX-FINAL-06 Regression Suite: Concurrent UNKNOWN Recovery CAS Race.

Verifies:
- Two concurrent threads synchronized via threading.Barrier right before the UNKNOWN -> PENDING
  CAS transition on the exact same UNKNOWN nonce:
  - Exactly ONE winner acquires PENDING -> EXECUTING and transmits at most ONE Sheets gateway POST.
  - The losing worker receives a handled conflict response (HTTP 409 CONCURRENT_RECOVERY_CONFLICT
    or safe replay if winner already committed) — NEVER an uncaught InvalidStateTransitionError
    or HTTP 500 — and executes ZERO duplicate Sheets gateway POSTs.
  - Total gateway HTTP POST calls across both competing workers == 1.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import tests  # noqa: F401 - activates offline fastapi shim

from app import apps_script_bridge as bridge_mod
from app.accounting.transaction_coordinator import TransactionCoordinator
from app.apps_script_bridge import AppsScriptBridge
from app.transaction_safety import (
    TransactionState,
    TransitionAuthority,
    compute_deterministic_payload_hash,
)


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


class TestTxFinal06ConcurrentRecoveryRace(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_tx06_")
        self.db_path = os.path.join(self.tmp_dir, "coord_tx06.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.bridge = AppsScriptBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _seed_unknown_payment(self, nonce: str, payload: dict):
        p_hash = compute_deterministic_payload_hash(
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload=payload,
        )
        st, _ = self.coord.begin_governed_transaction(
            nonce=nonce,
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            actor_user_id="USR-OWNER-001",
            payload_hash=p_hash,
            correlation_id="CORR-ORIG-UNK",
        )
        self.assertEqual(st, "ACQUIRED")
        self.coord.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state=TransactionState.UNKNOWN.value,
            bridge_status="PENDING_UNKNOWN",
            failure_category="WRITE_OUTCOME_UNKNOWN",
            error_code="APPS_SCRIPT_TIMEOUT",
            message="Simulated ambiguous timeout",
            clear_lease=True,
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=1,
            expected_correlation_id="CORR-ORIG-UNK",
            expected_attempt=1,
        )

    def test_concurrent_unknown_recovery_cas_race_single_write_zero_500s(self):
        nonce = "NONCE-TX06-RACE-1"
        payload = {
            "payment": {
                "sale_id": "SAL-000010",
                "customer_id": "CUST-000010",
                "amount": 500.0,
                "payment_mode": "UPI",
            }
        }
        self._seed_unknown_payment(nonce, payload)

        # Synchronize both worker threads right before UNKNOWN -> PENDING CAS transition
        cas_barrier = threading.Barrier(2, timeout=5.0)
        orig_transition = self.coord.transition_governed_transaction

        def _synchronized_transition(*args, **kwargs):
            if (
                kwargs.get("nonce") == nonce
                and str(kwargs.get("lifecycle_state") or "") == TransactionState.PENDING.value
                and kwargs.get("authority") == TransitionAuthority.RECOVERY
            ):
                cas_barrier.wait()
            return orig_transition(*args, **kwargs)

        tables_lock = threading.Lock()
        tables = {
            "IdAllocations": [],
            "AuditLog": [],
            "Payments": [],
            "JournalHeaders": [],
            "JournalLines": [],
        }
        post_count = {"n": 0}

        class _FakeOpener:
            def open(self, req, timeout=None):
                body = json.loads(req.data.decode("utf-8"))
                corr = body["correlation_id"]
                with tables_lock:
                    post_count["n"] += 1
                    pid = f"RCPT-{post_count['n']:06d}"
                    tables["IdAllocations"].append({"nonce": nonce, "tab_name": "Payments", "allocated_id": pid})
                    tables["Payments"].append(
                        {"payment_id": pid, "sale_id": "SAL-000010", "customer_id": "CUST-000010", "amount": 500.0, "payment_mode": "UPI"}
                    )
                    tables["JournalHeaders"].append(
                        {
                            "journal_id": "JV-000600",
                            "voucher_type": "RECEIPT",
                            "reference_type": "PAYMENT_COLLECTION",
                            "reference_id": pid,
                            "status": "POSTED",
                            "total_debit": 500.0,
                            "total_credit": 500.0,
                        }
                    )
                    tables["JournalLines"].extend([
                        {"line_id": "JL-601", "journal_id": "JV-000600", "account_code": "1120", "debit_amount": 500.0, "credit_amount": 0.0},
                        {"line_id": "JL-602", "journal_id": "JV-000600", "account_code": "1130", "debit_amount": 0.0, "credit_amount": 500.0},
                    ])
                return _FakeHttpResp(
                    {
                        "status": "CONFIRMED",
                        "correlation_id": corr,
                        "nonce": nonce,
                        "action": "RECORD_SALE_PAYMENT",
                        "target_tab": "Payments",
                        "allocated_id": pid,
                        "record": {"payment_id": pid, "amount": 500.0},
                    }
                )

        def _fake_get_records(tab_name, fresh=False):
            with tables_lock:
                return list(tables.get(tab_name, []))

        results = []
        uncaught = []

        def _worker(idx: int):
            try:
                res = self.bridge.execute_governed_write(
                    action="RECORD_SALE_PAYMENT",
                    target_tab="Payments",
                    payload=payload,
                    nonce=nonce,
                    actor_user_id="USR-OWNER-001",
                    actor_role="OWNER_ADMIN",
                    id_field="payment_id",
                    correlation_id=f"CORR-RACE-W{idx}",
                )
                results.append(res)
            except Exception as exc:
                uncaught.append(exc)

        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(self.coord, "transition_governed_transaction", side_effect=_synchronized_transition),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
            patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
            patch.object(bridge_mod.db, "get_records", side_effect=_fake_get_records),
            patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
            patch.object(bridge_mod.db, "log_audit", return_value=True),
            patch.object(bridge_mod.urllib.request, "build_opener", return_value=_FakeOpener()),
        ):
            t1 = threading.Thread(target=_worker, args=(1,))
            t2 = threading.Thread(target=_worker, args=(2,))
            t1.start()
            t2.start()
            t1.join(timeout=10.0)
            t2.join(timeout=10.0)

        self.assertEqual(uncaught, [], f"No uncaught exceptions allowed in recovery CAS race: {uncaught}")
        self.assertEqual(len(results), 2)
        self.assertEqual(post_count["n"], 1, f"Expected exactly 1 gateway POST across competing workers, got {post_count['n']}")

        # Winner must be CONFIRMED (200); loser must be handled conflict (409 CONCURRENT_RECOVERY_CONFLICT or safe replay)
        statuses = sorted(r.http_status for r in results)
        self.assertNotIn(500, statuses, "Loser MUST NOT return HTTP 500")
        confirmed = [r for r in results if r.status == "CONFIRMED"]
        self.assertGreaterEqual(len(confirmed), 1, "At least the winning worker must confirm cleanly")
        non_confirmed = [r for r in results if r.status != "CONFIRMED"]
        for loser in non_confirmed:
            self.assertEqual(loser.http_status, 409)
            self.assertIn(loser.error_code, {"CONCURRENT_RECOVERY_CONFLICT", "TRANSACTION_IN_PROGRESS"})

        final_tx = self.coord.get_governed_transaction(nonce)
        self.assertEqual(final_tx["lifecycle_state"], TransactionState.COMMITTED.value)
        self.assertEqual(final_tx["allocated_id"], "RCPT-000001")


if __name__ == "__main__":
    unittest.main()
