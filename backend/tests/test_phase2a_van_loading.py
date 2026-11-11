# backend/tests/test_phase2a_van_loading.py
"""
Kawad Swad ERP - Phase 2A.1 Morning Van Loading Pass Test Suite
Verifies:
1. Two-party custody handshake (Warehouse Keeper Issues -> Salesman Accepts).
2. Atomic finished goods transfer between Central Warehouse and Van.
3. Conservation of combined finished stock (Warehouse + Van variance == 0).
4. Prevention of negative warehouse stock.
5. Strict role authorization (salesmen cannot issue; salesmen cannot accept another salesman's pass).
6. Idempotency against duplicate submissions and duplicate acceptances.
7. Multiprocessing concurrent acceptance safety with POSIX advisory file locking.
8. Physical discrepancy reporting.
9. Cancelled pass protection.
10. Audit trail completeness.
"""

import asyncio
import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from fastapi import HTTPException

# Configure paths
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
from app.models import (
    VanLoadingItem,
    VanLoadingPassCreate,
    VanLoadingPassDiscrepancy,
    LoadingPassActionReq,
)
from app.routers import stock


def _concurrent_accept_worker(test_dir: str, pass_id: str, salesman_user: dict, result_queue: multiprocessing.Queue):
    """Isolated worker process attempting to accept a loading pass under advisory file locking."""
    try:
        db.enable_shared_file_store(test_dir)
        res = asyncio.run(stock.accept_van_loading_pass(pass_id, req=None, current_user=salesman_user))
        result_queue.put({"success": True, "status": res.status, "pass_id": res.pass_id})
    except Exception as exc:
        result_queue.put({"success": False, "error": str(exc), "type": type(exc).__name__})


def _competing_pass_worker(test_dir: str, pass_id: str, salesman_user: dict, result_queue: multiprocessing.Queue):
    """Isolated worker process attempting to accept a competing pass for warehouse inventory."""
    try:
        db.enable_shared_file_store(test_dir)
        res = asyncio.run(stock.accept_van_loading_pass(pass_id, req=None, current_user=salesman_user))
        result_queue.put({"success": True, "pass_id": pass_id, "status": res.status})
    except HTTPException as exc:
        result_queue.put({"success": False, "pass_id": pass_id, "status_code": exc.status_code, "detail": exc.detail})
    except Exception as exc:
        result_queue.put({"success": False, "pass_id": pass_id, "status_code": 500, "error": str(exc)})


