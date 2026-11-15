# backend/tests/test_stock_discrepancy_idempotency.py
"""
Kawad Swad ERP - Stock Discrepancy Approval Idempotency & Recovery Test Suite
Verifies:
Test A: Sequential duplicate approval -> exactly one ledger adjustment.
Test B: Concurrent approval across separate OS processes -> exactly one ledger adjustment, consistent responses.
Test C: Failure after ledger append -> retry detects existing DISC-{id}, appends 0 new movements, completes status APPROVED.
Test D: Already rejected discrepancy -> approval blocked (422), 0 movements created.
Test E: Conflicting existing movement -> approval blocked (422), diagnostic audit logged, 0 new movements.
Test F: Company warehouse discrepancy -> exactly one correct warehouse adjustment.
Test G: Salesman discrepancy -> exactly one correct salesman adjustment.
"""

import asyncio
import multiprocessing
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from fastapi import HTTPException

tests_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(tests_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)
os.environ["PYTHONPATH"] = f"{backend_dir}:{tests_dir}:{os.environ.get('PYTHONPATH', '')}"

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_AUTH_MOCK"] = "1"

from app.sheets import db
from app.stock_math import balances, salesman_available
from app.routers import stock


def _concurrent_review_worker(
    test_dir: str,
    discrepancy_id: str,
    action: str,
    notes: str,
    user_dict: dict,
    result_queue: multiprocessing.Queue,
    barrier=None,
):
    """Isolated OS worker process calling review_stock_discrepancy under shared lock."""
    pid = os.getpid()
    try:
        db.enable_shared_file_store(test_dir)
        if barrier is not None:
            barrier.wait(timeout=5)
        req = stock.StockDiscrepancyReview(action=action, notes=notes)
        res = asyncio.run(stock.review_stock_discrepancy(discrepancy_id, req, current_user=user_dict))
        result_queue.put({"pid": pid, "success": True, "result": res})
    except HTTPException as exc:
        result_queue.put({"pid": pid, "success": False, "status_code": exc.status_code, "detail": exc.detail})
    except Exception as exc:
        result_queue.put({"pid": pid, "success": False, "status_code": 500, "error": str(exc)})


