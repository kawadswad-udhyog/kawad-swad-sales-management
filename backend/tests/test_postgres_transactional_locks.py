"""
Kawad Swad ERP - Transactional PostgreSQL & ACID Row-Level Locking Test Suite.

Verifies:
1. Row-level locking semantics and validation checks in PostgresDatabase.
2. High-concurrency mutual exclusion (race condition prevention across threads and processes).
3. Integration with customer_ledger.reserve_credit_approval, consume_credit_approval, and release_credit_approval.
4. Idempotency distributed locking and replay detection.
"""

import os
import sys
import time
import math
import unittest
import threading
import concurrent.futures
from datetime import date, timedelta

# Ensure backend and test paths
tests_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(tests_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_AUTH_MOCK"] = "1"

from app.db import get_postgres_db, PostgresDatabase
from app.sheets import db
from app.accounting.customer_ledger import (
    reserve_credit_approval,
    consume_credit_approval,
    release_credit_approval,
    reset_cross_process_state,
)
from fastapi import HTTPException


class TestPostgresTransactionalLocks(unittest.TestCase):
    def setUp(self):
        self.pg_db = get_postgres_db()
        self.pg_db.reset_database()
        reset_cross_process_state()
        db.memory_store = {tab: [] for tab in db.memory_store}

        # Seed test approval in db
        self.approval_id = "APR-TX-001"
        self.customer_id = "CUS-TEST-001"
        self.appr_data = {
            "request_id": self.approval_id,
            "request_type": "CREDIT_EXCEPTION",
            "customer_id": self.customer_id,
            "requested_amount": 5000.0,
            "approved_amount": 5000.0,
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "decided_at": "2026-11-10T10:00:00Z",
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_revoked": False,
        }
        self.pg_db.sync_approval_record(self.appr_data)

    def test_01_successful_approval_reservation(self):
        """Verifies row-level reservation succeeds and transitions state."""
        ok, err, row = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id=self.customer_id,
            requested_credit=3000.0,
        )
        self.assertTrue(ok, f"Expected successful reservation, got err: {err}")
        self.assertIsNone(err)

        # Check idempotent retry by same sale succeeds
        ok_retry, _, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id=self.customer_id,
            requested_credit=3000.0,
        )
        self.assertTrue(ok_retry)

    def test_02_concurrent_reservation_rejected(self):
        """Verifies that once reserved by SALE-001, another sale SALE-002 is rejected."""
        ok1, _, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id=self.customer_id,
            requested_credit=2000.0,
        )
        self.assertTrue(ok1)

        ok2, err2, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-002",
            customer_id=self.customer_id,
            requested_credit=2000.0,
        )
        self.assertFalse(ok2)
        self.assertIn("concurrently reserved by sale 'SALE-001'", err2)

    def test_03_consumption_lifecycle(self):
        """Verifies reserve -> consume lifecycle and prevention of double consumption."""
        # 1. Reserve
        ok_res, _, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id=self.customer_id,
            requested_credit=4000.0,
        )
        self.assertTrue(ok_res)

        # 2. Cannot be consumed by a different sale
        ok_cons_diff, err_diff = self.pg_db.consume_approval_tx(self.approval_id, "SALE-002")
        self.assertFalse(ok_cons_diff)
        self.assertIn("reserved by 'SALE-001'", err_diff)

        # 3. Consumed by reserving sale
        ok_cons, err_cons = self.pg_db.consume_approval_tx(self.approval_id, "SALE-001")
        self.assertTrue(ok_cons, f"Failed to consume: {err_cons}")

        # 4. Idempotent consumption replay by same sale succeeds
        ok_cons_idem, _ = self.pg_db.consume_approval_tx(self.approval_id, "SALE-001")
        self.assertTrue(ok_cons_idem)

        # 5. Cannot be released once consumed
        ok_rel, err_rel = self.pg_db.release_approval_tx(self.approval_id, "SALE-001")
        self.assertFalse(ok_rel)
        self.assertIn("Cannot release consumed approval", err_rel)

        # 6. Cannot be re-reserved by another sale
        ok_re_res, err_re_res, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-003",
            customer_id=self.customer_id,
            requested_credit=1000.0,
        )
        self.assertFalse(ok_re_res)
        self.assertIn("already been consumed", err_re_res)

    def test_04_release_and_re_reserve(self):
        """Verifies release unlocks approval so another sale can reserve it."""
        ok_res, _, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id=self.customer_id,
            requested_credit=3000.0,
        )
        self.assertTrue(ok_res)

        # Release
        ok_rel, err_rel = self.pg_db.release_approval_tx(self.approval_id, "SALE-001")
        self.assertTrue(ok_rel, f"Failed to release: {err_rel}")

        # Now SALE-002 can reserve it
        ok_res2, err2, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-002",
            customer_id=self.customer_id,
            requested_credit=3500.0,
        )
        self.assertTrue(ok_res2, f"Failed re-reservation: {err2}")

    def test_05_validation_rejections(self):
        """Verifies amount, customer, and revocation rejections under row locks."""
        # Amount exceeded
        ok, err, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id=self.customer_id,
            requested_credit=6000.0,  # Approved is 5000
        )
        self.assertFalse(ok)
        self.assertIn("exceeds approved limit", err)

        # Customer mismatch
        ok_c, err_c, _ = self.pg_db.reserve_approval_tx(
            approval_id=self.approval_id,
            sale_id="SALE-001",
            customer_id="CUS-DIFFERENT",
            requested_credit=1000.0,
        )
        self.assertFalse(ok_c)
        self.assertIn("does not match", err_c)

    def test_06_high_concurrency_race_condition_prevention(self):
        """
        Simulates 10 concurrent threads attempting to reserve the EXACT same approval.
        Guarantees that row-level locking permits exactly 1 winner and rejects 9.
        """
        num_workers = 10
        barrier = threading.Barrier(num_workers)
        results = []

        def worker_fn(worker_idx):
            sale_id = f"SALE-CONC-{worker_idx}"
            barrier.wait()  # synchronize start
            ok, err, _ = self.pg_db.reserve_approval_tx(
                approval_id=self.approval_id,
                sale_id=sale_id,
                customer_id=self.customer_id,
                requested_credit=1500.0,
            )
            results.append((worker_idx, ok, err, sale_id))

        threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r[1] is True]
        failures = [r for r in results if r[1] is False]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got {len(successes)}")
        self.assertEqual(len(failures), 9, f"Expected 9 rejections, got {len(failures)}")

        winner = successes[0]
        # The remaining 9 must all report concurrent reservation
        for fail in failures:
            self.assertIn("concurrently reserved", fail[2])

    def test_07_idempotency_distributed_locking(self):
        """Verifies acquire, conflict detection, in-flight blocking, and commit replay."""
        key = "IDEMP-KEY-999"
        p_hash = "hash_payload_abc"

        # 1. Acquire
        status1, _ = self.pg_db.acquire_idempotency_lock_tx(key, p_hash, "SALE-IDP-01")
        self.assertEqual(status1, "ACQUIRED")

        # 2. Conflicting payload rejected
        status_conf, _ = self.pg_db.acquire_idempotency_lock_tx(key, "hash_different", "SALE-IDP-02")
        self.assertEqual(status_conf, "CONFLICT")

        # 3. Concurrent same payload while in-flight reports IN_FLIGHT
        status_flight, _ = self.pg_db.acquire_idempotency_lock_tx(key, p_hash, "SALE-IDP-03")
        self.assertEqual(status_flight, "IN_FLIGHT")

        # 4. Complete
        mock_resp = {"sale_id": "SALE-IDP-01", "bill_total": 2500.0}
        self.assertTrue(self.pg_db.complete_idempotency_lock_tx(key, "SALE-IDP-01", mock_resp))

        # 5. Subsequent request replays committed response
        status_rep, resp = self.pg_db.acquire_idempotency_lock_tx(key, p_hash, "SALE-IDP-01")
        self.assertEqual(status_rep, "REPLAY")
        self.assertEqual(resp["sale_id"], "SALE-IDP-01")

    def test_08_integration_with_customer_ledger(self):
        """Verifies customer_ledger functions seamlessly coordinate with PostgresDatabase."""
        # Seed user and customer in sheets
        db.append_record("Users", {
            "user_id": "USR-OWNER-01",
            "username": "owner_test",
            "role": "OWNER",
            "active": "TRUE",
        })
        db.append_record("Customers", {
            "customer_id": self.customer_id,
            "shop_name": "Test Store",
            "credit_limit": 1000.0,
            "max_overdue_days": 30,
            "active": "TRUE",
        })
        db.append_record("ApprovalRequests", {
            "request_id": self.approval_id,
            "request_type": "CREDIT_EXCEPTION",
            "customer_id": self.customer_id,
            "approved_amount": 5000.0,
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        # 1. Reserve via customer_ledger
        self.assertTrue(reserve_credit_approval(self.approval_id, "SALE-LEDGER-01", self.customer_id, 3000.0))

        # 2. Competing reservation rejected via customer_ledger
        with self.assertRaises(HTTPException) as cm:
            reserve_credit_approval(self.approval_id, "SALE-LEDGER-02", self.customer_id, 3000.0)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("concurrently reserved", cm.exception.detail)

        # 3. Consume via customer_ledger
        self.assertTrue(consume_credit_approval(self.approval_id, "SALE-LEDGER-01"))

        # 4. Cannot be released once consumed
        self.assertFalse(release_credit_approval(self.approval_id, "SALE-LEDGER-01"))


if __name__ == "__main__":
    unittest.main()