class TestPhase2AVanLoadingPass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="ks_van_loading_test_")
        db.enable_shared_file_store(cls.test_dir)

    @classmethod
    def tearDownClass(cls):
        db.disable_shared_file_store()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        # Reset memory and shared files for a clean slate
        db.enable_shared_file_store(self.test_dir)
        for tab in list(db.memory_store.keys()):
            path = db._tab_file_path(tab)
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass
            db.memory_store[tab] = []

        # Users setup
        self.owner_user = {"user_id": "USR-TEST-OWNER", "full_name": "Ramesh Owner", "role": "OWNER"}
        self.keeper_user = {"user_id": "USR-TEST-KEEPER", "full_name": "Kailash Storekeeper", "role": "PA"}
        self.salesman_101 = {"user_id": "USR-SALES-101", "full_name": "Mohan Lal", "role": "SALESMAN"}
        self.salesman_102 = {"user_id": "USR-SALES-102", "full_name": "Sohan Singh", "role": "SALESMAN"}

        for u in [self.owner_user, self.keeper_user, self.salesman_101, self.salesman_102]:
            db.append_record("Users", {
                "user_id": u["user_id"],
                "full_name": u["full_name"],
                "role": u["role"],
                "active": "true",
            })

        # Products setup
        self.products = [
            {"product_id": "PRD-MOONG-200G", "sku": "KS-MNG-200", "product_name": "Moong Master 200g", "pack_weight_g": 200, "selling_unit": "PACKET", "active": True},
            {"product_id": "PRD-GARLIC-200G", "sku": "KS-GRL-200", "product_name": "Moong Garlic 200g", "pack_weight_g": 200, "selling_unit": "PACKET", "active": True},
            {"product_id": "PRD-CHANA-200G", "sku": "KS-CHN-200", "product_name": "Chana Chotu 200g", "pack_weight_g": 200, "selling_unit": "PACKET", "active": True},
            {"product_id": "PRD-URAD-500G", "sku": "KS-URD-500", "product_name": "Urad Guru 500g", "pack_weight_g": 500, "selling_unit": "PACKET", "active": True},
        ]
        for p in self.products:
            db.append_record("Products", p)

        # Seed Central Warehouse Stock via COMPANY_RECEIPT
        # Moong: 100 pkts, Garlic: 80 pkts, Chana: 60 pkts, Urad: 50 pkts
        seed_inventory = [
            ("PRD-MOONG-200G", 100),
            ("PRD-GARLIC-200G", 80),
            ("PRD-CHANA-200G", 60),
            ("PRD-URAD-500G", 50),
        ]
        for pid, qty in seed_inventory:
            db.append_record("SalesmanStockLedger", {
                "stock_txn_id": db.generate_id("SalesmanStockLedger"),
                "movement_id": db.generate_id("SalesmanStockLedger"),
                "txn_datetime": datetime.now(timezone.utc).isoformat(),
                "salesman_user_id": "",
                "product_id": pid,
                "sku_snapshot": pid,
                "txn_type": "COMPANY_RECEIPT",
                "quantity": qty,
                "quantity_packets": qty,
                "unit": "PACKET",
                "pack_weight_g": 200 if "200G" in pid else 500,
                "issued_by_user_id": "USR-TEST-OWNER",
                "received_by_user_id": "WAREHOUSE",
                "reference_id": "FACTORY-INITIAL-RECEIPT",
                "notes": "Initial factory dispatch to central warehouse",
            })

    def test_01_successful_loading_creation_and_acceptance(self):
        """Happy Path: Warehouse keeper creates loading pass, salesman accepts, stock transfers atomically."""
        ledger_before = db.get_records("SalesmanStockLedger", fresh=True)
        wh_before, _ = balances(ledger_before)
        self.assertEqual(wh_before["PRD-MOONG-200G"], 100)
        self.assertEqual(wh_before["PRD-GARLIC-200G"], 80)
        self.assertEqual(wh_before["PRD-CHANA-200G"], 60)
        self.assertEqual(wh_before["PRD-URAD-500G"], 50)

        # Step A: Create Loading Pass
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[
                VanLoadingItem(product_id="PRD-MOONG-200G", quantity=40),
                VanLoadingItem(product_id="PRD-GARLIC-200G", quantity=30),
                VanLoadingItem(product_id="PRD-CHANA-200G", quantity=25),
                VanLoadingItem(product_id="PRD-URAD-500G", quantity=20),
            ],
            notes="Morning delivery route #1 - Bhilwara Central Market",
        )

        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))
        self.assertTrue(pass_resp.pass_id.startswith("VLP-"))
        self.assertTrue(pass_resp.pass_number.startswith("LP-20261112-"))
        self.assertEqual(pass_resp.status, "PENDING_ACCEPTANCE")
        self.assertEqual(pass_resp.total_skus, 4)
        self.assertEqual(pass_resp.total_packets, 115)  # 40+30+25+20
        # Weights: 40*0.2 + 30*0.2 + 25*0.2 + 20*0.5 = 8 + 6 + 5 + 10 = 29.0 kg
        self.assertAlmostEqual(pass_resp.total_weight_kg, 29.0, places=2)

        # Before acceptance, stock must remain intact in warehouse
        ledger_mid = db.get_records("SalesmanStockLedger", fresh=True)
        wh_mid, _ = balances(ledger_mid)
        self.assertEqual(wh_mid["PRD-MOONG-200G"], 100)
        self.assertEqual(salesman_available(ledger_mid, "USR-SALES-101", "PRD-MOONG-200G"), 0)

        # Step C & D: Salesman Verifies & Accepts Loading
        accept_resp = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(accept_resp.status, "ACCEPTED")
        self.assertEqual(accept_resp.accepted_by_user_id, "USR-SALES-101")
        self.assertTrue(bool(accept_resp.accepted_at))

        # Check final balances in canonical ledger
        ledger_after = db.get_records("SalesmanStockLedger", fresh=True)
        wh_after, _ = balances(ledger_after)

        # 1. Warehouse stock decreases by exactly the accepted quantity
        self.assertEqual(wh_after["PRD-MOONG-200G"], 60)   # 100 - 40
        self.assertEqual(wh_after["PRD-GARLIC-200G"], 50)  # 80 - 30
        self.assertEqual(wh_after["PRD-CHANA-200G"], 35)   # 60 - 25
        self.assertEqual(wh_after["PRD-URAD-500G"], 30)    # 50 - 20

        # 2. Van stock increases by exactly the same quantity
        self.assertEqual(salesman_available(ledger_after, "USR-SALES-101", "PRD-MOONG-200G"), 40)
        self.assertEqual(salesman_available(ledger_after, "USR-SALES-101", "PRD-GARLIC-200G"), 30)
        self.assertEqual(salesman_available(ledger_after, "USR-SALES-101", "PRD-CHANA-200G"), 25)
        self.assertEqual(salesman_available(ledger_after, "USR-SALES-101", "PRD-URAD-500G"), 20)

        # 3. Warehouse plus van combined stock remains unchanged (0 variance)
        for pid in ["PRD-MOONG-200G", "PRD-GARLIC-200G", "PRD-CHANA-200G", "PRD-URAD-500G"]:
            total_after = wh_after[pid] + salesman_available(ledger_after, "USR-SALES-101", pid)
            self.assertEqual(total_after, wh_before[pid])

    def test_02_insufficient_warehouse_stock_rejected(self):
        """Warehouse stock cannot become negative; request exceeding available stock is rejected."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[
                VanLoadingItem(product_id="PRD-MOONG-200G", quantity=150),  # Only 100 available!
            ],
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Insufficient warehouse stock", ctx.exception.detail)

        # Ensure no pass was recorded
        passes = db.get_records("VanLoadingPasses", fresh=True)
        self.assertEqual(len(passes), 0)

    def test_03_unauthorized_loading_creation_rejected(self):
        """Salesmen cannot create loading passes; only authorized storekeepers/managers can."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=10)],
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.salesman_101))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("not authorized to create van loading passes", ctx.exception.detail)

    def test_04_wrong_salesman_acceptance_rejected(self):
        """Salesmen can accept only their assigned van's loading pass."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=20)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        # Salesman 102 attempts to accept Salesman 101's pass
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_102))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("cannot accept a loading pass assigned to another salesman", ctx.exception.detail)

        # Status must remain PENDING_ACCEPTANCE and stock untouched
        curr = asyncio.run(stock.get_van_loading_pass(pass_resp.pass_id, current_user=self.keeper_user))
        self.assertEqual(curr.status, "PENDING_ACCEPTANCE")

    def test_05_duplicate_acceptance_is_idempotent(self):
        """Accepting an already-accepted loading pass must be idempotent and never duplicate stock credits."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=25)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        # First acceptance
        resp1 = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(resp1.status, "ACCEPTED")

        # Second acceptance (e.g. mobile button double-click / network retry)
        resp2 = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(resp2.status, "ACCEPTED")

        # Verify stock was credited exactly once (25 packets, never 50 packets)
        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        salesman_qty = salesman_available(ledger, "USR-SALES-101", "PRD-MOONG-200G")
        self.assertEqual(salesman_qty, 25)

        # Count ISSUE_TO_SALESMAN records for this pass
        matching_txns = [r for r in ledger if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(matching_txns), 1)

    def test_06_duplicate_creation_with_idempotency_key(self):
        """Duplicate creation with identical idempotency_key returns original pass without duplication."""
        req1 = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=15)],
            idempotency_key="IDEM-VAN-LOAD-999",
        )
        p1 = asyncio.run(stock.create_van_loading_pass(req1, current_user=self.keeper_user))

        req2 = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=15)],
            idempotency_key="IDEM-VAN-LOAD-999",
        )
        p2 = asyncio.run(stock.create_van_loading_pass(req2, current_user=self.keeper_user))

        self.assertEqual(p1.pass_id, p2.pass_id)
        self.assertEqual(p1.pass_number, p2.pass_number)

        # Verify only 1 pass exists in storage
        all_passes = db.get_records("VanLoadingPasses", fresh=True)
        self.assertEqual(len(all_passes), 1)

        # Reusing the same idempotency key with conflicting payload must return HTTP 409
        req_conflict = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=99)],
            idempotency_key="IDEM-VAN-LOAD-999",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.create_van_loading_pass(req_conflict, current_user=self.keeper_user))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Conflict: Idempotency key reused", ctx.exception.detail)

    def test_07_concurrent_acceptance_multiprocessing(self):
        """Multiprocessing test: Two separate OS worker processes simultaneously call accept."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=30)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        ctx = multiprocessing.get_context("fork")
        result_queue = ctx.Queue()

        p1 = ctx.Process(
            target=_concurrent_accept_worker,
            args=(self.test_dir, pass_resp.pass_id, self.salesman_101, result_queue),
        )
        p2 = ctx.Process(
            target=_concurrent_accept_worker,
            args=(self.test_dir, pass_resp.pass_id, self.salesman_101, result_queue),
        )

        p1.start()
        p2.start()

        results = []
        for _ in range(2):
            try:
                res = result_queue.get(timeout=10.0)
                results.append(res)
            except Exception:
                break

        p1.join(timeout=5.0)
        p2.join(timeout=5.0)

        # Both should succeed or report already accepted
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(r.get("success"), f"Worker failure: {r}")

        # In canonical ledger, stock must be credited exactly once (30 pkts, not 60 pkts)
        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        van_bal = salesman_available(ledger, "USR-SALES-101", "PRD-MOONG-200G")
        self.assertEqual(van_bal, 30)

        pass_txns = [r for r in ledger if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(pass_txns), 1)

    def test_08_physical_discrepancy_reporting(self):
        """Salesman can report a physical quantity discrepancy; does not transfer stock."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-CHANA-200G", quantity=25)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        disc_req = VanLoadingPassDiscrepancy(
            discrepancy_notes="Chana Chotu 200g has 2 packets torn and leaking; counted 23 intact packets."
        )
        updated = asyncio.run(stock.report_van_loading_discrepancy(pass_resp.pass_id, disc_req, current_user=self.salesman_101))
        self.assertEqual(updated.status, "DISCREPANCY_REPORTED")
        self.assertIn("2 packets torn", updated.discrepancy_notes)

        # Stock must NOT be credited to van
        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        van_bal = salesman_available(ledger, "USR-SALES-101", "PRD-CHANA-200G")
        self.assertEqual(van_bal, 0)

        # Also logged in StockDiscrepancies for manager action
        discs = db.get_records("StockDiscrepancies", fresh=True)
        van_disc = next((d for d in discs if "Van Loading Discrepancy" in str(d.get("product_name_snapshot"))), None)
        self.assertIsNotNone(van_disc)
        self.assertIn("2 packets torn", str(van_disc.get("reason")))

    def test_09_cancelled_loading_pass_cannot_be_accepted(self):
        """Cancelled loading pass cannot be accepted."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=10)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        # Keeper cancels
        cancel_req = LoadingPassActionReq(notes="Van 1 battery dead; loading reassigned to Van 2")
        cancelled = asyncio.run(stock.cancel_van_loading_pass(pass_resp.pass_id, cancel_req, current_user=self.keeper_user))
        self.assertEqual(cancelled.status, "CANCELLED")

        # Salesman attempts to accept
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Cannot accept a cancelled loading pass", ctx.exception.detail)

    def test_10_audit_trail_completeness(self):
        """Audit trail records pass creation and pass acceptance."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=10)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))
        asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))

        audits = db.get_records("AuditLog", fresh=True)
        create_audit = next((a for a in audits if str(a.get("action")) == "CREATE_VAN_LOADING_PASS" and str(a.get("entity_id")) == pass_resp.pass_id), None)
        accept_audit = next((a for a in audits if str(a.get("action")) == "ACCEPT_VAN_LOADING_PASS" and str(a.get("entity_id")) == pass_resp.pass_id), None)

        self.assertIsNotNone(create_audit)
        self.assertEqual(create_audit.get("actor_user_id"), "USR-TEST-KEEPER")
        self.assertIsNotNone(accept_audit)
        self.assertEqual(accept_audit.get("actor_user_id"), "USR-SALES-101")

    def test_11_partial_transfer_failure_first_sku_succeeds_second_fails_and_recovery(self):
        """Blocker 1: First SKU succeeds, second fails. Retrying completes transfer without duplication."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[
                VanLoadingItem(product_id="PRD-MOONG-200G", quantity=30),
                VanLoadingItem(product_id="PRD-GARLIC-200G", quantity=20),
            ],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        original_append = db.append_record
        append_call_count = 0

        def flaky_append(tab_name, record, raise_on_error=False):
            nonlocal append_call_count
            if tab_name == "SalesmanStockLedger" and record.get("product_id") == "PRD-GARLIC-200G" and append_call_count == 0:
                append_call_count += 1
                if raise_on_error:
                    raise RuntimeError("Injected disk failure on second SKU append")
                return False
            return original_append(tab_name, record, raise_on_error=raise_on_error)

        db.append_record = flaky_append
        try:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
            self.assertEqual(ctx.exception.status_code, 503)
        finally:
            db.append_record = original_append

        # Pass status must remain PENDING_ACCEPTANCE (fail closed, never prematurely ACCEPTED)
        curr = asyncio.run(stock.get_van_loading_pass(pass_resp.pass_id, current_user=self.keeper_user))
        self.assertEqual(curr.status, "PENDING_ACCEPTANCE")

        # In ledger: Moong was recorded (30 pkts), Garlic was not
        ledger_mid = db.get_records("SalesmanStockLedger", fresh=True)
        pass_txns_mid = [r for r in ledger_mid if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(pass_txns_mid), 1)
        self.assertEqual(pass_txns_mid[0].get("product_id"), "PRD-MOONG-200G")

        # Retry acceptance with healthy storage
        recovered = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(recovered.status, "ACCEPTED")

        # Verify final balances
        ledger_final = db.get_records("SalesmanStockLedger", fresh=True)
        wh_final, _ = balances(ledger_final)
        self.assertEqual(wh_final["PRD-MOONG-200G"], 70)   # 100 - 30
        self.assertEqual(wh_final["PRD-GARLIC-200G"], 60)  # 80 - 20
        self.assertEqual(salesman_available(ledger_final, "USR-SALES-101", "PRD-MOONG-200G"), 30)
        self.assertEqual(salesman_available(ledger_final, "USR-SALES-101", "PRD-GARLIC-200G"), 20)

        # Verify exactly 2 movements exist for this pass (one for Moong, one for Garlic, NO duplicate)
        pass_txns_final = [r for r in ledger_final if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(pass_txns_final), 2)
        pids = [r.get("product_id") for r in pass_txns_final]
        self.assertIn("PRD-MOONG-200G", pids)
        self.assertIn("PRD-GARLIC-200G", pids)

    def test_12_partial_transfer_failure_first_two_succeed_third_fails_and_recovery(self):
        """Blocker 1: First two succeed, third fails. Retry completes only the third."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[
                VanLoadingItem(product_id="PRD-MOONG-200G", quantity=20),
                VanLoadingItem(product_id="PRD-GARLIC-200G", quantity=15),
                VanLoadingItem(product_id="PRD-CHANA-200G", quantity=10),
            ],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        original_append = db.append_record
        append_call_count = 0

        def flaky_append(tab_name, record, raise_on_error=False):
            nonlocal append_call_count
            if tab_name == "SalesmanStockLedger" and record.get("product_id") == "PRD-CHANA-200G" and append_call_count == 0:
                append_call_count += 1
                if raise_on_error:
                    raise RuntimeError("Injected failure on third SKU append")
                return False
            return original_append(tab_name, record, raise_on_error=raise_on_error)

        db.append_record = flaky_append
        try:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
            self.assertEqual(ctx.exception.status_code, 503)
        finally:
            db.append_record = original_append

        # Status remains pending
        curr = asyncio.run(stock.get_van_loading_pass(pass_resp.pass_id, current_user=self.keeper_user))
        self.assertEqual(curr.status, "PENDING_ACCEPTANCE")

        # Retry and recover
        recovered = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(recovered.status, "ACCEPTED")

        ledger_final = db.get_records("SalesmanStockLedger", fresh=True)
        wh_final, _ = balances(ledger_final)
        self.assertEqual(wh_final["PRD-MOONG-200G"], 80)
        self.assertEqual(wh_final["PRD-GARLIC-200G"], 65)
        self.assertEqual(wh_final["PRD-CHANA-200G"], 50)
        self.assertEqual(salesman_available(ledger_final, "USR-SALES-101", "PRD-MOONG-200G"), 20)
        self.assertEqual(salesman_available(ledger_final, "USR-SALES-101", "PRD-GARLIC-200G"), 15)
        self.assertEqual(salesman_available(ledger_final, "USR-SALES-101", "PRD-CHANA-200G"), 10)

        pass_txns = [r for r in ledger_final if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(pass_txns), 3)

    def test_13_failure_while_updating_pass_status_after_all_movements_and_recovery(self):
        """Blocker 1: Failure while updating pass status after all movements succeed. Retry updates status with 0 new stock movements."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[
                VanLoadingItem(product_id="PRD-MOONG-200G", quantity=15),
                VanLoadingItem(product_id="PRD-GARLIC-200G", quantity=10),
            ],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        # Inject failure on VanLoadingPasses update
        db.inject_failure_once("VanLoadingPasses", 1)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(ctx.exception.status_code, 503)

        # Both items are already recorded in ledger
        ledger_mid = db.get_records("SalesmanStockLedger", fresh=True)
        pass_txns_mid = [r for r in ledger_mid if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(pass_txns_mid), 2)

        # Pass is still PENDING_ACCEPTANCE
        curr = asyncio.run(stock.get_van_loading_pass(pass_resp.pass_id, current_user=self.keeper_user))
        self.assertEqual(curr.status, "PENDING_ACCEPTANCE")

        # Retry: Should verify all movements already present, append 0 new movements, and mark ACCEPTED
        recovered = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(recovered.status, "ACCEPTED")

        ledger_final = db.get_records("SalesmanStockLedger", fresh=True)
        pass_txns_final = [r for r in ledger_final if str(r.get("reference_id")) == pass_resp.pass_number]
        self.assertEqual(len(pass_txns_final), 2)  # Zero duplicates!

    def test_14_authoritative_warehouse_stock_calculations(self):
        """Blocker 2: Authoritative warehouse stock calculations. Canonical stock ledger is sole source of truth."""
        # 1. Packaging records exceed ledger stock: ledger=50, packaging=500 -> available must be 50
        db.append_record("PackagingBatches", {
            "batch_id": "PKG-TEST-001",
            "product_id": "PRD-URAD-500G",
            "packets_produced": 500,
            "status": "APPROVED",
        })
        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        comp_bals, _ = balances(ledger)
        avail = stock._get_available_warehouse_stock("PRD-URAD-500G", comp_bals)
        self.assertEqual(avail, 50)  # Exactly the 50 from SalesmanStockLedger, NOT 500

        # Requesting 51 must fail even though PackagingBatches shows 500
        req_51 = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-URAD-500G", quantity=51)],
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.create_van_loading_pass(req_51, current_user=self.keeper_user))
        self.assertEqual(ctx.exception.status_code, 422)

        # Requesting exactly 50 (available == requested) must succeed
        req_50 = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-URAD-500G", quantity=50)],
        )
        p50 = asyncio.run(stock.create_van_loading_pass(req_50, current_user=self.keeper_user))
        self.assertEqual(p50.status, "PENDING_ACCEPTANCE")

        # 2. Production records exceed ledger stock
        db.append_record("ProductionStockLedger", {
            "stock_txn_id": "PSL-TEST-001",
            "product_id": "PRD-URAD-500G",
            "movement_type": "PACKETS_PACKAGED",
            "quantity_packets": 1000,
        })
        avail2 = stock._get_available_warehouse_stock("PRD-URAD-500G", comp_bals)
        self.assertEqual(avail2, 50)  # Still 50, production ledger does not override

        # 3. Ledger stock is zero while packaging/production shows 1000
        comp_bals_zero = {"PRD-ZERO-STOCK": 0}
        avail_zero = stock._get_available_warehouse_stock("PRD-ZERO-STOCK", comp_bals_zero)
        self.assertEqual(avail_zero, 0)

        # 4. Ledger stock is negative (-5)
        comp_bals_neg = {"PRD-NEG-STOCK": -5}
        avail_neg = stock._get_available_warehouse_stock("PRD-NEG-STOCK", comp_bals_neg)
        self.assertEqual(avail_neg, -5)

    def test_15_concurrent_passes_competing_for_same_warehouse_stock_multiprocessing(self):
        """Blocker 3: Multiprocessing test with competing passes. Warehouse has 100, Pass A requests 70, Pass B requests 60. Exactly one succeeds."""
        # Repeat test across 3 iterations to guarantee absolute concurrency stability
        for iteration in range(3):
            # Clean and re-seed 100 packets of Moong for this iteration
            self.setUp()

            # Create Pass A (70 pkts for Salesman 101)
            req_a = VanLoadingPassCreate(
                loading_date="2026-11-12",
                van_number="Van 1",
                salesman_user_id="USR-SALES-101",
                items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=70)],
            )
            pass_a = asyncio.run(stock.create_van_loading_pass(req_a, current_user=self.keeper_user))

            # Create Pass B (60 pkts for Salesman 102)
            req_b = VanLoadingPassCreate(
                loading_date="2026-11-12",
                van_number="Van 2",
                salesman_user_id="USR-SALES-102",
                items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=60)],
            )
            pass_b = asyncio.run(stock.create_van_loading_pass(req_b, current_user=self.keeper_user))

            ctx = multiprocessing.get_context("fork")
            q = ctx.Queue()

            p1 = ctx.Process(target=_competing_pass_worker, args=(self.test_dir, pass_a.pass_id, self.salesman_101, q))
            p2 = ctx.Process(target=_competing_pass_worker, args=(self.test_dir, pass_b.pass_id, self.salesman_102, q))

            p1.start()
            p2.start()

            results = []
            for _ in range(2):
                try:
                    results.append(q.get(timeout=10.0))
                except Exception:
                    break

            p1.join(timeout=5.0)
            p2.join(timeout=5.0)

            self.assertEqual(len(results), 2, f"Iteration {iteration}: Expected 2 results, got {len(results)}")
            successes = [r for r in results if r.get("success")]
            failures = [r for r in results if not r.get("success")]

            # Exactly one may succeed
            self.assertEqual(len(successes), 1, f"Iteration {iteration}: Exactly one pass must succeed: {results}")
            self.assertEqual(len(failures), 1, f"Iteration {iteration}: Exactly one pass must fail: {results}")
            self.assertEqual(failures[0].get("status_code"), 422)

            # Check final balances in canonical ledger
            ledger = db.get_records("SalesmanStockLedger", fresh=True)
            wh_bal, _ = balances(ledger)
            final_wh = wh_bal.get("PRD-MOONG-200G", 0)

            # Final warehouse balance must never be negative
            self.assertGreaterEqual(final_wh, 0, f"Iteration {iteration}: Warehouse balance negative: {final_wh}")

            # Total salesman stock issued must never exceed 100
            s1_stock = salesman_available(ledger, "USR-SALES-101", "PRD-MOONG-200G")
            s2_stock = salesman_available(ledger, "USR-SALES-102", "PRD-MOONG-200G")
            self.assertLessEqual(s1_stock + s2_stock, 100)

            # Exactly one pass was transferred: either 70 or 60
            self.assertIn(s1_stock + s2_stock, {60, 70})
            self.assertEqual(final_wh + s1_stock + s2_stock, 100)

    def test_16_safe_state_transitions_and_racing_protection(self):
        """Blocker 4: Safe state transitions. ACCEPTED cannot be cancelled; CANCELLED cannot be accepted; discrepancy failure fails closed."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-MOONG-200G", quantity=10)],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        # 1. Accept the pass
        asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))

        # 2. ACCEPTED pass cannot be cancelled
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.cancel_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.keeper_user))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Cannot cancel an accepted loading pass", ctx.exception.detail)

        # 3. ACCEPTED pass cannot report discrepancy
        disc_req = VanLoadingPassDiscrepancy(discrepancy_notes="Count mismatch")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.report_van_loading_discrepancy(pass_resp.pass_id, disc_req, current_user=self.salesman_101))
        self.assertEqual(ctx.exception.status_code, 422)

        # 4. Discrepancy persistence failure: Injected failure on StockDiscrepancies
        p2_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[VanLoadingItem(product_id="PRD-GARLIC-200G", quantity=5)],
        )
        p2 = asyncio.run(stock.create_van_loading_pass(p2_req, current_user=self.keeper_user))

        db.inject_failure_once("StockDiscrepancies", 1)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stock.report_van_loading_discrepancy(p2.pass_id, disc_req, current_user=self.salesman_101))
        self.assertEqual(ctx.exception.status_code, 503)

        # Pass status remains PENDING_ACCEPTANCE
        curr = asyncio.run(stock.get_van_loading_pass(p2.pass_id, current_user=self.keeper_user))
        self.assertEqual(curr.status, "PENDING_ACCEPTANCE")

    def test_17_repeated_retries_during_persistent_outage_then_successful_recovery(self):
        """Blocker 1 & 5: Repeated retries during persistent outage fail closed, then recover cleanly."""
        create_req = VanLoadingPassCreate(
            loading_date="2026-11-12",
            van_number="Van 1",
            salesman_user_id="USR-SALES-101",
            items=[
                VanLoadingItem(product_id="PRD-MOONG-200G", quantity=10),
                VanLoadingItem(product_id="PRD-GARLIC-200G", quantity=10),
            ],
        )
        pass_resp = asyncio.run(stock.create_van_loading_pass(create_req, current_user=self.keeper_user))

        # Inject failures on consecutive attempts
        for attempt in range(3):
            db.inject_failure_once("SalesmanStockLedger", 1)
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
            self.assertEqual(ctx.exception.status_code, 503)

            # Pass remains PENDING_ACCEPTANCE after each failed attempt
            curr = asyncio.run(stock.get_van_loading_pass(pass_resp.pass_id, current_user=self.keeper_user))
            self.assertEqual(curr.status, "PENDING_ACCEPTANCE")

        # Now storage is healthy: retry succeeds
        recovered = asyncio.run(stock.accept_van_loading_pass(pass_resp.pass_id, req=None, current_user=self.salesman_101))
        self.assertEqual(recovered.status, "ACCEPTED")

        # Final balances verified
        ledger = db.get_records("SalesmanStockLedger", fresh=True)
        self.assertEqual(salesman_available(ledger, "USR-SALES-101", "PRD-MOONG-200G"), 10)
        self.assertEqual(salesman_available(ledger, "USR-SALES-101", "PRD-GARLIC-200G"), 10)


if __name__ == "__main__":
    unittest.main()