class TestStockDiscrepancyIdempotency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="ks_disc_idem_test_")
        db.enable_shared_file_store(cls.test_dir)

    @classmethod
    def tearDownClass(cls):
        db.disable_shared_file_store()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        db.enable_shared_file_store(self.test_dir)
        for tab in list(db.memory_store.keys()):
            path = db._tab_file_path(tab)
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass
            db.memory_store[tab] = []

        self.owner_user = {"user_id": "USR-TEST-OWNER", "full_name": "Ramesh Owner", "role": "OWNER"}
        self.salesman_user = {"user_id": "USR-SALES-101", "full_name": "Mohan Lal", "role": "SALESMAN"}

        for u in [self.owner_user, self.salesman_user]:
            db.append_record("Users", {
                "user_id": u["user_id"],
                "full_name": u["full_name"],
                "role": u["role"],
                "active": "true",
            })

        db.append_record("Products", {
            "product_id": "PRD-MOONG-200G",
            "sku": "KS-MNG-200",
            "product_name": "Moong Master 200g",
            "pack_weight_g": 200,
            "selling_unit": "PACKET",
            "active": "true",
        })
        db.append_record("Products", {
            "product_id": "PRD-GARLIC-200G",
            "sku": "KS-GRL-200",
            "product_name": "Moong Garlic 200g",
            "pack_weight_g": 200,
            "selling_unit": "PACKET",
            "active": "true",
        })

        # Seed warehouse with 100 packets and salesman with 20 packets
        now = datetime.now(timezone.utc).isoformat()
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": db.generate_id("SalesmanStockLedger"),
            "txn_datetime": now,
            "salesman_user_id": "",
            "product_id": "PRD-MOONG-200G",
            "sku_snapshot": "KS-MNG-200",
            "txn_type": "COMPANY_RECEIPT",
            "quantity": 120,
            "unit": "PACKET",
            "pack_weight_g": 200,
            "reference_id": "SEED-WH",
        })
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": db.generate_id("SalesmanStockLedger"),
            "txn_datetime": now,
            "salesman_user_id": "USR-SALES-101",
            "product_id": "PRD-MOONG-200G",
            "sku_snapshot": "KS-MNG-200",
            "txn_type": "ISSUE_TO_SALESMAN",
            "quantity": 20,
            "unit": "PACKET",
            "pack_weight_g": 200,
            "reference_id": "SEED-VAN",
        })

    def test_A_sequential_duplicate_approval(self):
        """Test A: Approving a discrepancy (-2 packets) twice creates exactly one ledger adjustment."""
        disc_req = stock.StockDiscrepancyCreate(
            location="USR-SALES-101",
            product_id="PRD-MOONG-200G",
            expected_stock=20,
            physical_count=18,
            reason="2 packets damaged in van",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.salesman_user))
        disc_id = sub["discrepancy_id"]

        rev_req = stock.StockDiscrepancyReview(action="APPROVE", notes="Verified")
        res1 = asyncio.run(stock.review_stock_discrepancy(disc_id, rev_req, self.owner_user))
        res2 = asyncio.run(stock.review_stock_discrepancy(disc_id, rev_req, self.owner_user))

        self.assertEqual(res1["status"], "APPROVED")
        self.assertEqual(res2["status"], "APPROVED")

        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns = [tx for tx in ledger if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns), 1, f"Expected 1 adjustment, found {len(disc_txns)}")
        self.assertEqual(disc_txns[0]["quantity"], -2)
        self.assertEqual(salesman_available(ledger, "USR-SALES-101", "PRD-MOONG-200G"), 18)

    def test_B_concurrent_approval_multiprocessing(self):
        """Test B: Two separate OS processes approve the same discrepancy simultaneously -> exactly one ledger adjustment."""
        for iteration in range(3):
            self.setUp()
            disc_req = stock.StockDiscrepancyCreate(
                location="WAREHOUSE",
                product_id="PRD-MOONG-200G",
                expected_stock=100,
                physical_count=98,
                reason=f"Concurrent count diff -2 iter {iteration}",
            )
            sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
            disc_id = sub["discrepancy_id"]

            ctx = multiprocessing.get_context("fork")
            res_q = ctx.Queue()
            barrier = ctx.Barrier(2)
            p1 = ctx.Process(
                target=_concurrent_review_worker,
                args=(self.test_dir, disc_id, "APPROVE", "Worker 1 approval", self.owner_user, res_q, barrier),
            )
            p2 = ctx.Process(
                target=_concurrent_review_worker,
                args=(self.test_dir, disc_id, "APPROVE", "Worker 2 approval", self.owner_user, res_q, barrier),
            )

            p1.start()
            p2.start()
            p1.join(timeout=10)
            p2.join(timeout=10)

            results = []
            while not res_q.empty():
                results.append(res_q.get_nowait())

            self.assertEqual(len(results), 2, f"Expected 2 results, got {results}")
            pids = {r["pid"] for r in results}
            self.assertEqual(len(pids), 2, f"Expected 2 distinct worker PIDs, got {pids}")
            self.assertNotIn(os.getpid(), pids)

            for r in results:
                self.assertTrue(r.get("success"), f"Unexpected failure in concurrent approval: {r}")
                self.assertEqual(r["result"]["status"], "APPROVED")

            ledger = db.get_records("SalesmanStockLedger", fresh=True)
            disc_txns = [tx for tx in ledger if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
            self.assertEqual(len(disc_txns), 1, f"Iteration {iteration}: Expected 1 ledger row, got {len(disc_txns)}")
            wh_bal, _ = balances(ledger)
            self.assertEqual(wh_bal["PRD-MOONG-200G"], 98)
            print(f"[Discrepancy Test B iter={iteration}] PIDs={sorted(pids)} ledger_rows=1 wh_bal=98")

    def test_C_failure_after_ledger_append_and_recovery(self):
        """Test C: Failure on StockDiscrepancies update after ledger append -> retry finalizes status with 0 new movements."""
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=96,
            reason="4 packets short in warehouse rack",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id = sub["discrepancy_id"]

        # Inject write failure on StockDiscrepancies update AFTER SalesmanStockLedger append succeeds
        db.inject_failure_once("StockDiscrepancies", 1)
        rev_req = stock.StockDiscrepancyReview(action="APPROVE", notes="First attempt")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.review_stock_discrepancy(disc_id, rev_req, self.owner_user))
        self.assertEqual(ctx.exception.status_code, 503)

        # Ledger entry is saved, status is still PENDING_APPROVAL
        ledger_mid = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns_mid = [tx for tx in ledger_mid if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns_mid), 1)
        curr_disc = next(r for r in db.get_records("StockDiscrepancies", fresh=True) if r["discrepancy_id"] == disc_id)
        self.assertEqual(curr_disc["status"], "PENDING_APPROVAL")

        # Retry approval -> must detect existing DISC-{disc_id}, append 0 new rows, update status to APPROVED
        res_retry = asyncio.run(stock.review_stock_discrepancy(disc_id, stock.StockDiscrepancyReview(action="APPROVE", notes="Retry recovery"), self.owner_user))
        self.assertEqual(res_retry["status"], "APPROVED")

        ledger_final = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns_final = [tx for tx in ledger_final if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns_final), 1)
        wh_bal, _ = balances(ledger_final)
        self.assertEqual(wh_bal["PRD-MOONG-200G"], 96)

        final_disc = next(r for r in db.get_records("StockDiscrepancies", fresh=True) if r["discrepancy_id"] == disc_id)
        self.assertEqual(final_disc["status"], "APPROVED")

    def test_D_already_rejected_discrepancy_cannot_be_approved(self):
        """Test D: Attempting approval of an already REJECTED discrepancy fails (422) with zero stock movements."""
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=95,
            reason="Reported shortage",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id = sub["discrepancy_id"]

        rej_res = asyncio.run(stock.review_stock_discrepancy(
            disc_id,
            stock.StockDiscrepancyReview(action="REJECT", notes="Recount matched 100"),
            self.owner_user,
        ))
        self.assertEqual(rej_res["status"], "REJECTED")

        ledger_before = db.get_records("SalesmanStockLedger", fresh=True)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.review_stock_discrepancy(
                disc_id,
                stock.StockDiscrepancyReview(action="APPROVE", notes="Late approval attempt"),
                self.owner_user,
            ))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("REJECTED", ctx.exception.detail)

        ledger_after = db.get_records("SalesmanStockLedger", fresh=True)
        self.assertEqual(len(ledger_after), len(ledger_before))
        self.assertFalse(any(str(tx.get("reference_id")) == f"DISC-{disc_id}" for tx in ledger_after))

    def test_E_conflicting_existing_movement_blocks_approval(self):
        """Test E: Existing DISC-{id} movement with mismatched quantity or product blocks approval and logs diagnostic audit."""
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=97,
            reason="3 packets short",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id = sub["discrepancy_id"]

        # Inject conflicting ledger row for the same DISC-{disc_id} reference (wrong quantity 9 instead of 3)
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": db.generate_id("SalesmanStockLedger"),
            "txn_datetime": datetime.now(timezone.utc).isoformat(),
            "salesman_user_id": "",
            "product_id": "PRD-MOONG-200G",
            "sku_snapshot": "KS-MNG-200",
            "txn_type": "NEGATIVE_ADJUSTMENT",
            "quantity": 9,
            "unit": "PACKET",
            "pack_weight_g": 200,
            "reference_id": f"DISC-{disc_id}",
            "notes": "Conflicting movement",
        }, raise_on_error=True)

        ledger_before = db.get_records("SalesmanStockLedger", fresh=True)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.review_stock_discrepancy(
                disc_id,
                stock.StockDiscrepancyReview(action="APPROVE", notes="Attempt approval"),
                self.owner_user,
            ))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Conflicting", ctx.exception.detail)

        # No additional stock movement created, status stays PENDING_APPROVAL, diagnostic audit logged
        ledger_after = db.get_records("SalesmanStockLedger", fresh=True)
        self.assertEqual(len(ledger_after), len(ledger_before))
        curr_disc = next(r for r in db.get_records("StockDiscrepancies", fresh=True) if r["discrepancy_id"] == disc_id)
        self.assertEqual(curr_disc["status"], "PENDING_APPROVAL")

        audits = db.get_records("AuditLog", fresh=True)
        conflict_audit = next(
            (a for a in audits if str(a.get("action")) == "DISCREPANCY_LEDGER_CONFLICT" and str(a.get("entity_id")) == disc_id),
            None,
        )
        self.assertIsNotNone(conflict_audit, "Expected DISCREPANCY_LEDGER_CONFLICT diagnostic audit event")

    def test_F_company_warehouse_discrepancy(self):
        """Test F: Company warehouse discrepancy produces exactly one NEGATIVE_ADJUSTMENT and accurate warehouse balance."""
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=95,
            reason="5 packets broken in central warehouse",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id = sub["discrepancy_id"]

        res = asyncio.run(stock.review_stock_discrepancy(
            disc_id,
            stock.StockDiscrepancyReview(action="APPROVE", notes="Confirmed 5 broken"),
            self.owner_user,
        ))
        self.assertEqual(res["status"], "APPROVED")

        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns = [tx for tx in ledger if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns), 1)
        self.assertEqual(disc_txns[0]["txn_type"], "NEGATIVE_ADJUSTMENT")
        self.assertEqual(disc_txns[0]["quantity"], 5)
        self.assertEqual(disc_txns[0]["salesman_user_id"], "")

        wh_bal, _ = balances(ledger)
        self.assertEqual(wh_bal["PRD-MOONG-200G"], 95)

    def test_G_salesman_discrepancy(self):
        """Test G: Salesman discrepancy produces exactly one salesman adjustment and preserves salesman stock accuracy."""
        disc_req = stock.StockDiscrepancyCreate(
            location="USR-SALES-101",
            product_id="PRD-MOONG-200G",
            expected_stock=20,
            physical_count=18,
            reason="2 packets missing from van",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.salesman_user))
        disc_id = sub["discrepancy_id"]

        res = asyncio.run(stock.review_stock_discrepancy(
            disc_id,
            stock.StockDiscrepancyReview(action="APPROVE", notes="Approved salesman shortage"),
            self.owner_user,
        ))
        self.assertEqual(res["status"], "APPROVED")

        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns = [tx for tx in ledger if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns), 1)
        self.assertEqual(disc_txns[0]["txn_type"], "RETURN_FROM_SALESMAN")
        self.assertEqual(disc_txns[0]["quantity"], -2)
        self.assertEqual(disc_txns[0]["salesman_user_id"], "USR-SALES-101")
        self.assertEqual(salesman_available(ledger, "USR-SALES-101", "PRD-MOONG-200G"), 18)

    @staticmethod
    def _approval_audits(disc_id: str):
        audits = db.get_records("AuditLog", fresh=True)
        return [
            a for a in audits
            if str(a.get("entity_type", "")).strip() == "StockDiscrepancies"
            and str(a.get("entity_id", "")).strip() == disc_id
            and str(a.get("action", "")).strip().upper() == "APPROVED_STOCK_DISCREPANCY"
        ]

    def test_H_audit_log_failure_after_adjustment_and_status_update_and_retry_recovery(self):
        """Test H: AuditLog write failure raises 503 (never silent success); retry writes missing audit with 0 duplicate ledger moves."""
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=98,
            reason="2 packets missing for Test H",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id = sub["discrepancy_id"]

        # Inject AuditLog write failure: ledger append & StockDiscrepancies status update succeed, AuditLog append fails
        db.inject_failure_once("AuditLog", 1)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.review_stock_discrepancy(
                disc_id,
                stock.StockDiscrepancyReview(action="APPROVE", notes="Initial approval with audit failure"),
                self.owner_user,
            ))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("audit", ctx.exception.detail.lower())

        # Partial state verified: 1 ledger adjustment, status=APPROVED, 0 approval audit events yet
        ledger_mid = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns_mid = [tx for tx in ledger_mid if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns_mid), 1)
        curr_disc = next(r for r in db.get_records("StockDiscrepancies", fresh=True) if r["discrepancy_id"] == disc_id)
        self.assertEqual(curr_disc["status"], "APPROVED")
        self.assertEqual(len(self._approval_audits(disc_id)), 0)

        # Retry approval -> must repair missing AuditLog event and create 0 new ledger movements
        res_retry = asyncio.run(stock.review_stock_discrepancy(
            disc_id,
            stock.StockDiscrepancyReview(action="APPROVE", notes="Retry audit recovery"),
            self.owner_user,
        ))
        self.assertEqual(res_retry["status"], "APPROVED")

        ledger_final = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns_final = [tx for tx in ledger_final if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns_final), 1)
        wh_bal, _ = balances(ledger_final)
        self.assertEqual(wh_bal["PRD-MOONG-200G"], 98)

        approval_audits = self._approval_audits(disc_id)
        self.assertEqual(len(approval_audits), 1)
        self.assertEqual(approval_audits[0]["related_record_id"], f"AUDIT-DISC-{disc_id}-APPROVED")

    def test_I_audit_succeeds_but_status_update_fails_then_retry_completes_cleanly(self):
        """Test I: Status update failure recovery (with and without pre-existing approval audit) produces 1 ledger row, 1 audit event, and APPROVED status."""
        # Part 1: Inject StockDiscrepancies update failure during approval -> retry finishes with 1 ledger + 1 audit
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=97,
            reason="3 packets short for Test I part 1",
        )
        sub1 = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id_1 = sub1["discrepancy_id"]

        db.inject_failure_once("StockDiscrepancies", 1)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.review_stock_discrepancy(
                disc_id_1,
                stock.StockDiscrepancyReview(action="APPROVE", notes="Attempt 1 status fail"),
                self.owner_user,
            ))
        self.assertEqual(ctx.exception.status_code, 503)

        res1 = asyncio.run(stock.review_stock_discrepancy(
            disc_id_1,
            stock.StockDiscrepancyReview(action="APPROVE", notes="Retry 1"),
            self.owner_user,
        ))
        self.assertEqual(res1["status"], "APPROVED")
        ledger1 = db.get_records("SalesmanStockLedger", fresh=True)
        self.assertEqual(len([tx for tx in ledger1 if str(tx.get("reference_id")) == f"DISC-{disc_id_1}"]), 1)
        self.assertEqual(len(self._approval_audits(disc_id_1)), 1)

        # Part 2: Pre-existing approval audit event succeeded while StockDiscrepancies remained PENDING_APPROVAL
        self.setUp()
        disc_req2 = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=96,
            reason="4 packets short for Test I part 2",
        )
        sub2 = asyncio.run(stock.submit_stock_discrepancy(disc_req2, self.owner_user))
        disc_id_2 = sub2["discrepancy_id"]

        db.append_record("AuditLog", {
            "audit_id": db.generate_id("AuditLog"),
            "event_datetime": datetime.now(timezone.utc).isoformat(),
            "actor_user_id": self.owner_user["user_id"],
            "action": "APPROVED_STOCK_DISCREPANCY",
            "entity_type": "StockDiscrepancies",
            "entity_id": disc_id_2,
            "field_changed": "status",
            "old_value": "PENDING_APPROVAL",
            "new_value": "APPROVED",
            "reason": f"APPROVED stock discrepancy {disc_id_2}. Adjustment: -4.",
            "approved_by_user_id": self.owner_user["user_id"],
            "related_record_id": f"AUDIT-DISC-{disc_id_2}-APPROVED",
        }, raise_on_error=True)

        db.inject_failure_once("StockDiscrepancies", 1)
        with self.assertRaises(HTTPException) as ctx2:
            asyncio.run(stock.review_stock_discrepancy(
                disc_id_2,
                stock.StockDiscrepancyReview(action="APPROVE", notes="Status fail with pre-written audit"),
                self.owner_user,
            ))
        self.assertEqual(ctx2.exception.status_code, 503)

        res2 = asyncio.run(stock.review_stock_discrepancy(
            disc_id_2,
            stock.StockDiscrepancyReview(action="APPROVE", notes="Retry completes status"),
            self.owner_user,
        ))
        self.assertEqual(res2["status"], "APPROVED")
        curr_disc2 = next(r for r in db.get_records("StockDiscrepancies", fresh=True) if r["discrepancy_id"] == disc_id_2)
        self.assertEqual(curr_disc2["status"], "APPROVED")
        ledger2 = db.get_records("SalesmanStockLedger", fresh=True)
        self.assertEqual(len([tx for tx in ledger2 if str(tx.get("reference_id")) == f"DISC-{disc_id_2}"]), 1)
        self.assertEqual(len(self._approval_audits(disc_id_2)), 1)

    def test_J_repeated_approval_after_recovery_is_fully_idempotent(self):
        """Test J: Repeated approvals after audit recovery create 0 extra ledger adjustments and 0 duplicate audit events."""
        disc_req = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=95,
            reason="5 packets missing for Test J",
        )
        sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
        disc_id = sub["discrepancy_id"]

        db.inject_failure_once("AuditLog", 1)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.review_stock_discrepancy(
                disc_id,
                stock.StockDiscrepancyReview(action="APPROVE", notes="Fail audit once"),
                self.owner_user,
            ))
        self.assertEqual(ctx.exception.status_code, 503)

        # Recover + call approval repeatedly 3 more times
        for attempt in range(4):
            res = asyncio.run(stock.review_stock_discrepancy(
                disc_id,
                stock.StockDiscrepancyReview(action="APPROVE", notes=f"Repeat attempt {attempt}"),
                self.owner_user,
            ))
            self.assertEqual(res["status"], "APPROVED")

        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        disc_txns = [tx for tx in ledger if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
        self.assertEqual(len(disc_txns), 1)
        self.assertEqual(len(self._approval_audits(disc_id)), 1)
        wh_bal, _ = balances(ledger)
        self.assertEqual(wh_bal["PRD-MOONG-200G"], 95)

    def test_K_concurrent_approval_with_audit_recovery(self):
        """Test K: Two separate OS processes racing on approval & audit-recovery produce 1 ledger adjustment and 1 audit event."""
        # Phase 1: Concurrent audit-recovery race after AuditLog write failure
        for iteration in range(2):
            self.setUp()
            disc_req = stock.StockDiscrepancyCreate(
                location="WAREHOUSE",
                product_id="PRD-MOONG-200G",
                expected_stock=100,
                physical_count=98,
                reason=f"Concurrent audit recovery iter {iteration}",
            )
            sub = asyncio.run(stock.submit_stock_discrepancy(disc_req, self.owner_user))
            disc_id = sub["discrepancy_id"]

            # Simulate initial partial failure where ledger & status=APPROVED succeeded but AuditLog write failed
            db.inject_failure_once("AuditLog", 1)
            with self.assertRaises(HTTPException) as ctx_init:
                asyncio.run(stock.review_stock_discrepancy(
                    disc_id,
                    stock.StockDiscrepancyReview(action="APPROVE", notes="Initial failed audit"),
                    self.owner_user,
                ))
            self.assertEqual(ctx_init.exception.status_code, 503)
            self.assertEqual(len(self._approval_audits(disc_id)), 0)

            ctx = multiprocessing.get_context("fork")
            res_q = ctx.Queue()
            barrier = ctx.Barrier(2)
            p1 = ctx.Process(
                target=_concurrent_review_worker,
                args=(self.test_dir, disc_id, "APPROVE", "Worker 1 recovery", self.owner_user, res_q, barrier),
            )
            p2 = ctx.Process(
                target=_concurrent_review_worker,
                args=(self.test_dir, disc_id, "APPROVE", "Worker 2 recovery", self.owner_user, res_q, barrier),
            )
            p1.start()
            p2.start()
            p1.join(timeout=10)
            p2.join(timeout=10)

            results = []
            while not res_q.empty():
                results.append(res_q.get_nowait())
            self.assertEqual(len(results), 2)
            pids = sorted({r["pid"] for r in results})
            self.assertEqual(len(pids), 2)
            for r in results:
                self.assertTrue(r.get("success"), f"Unexpected failure during concurrent audit recovery: {r}")
                self.assertEqual(r["result"]["status"], "APPROVED")

            ledger = db.get_records("SalesmanStockLedger", fresh=True)
            disc_txns = [tx for tx in ledger if str(tx.get("reference_id")) == f"DISC-{disc_id}"]
            self.assertEqual(len(disc_txns), 1)
            audits = self._approval_audits(disc_id)
            self.assertEqual(len(audits), 1)
            curr_disc = next(r for r in db.get_records("StockDiscrepancies", fresh=True) if r["discrepancy_id"] == disc_id)
            self.assertEqual(curr_disc["status"], "APPROVED")
            print(f"[Discrepancy Test K recovery iter={iteration}] PIDs={pids} ledger_rows=1 audit_rows=1 status=APPROVED")

        # Phase 2: Concurrent normal approval across 2 OS processes verifies exactly 1 ledger + 1 audit row
        self.setUp()
        disc_req_fresh = stock.StockDiscrepancyCreate(
            location="WAREHOUSE",
            product_id="PRD-MOONG-200G",
            expected_stock=100,
            physical_count=94,
            reason="Concurrent normal approval check for audit uniqueness",
        )
        sub_fresh = asyncio.run(stock.submit_stock_discrepancy(disc_req_fresh, self.owner_user))
        disc_id_fresh = sub_fresh["discrepancy_id"]

        ctx = multiprocessing.get_context("fork")
        res_q2 = ctx.Queue()
        barrier2 = ctx.Barrier(2)
        p3 = ctx.Process(
            target=_concurrent_review_worker,
            args=(self.test_dir, disc_id_fresh, "APPROVE", "Worker A", self.owner_user, res_q2, barrier2),
        )
        p4 = ctx.Process(
            target=_concurrent_review_worker,
            args=(self.test_dir, disc_id_fresh, "APPROVE", "Worker B", self.owner_user, res_q2, barrier2),
        )
        p3.start()
        p4.start()
        p3.join(timeout=10)
        p4.join(timeout=10)

        results2 = []
        while not res_q2.empty():
            results2.append(res_q2.get_nowait())
        self.assertEqual(len(results2), 2)
        pids2 = sorted({r["pid"] for r in results2})
        self.assertEqual(len(pids2), 2)
        for r in results2:
            self.assertTrue(r.get("success"), f"Unexpected failure: {r}")
            self.assertEqual(r["result"]["status"], "APPROVED")

        ledger_f = db.get_records("SalesmanStockLedger", fresh=True)
        self.assertEqual(len([tx for tx in ledger_f if str(tx.get("reference_id")) == f"DISC-{disc_id_fresh}"]), 1)
        self.assertEqual(len(self._approval_audits(disc_id_fresh)), 1)
        print(f"[Discrepancy Test K normal] PIDs={pids2} ledger_rows=1 audit_rows=1 status=APPROVED")


if __name__ == "__main__":
    unittest.main()
